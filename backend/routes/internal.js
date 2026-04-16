// ─────────────────────────────────────────────────────────────────────────────
// routes/internal.js
//
// Endpoints internos protegidos por secret compartido (no por JWT de usuario).
// Diseñados para ser invocados por servicios externos como cron-job.org,
// EasyCron, o GitHub Actions scheduled workflows.
//
// Auth: header x-cron-secret debe coincidir con env CRON_SECRET.
// Si CRON_SECRET no está configurada, todos los endpoints devuelven 503 —
// fail-safe: no quedan abiertos por accidente.
//
// Endpoints:
//   POST /api/internal/scheduled-sync  → corre runScheduledSync()
//   POST /api/internal/process-queue   → drena la cola de categorización
//   GET  /api/internal/queue-depth     → cuántas transacciones pendientes hay
// ─────────────────────────────────────────────────────────────────────────────

import express from "express";
import { runScheduledSync }            from "../services/schedulerService.js";
import { processQueue, getQueueDepth } from "../services/categorizationQueueService.js";

const router = express.Router();

// ── Middleware de autorización por secret ────────────────────────────────────
function requireCronSecret(req, res, next) {
  const expected = process.env.CRON_SECRET;
  if (!expected) {
    // Sin secret configurado, todos los endpoints internal están cerrados.
    return res.status(503).json({ error: "Internal endpoints disabled (CRON_SECRET not set)" });
  }
  const provided = req.headers["x-cron-secret"];
  if (provided !== expected) {
    return res.status(401).json({ error: "Invalid cron secret" });
  }
  next();
}

router.use(requireCronSecret);

// ── POST /api/internal/scheduled-sync ────────────────────────────────────────
router.post("/scheduled-sync", async (req, res) => {
  try {
    const result = await runScheduledSync();
    res.json(result);
  } catch (e) {
    console.error("[internal] scheduled-sync:", e.message);
    res.status(500).json({ error: e.message });
  }
});

// ── POST /api/internal/process-queue ─────────────────────────────────────────
router.post("/process-queue", async (req, res) => {
  try {
    const result = await processQueue();
    res.json(result);
  } catch (e) {
    console.error("[internal] process-queue:", e.message);
    res.status(500).json({ error: e.message });
  }
});

// ── GET /api/internal/queue-depth ────────────────────────────────────────────
router.get("/queue-depth", async (req, res) => {
  try {
    const depth = await getQueueDepth();
    res.json({ depth });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

export default router;
