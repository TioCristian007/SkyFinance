// ─────────────────────────────────────────────────────────────────────────────
// services/bankSyncService.js
//
// Orquestador de sincronización bancaria.
//
// FLUJO:
//   1. Cargar bank_account (credentials encriptadas)
//   2. Resetear status → "syncing"
//   3. Desencriptar RUT + pass en memoria
//   4. Llamar proveedor con onProgress (reporta estado 2FA en tiempo real)
//   5. Adaptar movimientos al modelo canónico
//   6. Deduplicar contra transacciones existentes
//   7. Insertar solo transacciones nuevas (sin rawDescription)
//   8. Actualizar last_balance, last_sync_at, status → "active"
//   9. ARIA en background (buckets anónimos, sin UUID ni montos exactos)
//
// 2FA (bchile):
//   - onProgress detecta el mensaje de espera 2FA
//   - Escribe "⏳ Esperando aprobación..." en last_sync_error
//   - Frontend lo lee via polling GET /api/banking/accounts
//   - Cuando usuario aprueba en app → scraper continúa → last_sync_error se limpia
// ─────────────────────────────────────────────────────────────────────────────

import { getAdminClient }   from "./supabaseClient.js";
import { decrypt }          from "./encryptionService.js";
import { getProviderForBank }       from "./bankingAdapter.js";
import { categorizeMovements }       from "./categorizerService.js";
import { trackSpendingEvent } from "./ariaService.js";

const db = () => getAdminClient();

// ── Sync de una cuenta ────────────────────────────────────────────────────────

// Lock para evitar syncs paralelos de la misma cuenta
const _syncingAccounts = new Set();

export async function syncBankAccount(bankAccountId, userId) {
  if (_syncingAccounts.has(bankAccountId)) {
    console.log(`[sync] ya activo para ${bankAccountId}, ignorando`);
    return { skipped: true };
  }
  _syncingAccounts.add(bankAccountId);
  const startedAt = Date.now();
  console.log(`[sync] iniciando account=${bankAccountId}`);

  // 1. Cargar cuenta — acepta status "active" o "error" (no "disconnected")
  const { data: account, error: accErr } = await db()
    .from("bank_accounts")
    .select("*")
    .eq("id",      bankAccountId)
    .eq("user_id", userId)
    .neq("status", "disconnected")
    .single();

  if (accErr || !account) {
    throw new Error(`[sync] cuenta no encontrada: ${bankAccountId}`);
  }

  // 2. Reset status al iniciar (limpia errores anteriores)
  await db()
    .from("bank_accounts")
    .update({ status: "active", last_sync_error: null, updated_at: new Date().toISOString() })
    .eq("id", bankAccountId);

  try {
    // 3. Desencriptar credenciales en memoria (nunca se logean)
    const rut      = decrypt(account.encrypted_rut);
    const password = decrypt(account.encrypted_pass);

    // 4. onProgress — reporta cada paso del scraper al log
    //    Para bchile: detecta la pantalla de 2FA y avisa al frontend
    //    vía last_sync_error + status="waiting_2fa" (estado temporal).
    //    Al completar el sync con éxito vuelve a "active" y limpia el error.
    const onProgress = (step) => {
      console.log(`[sync][${account.bank_id}] ${step}`);

      if (/2FA|aprobaci[oó]n|esperando/i.test(step)) {
        // Escribir estado 2FA para que el frontend lo vea via polling.
        // status != "error" → la UI no lo pinta como fallo; el banner se
        // dispara por el regex en last_sync_error.
        db().from("bank_accounts")
          .update({
            status:          "waiting_2fa",
            last_sync_error: "⏳ Esperando aprobación en tu app Banco de Chile...",
          })
          .eq("id", bankAccountId)
          .then(() => {}).catch(() => {});
      }
    };

    // 5. Obtener proveedor y ejecutar scrape
    const provider = await getProviderForBank(account.bank_id);
    const { balance, movements } = await provider.fetchData({ rut, password, onProgress });

    // 6. Categorizar con sistema de 3 capas (reglas → cache → IA)
    const adapted = await categorizeMovements(movements, account.bank_id);

    // 7. Deduplicar contra transacciones existentes
    const { data: existing } = await db()
      .from("transactions")
      .select("external_id")
      .eq("bank_account_id", bankAccountId)
      .not("external_id", "is", null);

    const existingIds  = new Set((existing || []).map((r) => r.external_id));
    const newMovements = adapted.filter((m) => !existingIds.has(m.externalId));

    console.log(`[sync] ${account.bank_id}: ${adapted.length} total, ${newMovements.length} nuevos`);

    // 8. Insertar transacciones nuevas (sin rawDescription — privacidad)
    if (newMovements.length > 0) {
      const rows = newMovements.map((m) => ({
        user_id:          userId,
        bank_account_id:  bankAccountId,
        amount:           m.amount,
        category:         m.category,
        description:      m.description,  // etiqueta limpia, no texto bancario
        date:             m.date,
        external_id:      m.externalId,
        movement_source:  m.movementSource,
      }));

      const { error: insertErr } = await db().from("transactions").insert(rows);
      if (insertErr) throw insertErr;
    }

    // 9. Actualizar estado de la cuenta
    await db()
      .from("bank_accounts")
      .update({
        last_sync_at:    new Date().toISOString(),
        last_sync_error: null,
        last_balance:    balance,
        status:          "active",
        sync_count:      (account.sync_count ?? 0) + 1,
        updated_at:      new Date().toISOString(),
      })
      .eq("id", bankAccountId);

    // 10. ARIA en background
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
    const msg = sanitizeError(error.message);
    console.error(`[sync] error en ${account.bank_id}:`, msg);

    await db()
      .from("bank_accounts")
      .update({ status: "error", last_sync_error: msg, updated_at: new Date().toISOString() })
      .eq("id", bankAccountId);

    throw new Error(msg);
  } finally {
    _syncingAccounts.delete(bankAccountId);
  }
}

// ── Sync de todas las cuentas del usuario ─────────────────────────────────────

export async function syncAllUserAccounts(userId) {
  // Sync todo lo que no esté desconectado. Incluye "error" y "waiting_2fa"
  // para permitir reintentos después de una falla transitoria o un 2FA
  // que el usuario no alcanzó a aprobar.
  const { data: accounts } = await db()
    .from("bank_accounts")
    .select("id, bank_id, bank_name")
    .eq("user_id", userId)
    .neq("status", "disconnected");

  if (!accounts?.length) return { synced: 0, results: [] };

  const results = await Promise.allSettled(
    accounts.map((acc) => syncBankAccount(acc.id, userId))
  );

  return {
    synced:  results.filter((r) => r.status === "fulfilled").length,
    errors:  results.filter((r) => r.status === "rejected").length,
    results: results.map((r, i) => ({
      bankId:  accounts[i].bank_id,
      success: r.status === "fulfilled",
      error:   r.status === "rejected" ? r.reason?.message : null,
    })),
  };
}

// ── Balances por banco ────────────────────────────────────────────────────────

export async function getBankBalances(userId) {
  // Importante: NO incluir account_type ni account_last4 en el SELECT.
  // Esas columnas vienen de una migración extendida (Bank_SQLSchema.txt) que
  // puede no estar aplicada en el schema del usuario. Si Supabase encuentra
  // una columna que no existe, el query falla en silencio, `data` viene como
  // null, y el endpoint devuelve {accounts:[], totalBalance:0} aunque la DB
  // tenga registros con balance. Síntoma: "hice el sync, se guardó el
  // balance, y la UI muestra cero cuentas conectadas".
  // Los campos extendidos se reemplazan por defaults por-banco y se
  // re-intentan en una segunda pasada opcional (no-bloqueante).
  const { data: accounts, error } = await db()
    .from("bank_accounts")
    .select("id, bank_id, bank_name, bank_icon, last_balance, last_sync_at, last_sync_error, status, sync_count")
    .eq("user_id", userId)
    .neq("status", "disconnected")
    .order("created_at", { ascending: true });

  if (error) {
    console.error("[sync] getBankBalances query error:", error.message);
    return { accounts: [], totalBalance: 0 };
  }
  if (!accounts?.length) return { accounts: [], totalBalance: 0 };

  const now          = Date.now();
  const totalBalance = accounts.reduce((sum, a) => sum + (a.last_balance || 0), 0);

  // Tipo de cuenta por defecto según banco — se usa siempre, porque la
  // columna account_type es parte de la migración extendida que puede no
  // estar presente. Cuando se agregue, se puede hacer un SELECT aparte
  // opcional con try/catch y merge sobre estos defaults.
  const DEFAULT_ACCOUNT_TYPE = {
    bancoestado: "CuentaRUT",
    bchile:      "Cta. Corriente",
    santander:   "Cta. Corriente",
    bci:         "Cta. Vista",
    falabella:   "CMR Cuenta",
    itau:        "Cta. Corriente",
    scotiabank:  "Cta. Corriente",
  };

  return {
    accounts: accounts.map((a) => {
      const lastSync   = a.last_sync_at ? new Date(a.last_sync_at).getTime() : null;
      const minutesAgo = lastSync ? Math.max(0, Math.floor((now - lastSync) / 60000)) : null;

      return {
        id:            a.id,
        bankId:        a.bank_id,
        bankName:      a.bank_name,
        bankIcon:      a.bank_icon,
        balance:       a.last_balance    || 0,
        lastSyncAt:    a.last_sync_at,
        lastSyncError: a.last_sync_error,
        status:        a.status,
        syncCount:     a.sync_count      || 0,
        // minutesAgo calculado aquí — el frontend no tiene que hacer aritmética de fechas
        minutesAgo,
        // accountType: default por banco (columna account_type omitida en SELECT
        // porque puede no existir en el schema del usuario)
        accountType:   DEFAULT_ACCOUNT_TYPE[a.bank_id] || "Cuenta",
        // last4: null hasta que exista la columna en el schema y el scraper lo popule
        last4:         null,
      };
    }),
    totalBalance,
  };
}

// ── Helpers privados ──────────────────────────────────────────────────────────

function sanitizeError(msg) {
  if (!msg) return "Error de sincronización";
  // No exponer credenciales ni stack traces en errores
  if (/password|rut|clave|credential/i.test(msg)) return "Error de autenticación bancaria";
  if (/ETIMEDOUT|ECONNREFUSED|timeout.*connect/i.test(msg)) return "El banco no respondió. Intenta más tarde.";
  if (msg.startsWith("2FA_TIMEOUT:"))  return msg.replace("2FA_TIMEOUT: ", "");
  if (msg.startsWith("AUTH_FAILED:"))  return msg.replace("AUTH_FAILED: ", "");
  if (msg.length > 200) return msg.substring(0, 200);
  return msg;
}

async function fireAriaSignals(userId, account, newMovements) {
  if (!newMovements.length) return;
  const { data: profile } = await db()
    .from("profiles")
    .select("age_range, region, income_range")
    .eq("id", userId)
    .single();
  if (!profile) return;
  for (const m of newMovements) {
    if (m.amount >= 0) continue;
    await trackSpendingEvent(
      { age_range: profile.age_range, region: profile.region, income_range: profile.income_range },
      { amount: Math.abs(m.amount), category: m.category, date: m.date }
    ).catch(() => {});
  }
}