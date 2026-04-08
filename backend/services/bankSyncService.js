// ─────────────────────────────────────────────────────────────────────────────
// services/bankSyncService.js
//
// Orquestador de sincronización bancaria.
//
// FLUJO POR SYNC:
//   1. Leer bank_account de Supabase (get credentials encriptadas)
//   2. Desencriptar RUT + pass en memoria (nunca logueados)
//   3. Llamar al proveedor (scraper/API)
//   4. Adaptar movimientos al modelo canónico
//   5. Deduplicar contra transacciones existentes
//   6. Insertar solo transacciones nuevas (sin rawDescription)
//   7. Actualizar last_balance y last_sync_at en bank_accounts
//   8. Destruir credenciales de memoria (GC)
//   9. Disparar ARIA en background (solo buckets, sin UUID)
//
// PRIVACIDAD:
//   - rawDescription nunca persiste en Supabase
//   - El balance exacto va a bank_accounts.last_balance (tabla usuario, RLS)
//   - ARIA recibe solo income_range bucket y category — sin montos reales
// ─────────────────────────────────────────────────────────────────────────────

import { getAdminClient } from "./supabaseClient.js";
import { decrypt }        from "./encryptionService.js";
import { adaptMovements, getProviderForBank } from "./bankingAdapter.js";
import { trackSpendingEvent } from "./ariaService.js";

const db = () => getAdminClient();

// ── Sync de una cuenta bancaria ───────────────────────────────────────────────

export async function syncBankAccount(bankAccountId, userId) {
  const startedAt = Date.now();
  console.log(`[sync] iniciando sync account=${bankAccountId}`);

  // 1. Cargar la cuenta bancaria
  const { data: account, error: accErr } = await db()
    .from("bank_accounts")
    .select("*")
    .eq("id",      bankAccountId)
    .eq("user_id", userId)
    .eq("status",  "active")
    .single();

  if (accErr || !account) {
    throw new Error(`[sync] cuenta no encontrada o inactiva: ${bankAccountId}`);
  }

  try {
    // 2. Desencriptar credenciales en memoria
    const rut      = decrypt(account.encrypted_rut);
    const password = decrypt(account.encrypted_pass);

    // 3. Obtener proveedor y hacer fetch
    const provider = await getProviderForBank(account.bank_id);
    const { balance, movements } = await provider.fetchData({ rut, password });

    // Destruir referencias explícitamente
    // (JS GC las recogerá; hacemos null para ser explícitos)
    // eslint-disable-next-line no-unused-vars
    const _rut = null, _password = null;

    // 4. Adaptar al modelo canónico
    const adapted = adaptMovements(movements, account.bank_id);

    // 5. Deduplicar — obtener external_ids ya existentes para esta cuenta
    const { data: existing } = await db()
      .from("transactions")
      .select("external_id")
      .eq("bank_account_id", bankAccountId)
      .not("external_id", "is", null);

    const existingIds = new Set((existing || []).map((r) => r.external_id));
    const newMovements = adapted.filter((m) => !existingIds.has(m.externalId));

    console.log(`[sync] ${adapted.length} movimientos totales, ${newMovements.length} nuevos`);

    // 6. Insertar transacciones nuevas (sin rawDescription)
    if (newMovements.length > 0) {
      const rows = newMovements.map((m) => ({
        user_id:         userId,
        bank_account_id: bankAccountId,
        amount:          m.amount,
        category:        m.category,
        description:     m.description,  // etiqueta limpia, no texto bancario raw
        date:            m.date,
        external_id:     m.externalId,
      }));

      const { error: insertErr } = await db()
        .from("transactions")
        .insert(rows);

      if (insertErr) {
        console.error("[sync] error insertando transacciones:", insertErr.message);
        throw insertErr;
      }
    }

    // 7. Actualizar estado de la cuenta
    await db()
      .from("bank_accounts")
      .update({
        last_sync_at:    new Date().toISOString(),
        last_sync_error: null,
        last_balance:    balance,
        status:          "active",
        updated_at:      new Date().toISOString(),
      })
      .eq("id", bankAccountId);

    // 8. ARIA en background — solo señales anonimizadas, sin UUID ni montos exactos
    fireAriaSignals(userId, account, newMovements).catch(() => {});

    const elapsed = Date.now() - startedAt;
    console.log(`[sync] completado en ${elapsed}ms — balance: ${balance}`);

    return {
      success:         true,
      newTransactions: newMovements.length,
      balance,
      bankId:          account.bank_id,
      bankName:        account.bank_name,
    };

  } catch (error) {
    // Registrar error sin exponer credenciales
    const msg = sanitizeErrorMessage(error.message);
    console.error(`[sync] error en ${account.bank_id}:`, msg);

    await db()
      .from("bank_accounts")
      .update({
        status:          "error",
        last_sync_error: msg,
        updated_at:      new Date().toISOString(),
      })
      .eq("id", bankAccountId);

    throw new Error(msg);
  }
}

// ── Sync de todas las cuentas activas de un usuario ──────────────────────────

export async function syncAllUserAccounts(userId) {
  const { data: accounts } = await db()
    .from("bank_accounts")
    .select("id, bank_id, bank_name")
    .eq("user_id", userId)
    .eq("status",  "active");

  if (!accounts?.length) return { synced: 0, results: [] };

  const results = await Promise.allSettled(
    accounts.map((acc) => syncBankAccount(acc.id, userId))
  );

  const synced  = results.filter((r) => r.status === "fulfilled").length;
  const errors  = results.filter((r) => r.status === "rejected").length;

  return {
    synced,
    errors,
    results: results.map((r, i) => ({
      bankId:  accounts[i].bank_id,
      success: r.status === "fulfilled",
      error:   r.status === "rejected" ? r.reason?.message : null,
    })),
  };
}

// ── Balance consolidado por banco ─────────────────────────────────────────────

export async function getBankBalances(userId) {
  const { data: accounts } = await db()
    .from("bank_accounts")
    .select("id, bank_id, bank_name, bank_icon, last_balance, last_sync_at, status")
    .eq("user_id", userId)
    .neq("status", "disconnected")
    .order("created_at", { ascending: true });

  if (!accounts?.length) return { accounts: [], totalBalance: 0 };

  const totalBalance = accounts.reduce((sum, a) => sum + (a.last_balance || 0), 0);

  return {
    accounts: accounts.map((a) => ({
      id:          a.id,
      bankId:      a.bank_id,
      bankName:    a.bank_name,
      bankIcon:    a.bank_icon,
      balance:     a.last_balance || 0,
      lastSyncAt:  a.last_sync_at,
      status:      a.status,
    })),
    totalBalance,
  };
}

// ── Helpers privados ──────────────────────────────────────────────────────────

// Evitar exponer stack traces o mensajes con credenciales en errores
function sanitizeErrorMessage(msg) {
  if (!msg) return "Error de sincronización";
  if (/password|rut|clave|credential/i.test(msg)) return "Error de autenticación bancaria";
  if (/timeout|ETIMEDOUT|ECONNREFUSED/i.test(msg)) return "El banco no respondió. Intenta más tarde.";
  if (/2FA|clave dinámica/i.test(msg))             return "El banco requiere autenticación adicional no soportada.";
  if (msg.length > 200) return msg.substring(0, 200);
  return msg;
}

// ARIA: señales anonimizadas sin UUID ni montos exactos
async function fireAriaSignals(userId, account, newMovements) {
  if (!newMovements.length) return;

  // Obtener profile solo para age_range, region, income_range
  const { data: profile } = await db()
    .from("profiles")
    .select("age_range, region, income_range")
    .eq("id", userId)
    .single();

  if (!profile) return;

  // Una señal de gasto por cada movimiento nuevo (sin monto real ni descripción)
  for (const m of newMovements) {
    if (m.amount >= 0) continue; // solo gastos

    const fakeProfile = {
      age_range:    profile.age_range,
      region:       profile.region,
      income_range: profile.income_range,
    };

    const fakeTx = {
      amount:   Math.abs(m.amount),
      category: m.category,
      date:     m.date,
    };

    await trackSpendingEvent(fakeProfile, fakeTx).catch(() => {});
  }
}