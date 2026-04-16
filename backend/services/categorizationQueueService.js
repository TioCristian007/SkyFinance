// ─────────────────────────────────────────────────────────────────────────────
// services/categorizationQueueService.js
//
// Categorización asíncrona de transacciones marcadas como "pending".
//
// Por qué existe:
//   El sync bancario insertaba con categoría ya resuelta. Si Claude tardaba
//   mucho o fallaba, el usuario veía el spinner del sync por más tiempo.
//   Ahora el sync inserta TODO con categoría provisional y marca
//   categorization_status='pending'. Este servicio procesa la cola en
//   background — el usuario ve sus movimientos al instante con etiqueta
//   genérica, y la categoría real aparece segundos después.
//
// Cuándo se ejecuta:
//   1. Después de cada sync (disparado por bankSyncService).
//   2. Por el cron job cada N minutos como red de seguridad.
//
// Garantías:
//   · Idempotente: si dos invocaciones procesan el mismo lote, no duplica trabajo.
//   · Lock por tabla en lugar de lock por fila — más simple, sirve para early.
//   · Fallback a "other" + categorization_status='failed' si IA falla; queda
//     visible para el usuario y la entrega 1 (recategorización) lo resuelve.
// ─────────────────────────────────────────────────────────────────────────────

import { getAdminClient }                  from "./supabaseClient.js";
import { categorizeMovements, categoryLabel } from "./categorizerService.js";

const db = () => getAdminClient();

// Lock global en memoria — evita procesamiento paralelo de la cola.
// Con un solo proceso de Node esto basta. Cuando escales a múltiples
// workers se reemplaza por advisory lock de Postgres (pg_try_advisory_lock).
let _processing = false;

// Tamaño del lote — Claude Haiku categoriza hasta 20 keys por llamada.
// 50 transacciones cubren típicamente ~30 merchants únicos.
const BATCH_SIZE = 50;

// ── processQueue ─────────────────────────────────────────────────────────────
// Procesa hasta BATCH_SIZE transacciones pendientes.
// Devuelve { processed, failed, skipped }.
// Si ya hay otra invocación en curso, devuelve { skipped: true } sin esperar.

export async function processQueue() {
  if (_processing) {
    return { skipped: true, reason: "already_running" };
  }
  _processing = true;
  const startedAt = Date.now();

  try {
    // 1. Tomar lote pendiente, FIFO.
    //    Usamos el índice parcial idx_transactions_pending — query rápida
    //    incluso con millones de filas en transactions.
    const { data: pending, error: pendErr } = await db()
      .from("transactions")
      .select("id, raw_description, amount, bank_account_id, user_id")
      .eq("categorization_status", "pending")
      .order("created_at", { ascending: true })
      .limit(BATCH_SIZE);

    if (pendErr) {
      console.error("[catQueue] fetch error:", pendErr.message);
      return { processed: 0, failed: 0, error: pendErr.message };
    }

    if (!pending || pending.length === 0) {
      return { processed: 0, failed: 0, skipped: false };
    }

    console.log(`[catQueue] procesando ${pending.length} pendientes`);

    // 2. Agrupar por bankId para que el categorizer reciba contexto homogéneo.
    //    bankId se infiere desde bank_account_id. Para el categorizer es
    //    suficiente saber que vienen de "algún banco" (no usa bankId hoy).
    const movementsForCategorizer = pending.map((tx) => ({
      id:          tx.id,                  // se preserva pero no se usa como external
      description: tx.raw_description || "",
      amount:      tx.amount,
      date:        new Date().toISOString().split("T")[0], // no afecta categorización
      source:      "account",
    }));

    // 3. Categorizar. categorizeMovements ya maneja sus 3 capas internamente.
    //    Aquí no nos importa external_id — solo necesitamos category por idx.
    let categorized;
    try {
      categorized = await categorizeMovements(movementsForCategorizer, "queue");
    } catch (e) {
      console.error("[catQueue] categorizer threw:", e.message);
      // Marcar todo el lote como failed para no quedar en loop infinito.
      await markBatchFailed(pending.map((p) => p.id));
      return { processed: 0, failed: pending.length, error: e.message };
    }

    // 4. Aplicar resultados — uno por uno porque cada UPDATE depende del id.
    //    Promise.allSettled para no abortar si una update falla.
    const updates = pending.map((tx, idx) => {
      const cat   = categorized[idx]?.category || "other";
      const label = categoryLabel(cat);
      const status = cat === "other" ? "failed" : "done";

      return db()
        .from("transactions")
        .update({
          category:               cat,
          description:            label,
          categorization_status:  status,
        })
        .eq("id", tx.id);
    });

    const results = await Promise.allSettled(updates);
    const succeeded = results.filter((r) => r.status === "fulfilled").length;
    const errored   = results.filter((r) => r.status === "rejected").length;

    const elapsed = Date.now() - startedAt;
    console.log(`[catQueue] ${succeeded} OK, ${errored} fail en ${elapsed}ms`);

    return {
      processed: succeeded,
      failed:    errored,
      skipped:   false,
      elapsedMs: elapsed,
    };

  } finally {
    _processing = false;
  }
}

// ── markBatchFailed ──────────────────────────────────────────────────────────
// Helper privado: marca un lote como failed cuando el categorizer revienta
// completo (ej: API key inválida, rate limit total). Evita loop infinito de
// reintentos sobre las mismas filas.

async function markBatchFailed(ids) {
  if (!ids?.length) return;
  await db()
    .from("transactions")
    .update({ categorization_status: "failed" })
    .in("id", ids)
    .then(() => {})
    .catch((e) => console.error("[catQueue] markBatchFailed:", e.message));
}

// ── getQueueDepth ────────────────────────────────────────────────────────────
// Métrica simple — cuántas filas hay esperando.
// Útil para health-check y para que el frontend muestre "categorizando..."
// si la cola está alta.

export async function getQueueDepth() {
  const { count, error } = await db()
    .from("transactions")
    .select("*", { count: "exact", head: true })
    .eq("categorization_status", "pending");

  if (error) {
    console.error("[catQueue] depth error:", error.message);
    return null;
  }
  return count ?? 0;
}
