// routes/challenges.js
import express from "express";
import { getUserChallengesState, activateChallenge, completeChallenge } from "../services/financeService.js";
import { askMrMoney } from "../services/aiService.js";

const router = express.Router();

router.get("/", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    res.json(await getUserChallengesState(uid));
  } catch (e) {
    res.status(500).json({ error: "Error al cargar desafíos" });
  }
});

router.post("/:id/activate", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    const result = await activateChallenge(uid, req.params.id);
    if (result.error) return res.status(400).json({ error: result.error });
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: "Error al activar el desafío" });
  }
});

router.post("/:id/complete", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    const result = await completeChallenge(uid, req.params.id);
    if (result.error) return res.status(400).json({ error: result.error });

    let reply = `🏆 +${result.pointsEarned} pts. Completaste "${result.challenge.label}".`;
    try {
      reply = await askMrMoney(
        `El usuario completó el desafío "${result.challenge.label}" y ganó ${result.pointsEarned} pts. Total: ${result.totalPoints} pts. Felicítalo brevemente.`,
        []
      );
    } catch (e) { console.error("[challenges] AI error:", e.message); }

    res.json({ ...result, reply });
  } catch (e) {
    res.status(500).json({ error: "Error al completar el desafío" });
  }
});

export default router;
