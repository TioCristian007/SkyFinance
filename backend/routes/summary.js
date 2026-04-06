// routes/summary.js
import express from "express";
import { getSummary, getUserProfile, evaluateBadges } from "../services/financeService.js";

const router = express.Router();

router.get("/", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });

    const [summary, profile, badges] = await Promise.all([
      getSummary(uid),
      getUserProfile(uid),
      evaluateBadges(uid),
    ]);
    res.json({ summary, profile, badges });
  } catch (error) {
    console.error("[summary] Error:", error.message);
    res.status(500).json({ error: "Error al cargar el resumen" });
  }
});

export default router;
