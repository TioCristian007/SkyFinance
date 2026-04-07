// routes/chat.js
import express from "express";
import { askMrMoney } from "../services/aiService.js";
import { trackBehavioralSignal } from "../services/ariaService.js";
import { getProfile } from "../services/dbService.js";

const router = express.Router();

router.post("/", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });

    const { message, history = [] } = req.body;
    if (!message || typeof message !== "string" || !message.trim()) {
      return res.status(400).json({ error: "Mensaje inválido" });
    }

    // Mr. Money ahora devuelve { reply, proposals? }
    const result = await askMrMoney(message.trim(), history, uid);
    res.json(result);

    // ARIA en background
    getProfile(uid).then((profile) => {
      if (profile) {
        trackBehavioralSignal(profile, message.trim(), result.reply).catch(() => {});
      }
    }).catch(() => {});

  } catch (error) {
    console.error("[chat] Error:", error);
    res.status(500).json({ error: "Error al conectar con Mr Money. Intenta de nuevo." });
  }
});

export default router;