// ─────────────────────────────────────────────────────────────────────────────
// services/bankSyncService.js
//
// Orquestador de sincronización bancaria.
//
// CAMBIOS ENTREGA 2:
//   · Sync incremental: cuenta cuántas transacciones existentes ya hay para
//     esta cuenta. Si el scraper trae los movimientos más recientes y todos
//     ya están conocidos, evitamos categorizar de nuevo. Reduce calls a IA.
//   · Categorización async: las transacciones se insertan con
//     categorization_status='pending' y categoría provisional 'other'.
//     processQueue() las resuelve en background. El usuario ve los
//     movimientos al instante; la categoría real aparece segundos después.
//   · Tracking de errores consecutivos: bank_accounts.consecutive_errors
//     sube en cada error y se resetea a 0 en éxito. El scheduler lo usa
//     para backoff exponencial.
//   · last_scheduled_at: actualizado al inicio de cada sync, exitoso o no,
//     para que el scheduler no insista demasiado pronto.
//
// FLUJO:
//   1. Cargar bank_account (credentials encriptadas)
//   2. Resetear status → "syncing"
//   3. Desencriptar RUT + pass en memoria
//   4. Llamar proveedor con onProgress (reporta estado 2FA en tiempo real)
//   5. Adaptar movimientos al modelo canónico
//   6. Deduplicar contra transacciones existentes
//   7. Insertar nuevas con categorization_status='pending'
//   8. Actualizar last_balance, last_sync_at, status → "active"
//   9. Disparar processQueue() en background — categoriza los pendientes
//  10. ARIA en background (buckets anónimos, sin UUID ni montos exactos)
//
// 2FA (bchile):
//   - onProgress detecta el mensaje de espera 2FA
//   - Escribe "⏳ Esperando aprobación..." en last_sync_error
//   - Frontend lo lee via polling GET /api/banking/accounts
//   - Cuando usuario aprueba en app → scraper continúa → last_sync_error se limpia
// ─────────────────────────────────────────────────────────────────────────────

import { getAdminClient }      from "./supabaseClient.js";
import { decrypt }             from "./encryptionService.js";
import { getProviderForBank }  from "./bankingAdapter.js";
import { trackSpendingEvent }  from "./ariaService.js";
import { processQueue }        from "./categorizationQueueService.js";

const db = () => getAdminClient();

// Lock en memoria para evitar syncs paralelos de la MISMA cuenta.
// No previene paralelismo entre cuentas distintas (eso es deseable).
const _syncingAccounts = new Set();

// ── Sync de una cuenta ────────────────────────────────────────────────────────

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
    _syncingAccounts.delete(bankAccountId);
    throw new Error(`[sync] cuenta no encontrada: ${bankAccountId}`);
  }

  // 2. Reset status al iniciar (limpia errores anteriores) y marca scheduler
  await db()
    .from("bank_accounts")
    .update({
      status:              "active",
      last_sync_error:     null,
      last_scheduled_at:   new Date().toISOString(),
      updated_at:          new Date().toISOString(),
    })
    .eq("id", bankAccountId);

  try {
    // 3. Desencriptar credenciales en memoria (nunca se logean)
    const rut      = decrypt(account.encrypted_rut);
    const password = decrypt(account.encrypted_pass);

    // 4. onProgress — reporta cada paso del scraper al log
    //    Para bchile: detecta la pantalla de 2FA y avisa al frontend
    //    vía last_sync_error + status="waiting_2fa" (estado temporal).
    const onProgress = (step) => {
      console.log(`[sync][${account.bank_id}] ${step}`);

      if (/2FA|aprobaci[oó]n|esperando/i.test(step)) {
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

    // 6. Deduplicar ANTES de cualquier procesamiento pesado.
    //    Sync incremental: si todos los movimientos ya existen, salimos
    //    sin tocar nada más. Reduce calls a IA y escrituras innecesarias.
    const { data: existing } = await db()
      .from("transactions")
      .select("external_id")
      .eq("bank_account_id", bankAccountId)
      .not("external_id", "is", null);

    const existingIds = new Set((existing || []).map((r) => r.external_id));

    // El proveedor devuelve movimientos sin categorizar (raw del scraper).
    // Construimos external_id provisional para cada uno y filtramos.
    const adapted = movements.map((m) => buildPendingMovement(m, account.bank_id));
    const newMovements = adapted.filter((m) => !existingIds.has(m.externalId));

    console.log(`[sync] ${account.bank_id}: ${adapted.length} total, ${newMovements.length} nuevos`);

    // 7. Insertar transacciones nuevas con categorization_status='pending'.
    //    El usuario ve sus movimientos al instante con etiqueta provisional.
    //    processQueue() los categoriza en background.
    if (newMovements.length > 0) {
      const rows = newMovements.map((m) => ({
        user_id:                  userId,
        bank_account_id:          bankAccountId,
        amount:                   m.amount,
        category:                 "other",                 // provisional
        description:              "Procesando...",         // provisional
        raw_description:          m.rawDescription,
        date:                     m.date,
        external_id:              m.externalId,
        movement_source:          m.movementSource,
        categorization_status:    "pending",
      }));

      const { error: insertErr } = await db()
        .from("transactions")
        .upsert(rows, {
          onConflict: "user_id,bank_account_id,date,amount,raw_description"
        });

      if (insertErr) {
        console.error("Insert error:", insertErr);
        throw insertErr;
      }
    }

    // 8. Actualizar estado de la cuenta + reset error counter
    await db()
      .from("bank_accounts")
      .update({
        last_sync_at:        new Date().toISOString(),
        last_sync_error:     null,
        last_balance:        balance,
        status:              "active",
        sync_count:          (account.sync_count ?? 0) + 1,
        consecutive_errors:  0,                            // reset on success
        updated_at:          new Date().toISOString(),
      })
      .eq("id", bankAccountId);

    // 9. Disparar categorización en background.
    //    fire-and-forget — no bloqueamos la respuesta al usuario.
    if (newMovements.length > 0) {
      processQueue().catch((e) => console.error("[sync] catQueue error:", e.message));
    }

    // 10. ARIA en background — pasamos userId para que el guard de
    //     consentimiento funcione (P0-3 del sweep).
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

    // Incrementar contador de errores consecutivos para backoff del scheduler
    await db()
      .from("bank_accounts")
      .update({
        status:              "error",
        last_sync_error:     msg,
        consecutive_errors:  (account.consecutive_errors ?? 0) + 1,
        updated_at:          new Date().toISOString(),
      })
      .eq("id", bankAccountId);

    throw new Error(msg);
  } finally {
    _syncingAccounts.delete(bankAccountId);
  }
}

// ── Sync de todas las cuentas del usuario ─────────────────────────────────────

export async function syncAllUserAccounts(userId) {
  const { data: accounts } = await db()
    .from("bank_accounts")
    .select("id, bank_id, bank_name")
    .eq("user_id", userId)
    .neq("status", "disconnected");

  if (!accounts?.length) return { synced: 0, results: [] };

  // Secuencial, no paralelo: cada scraper abre una instancia de Chromium
  // que consume ~200MB. Con 6+ bancos en paralelo en Railway la memoria
  // explota. Sequential es más lento pero estable.
  const results = [];
  for (const acc of accounts) {
    try {
      const r = await syncBankAccount(acc.id, userId);
      results.push({ bankId: acc.bank_id, success: true, ...r });
    } catch (e) {
      results.push({ bankId: acc.bank_id, success: false, error: e.message });
    }
  }

  return {
    synced: results.filter((r) => r.success).length,
    errors: results.filter((r) => !r.success).length,
    results,
  };
}

// ── Balances por banco ────────────────────────────────────────────────────────

export async function getBankBalances(userId) {
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
        minutesAgo,
        accountType:   DEFAULT_ACCOUNT_TYPE[a.bank_id] || "Cuenta",
        last4:         null,
      };
    }),
    totalBalance,
  };
}

// ── Helpers privados ──────────────────────────────────────────────────────────

// Construye el shape mínimo necesario para insertar una transacción
// pendiente. NO categoriza — eso es trabajo de processQueue() después.
// external_id se construye igual que en el categorizer original para
// que la deduplicación funcione consistentemente.
function buildPendingMovement(m, bankId) {
  const amount    = parseInt(m.amount ?? 0);
  const rawDesc   = (m.description ?? "").trim();
  const date      = normalizeDate(m.date);
  const source    = m.source ?? "account";
  const externalId = m.id ?? buildExternalId(bankId, date, amount, rawDesc, source);

  return {
    amount,
    rawDescription: rawDesc,
    date,
    movementSource: source,
    externalId,
  };
}

function normalizeDate(raw) {
  if (!raw) return new Date().toISOString().split("T")[0];
  if (/^\d{2}-\d{2}-\d{4}$/.test(raw)) {
    const [d, mo, y] = raw.split("-");
    return `${y}-${mo}-${d}`;
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.substring(0, 10);
  return new Date().toISOString().split("T")[0];
}

function buildExternalId(bankId, date, amount, desc, source) {
  const raw = `${bankId}:${source}:${date}:${amount}:${desc.substring(0, 30)}`;
  let h = 0;
  for (let i = 0; i < raw.length; i++) { h = ((h << 5) - h) + raw.charCodeAt(i); h |= 0; }
  return `${bankId}_${Math.abs(h).toString(36)}`;
}

function sanitizeError(msg) {
  if (!msg) return "Error de sincronización";
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
    // Pasamos userId — el guard de consentimiento de ARIA lo necesita.
    // Sin userId el guard se saltaba (P0-3 del sweep).
    await trackSpendingEvent(
      { age_range: profile.age_range, region: profile.region, income_range: profile.income_range },
      { amount: Math.abs(m.amount), category: "other", date: m.date }, // categoría real vendrá en el futuro
      userId
    ).catch(() => {});
  }
}
