// ─────────────────────────────────────────────────────────────────────────────
// services/schedulerService.js
//
// Lógica del cron job de auto-sync.
//
// Diseño:
//   · El cron se ejecuta cada hora (configurable por env CRON_INTERVAL_HOURS).
//   · En cada tick busca cuentas que toca sincronizar según reglas:
//       - status IN ('active', 'error')                    — no tocar disconnected
//       - profiles.auto_sync_enabled = true                — opt-in del usuario
//       - last_scheduled_at IS NULL OR < (now - intervalo) — rate-limit
//       - backoff exponencial por consecutive_errors        — no insistir en cuentas rotas
//   · Sincroniza secuencialmente — Chromium consume mucha memoria, paralelo es riesgoso.
//
// Backoff exponencial:
//   · 0 errores:  cada 1h    (intervalo normal)
//   · 1 error:    cada 2h
//   · 2 errores:  cada 4h
//   · 3 errores:  cada 8h
//   · 4+ errores: cada 24h   (probablemente el banco bloqueó al usuario)
//
// Cómo se invoca:
//   Esta función se exporta y se llama desde un cron de Railway o desde
//   un endpoint protegido. NO se auto-invoca al cargar el módulo.
//
//   Opción A — Railway cron job (recomendado):
//     Railway permite definir cron jobs nativos en railway.toml.
//     El cron ejecuta `node scripts/runScheduledSync.js`.
//
//   Opción B — Endpoint con secret + servicio externo (cron-job.org, etc):
//     POST /api/internal/scheduled-sync  con header x-cron-secret.
//     Útil si Railway cron no está disponible en tu plan.
//
//   Opción C — setInterval en server.js (NO recomendado en producción):
//     Solo para dev. Si el server reinicia, se pierde el ciclo.
// ─────────────────────────────────────────────────────────────────────────────

import { getAdminClient }   from "./supabaseClient.js";
import { syncBankAccount }  from "./bankSyncService.js";
import { processQueue }     from "./categorizationQueueService.js";

const db = () => getAdminClient();

// Intervalo base entre intentos para una cuenta sin errores.
// Configurable por env. Default: 1 hora.
const BASE_INTERVAL_HOURS = parseFloat(process.env.SCHEDULER_BASE_INTERVAL_HOURS) || 1;

// Multiplicador del backoff por error consecutivo. 2 = duplica cada error.
const BACKOFF_FACTOR = 2;

// Tope del backoff. Más allá de esto no esperamos más; el sistema se rinde.
const MAX_BACKOFF_HOURS = 24;

// Cuántas cuentas procesar por tick. Limita el blast radius si algo va mal.
const MAX_ACCOUNTS_PER_TICK = 20;

// ── runScheduledSync ─────────────────────────────────────────────────────────
// Función principal del cron. Decide qué cuentas tocan, las sincroniza
// secuencialmente, y procesa la cola de categorización al final.

export async function runScheduledSync() {
  const startedAt = Date.now();
  console.log(`[scheduler] tick start`);

  try {
    // 1. Obtener cuentas candidatas con sus profiles para verificar opt-in.
    //    Una sola query con join — más rápido que iterar.
    const { data: candidates, error } = await db()
      .from("bank_accounts")
      .select(`
        id, user_id, bank_id, status, last_scheduled_at, consecutive_errors,
        profiles!inner (auto_sync_enabled)
      `)
      .in("status", ["active", "error"])
      .eq("profiles.auto_sync_enabled", true)
      .limit(MAX_ACCOUNTS_PER_TICK * 3); // sobre-pedimos para filtrar

    if (error) {
      console.error("[scheduler] query error:", error.message);
      return { error: error.message };
    }

    if (!candidates?.length) {
      console.log(`[scheduler] sin candidatos`);
      return { processed: 0 };
    }

    // 2. Filtrar por backoff exponencial.
    const now = Date.now();
    const due = candidates.filter((acc) => {
      const errors          = acc.consecutive_errors ?? 0;
      const intervalHours   = Math.min(
        BASE_INTERVAL_HOURS * Math.pow(BACKOFF_FACTOR, errors),
        MAX_BACKOFF_HOURS
      );
      const intervalMs      = intervalHours * 3600 * 1000;
      const lastScheduledMs = acc.last_scheduled_at
        ? new Date(acc.last_scheduled_at).getTime()
        : 0;
      return (now - lastScheduledMs) >= intervalMs;
    });

    const toProcess = due.slice(0, MAX_ACCOUNTS_PER_TICK);
    console.log(`[scheduler] ${candidates.length} candidatos → ${due.length} due → ${toProcess.length} a procesar`);

    if (!toProcess.length) {
      return { processed: 0, skipped: candidates.length };
    }

    // 3. Sincronizar SECUENCIALMENTE.
    //    Paralelo abriría N instancias de Chromium → OOM en Railway.
    const results = [];
    for (const acc of toProcess) {
      try {
        const r = await syncBankAccount(acc.id, acc.user_id);
        results.push({ accountId: acc.id, bankId: acc.bank_id, success: true, ...r });
      } catch (e) {
        results.push({ accountId: acc.id, bankId: acc.bank_id, success: false, error: e.message });
      }
    }

    // 4. Drenar cola de categorización al final.
    //    Cada sync ya disparó processQueue, pero esta llamada extra cubre
    //    casos donde un lote quedó sin procesar por race conditions.
    try { await processQueue(); } catch (e) { console.error("[scheduler] catQueue:", e.message); }

    const elapsed = Date.now() - startedAt;
    const ok      = results.filter((r) => r.success).length;
    const fail    = results.filter((r) => !r.success).length;
    console.log(`[scheduler] tick done — ${ok} OK, ${fail} fail en ${elapsed}ms`);

    return {
      processed: results.length,
      ok,
      fail,
      elapsedMs: elapsed,
      results,
    };

  } catch (e) {
    console.error("[scheduler] fatal:", e.message);
    return { error: e.message };
  }
}
