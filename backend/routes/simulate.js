// routes/simulate.js
import express from "express";
import { computeSimulation } from "../services/financeService.js";

const router = express.Router();

router.post("/", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    const { simulationId, customAmount } = req.body;
    if (!simulationId) return res.status(400).json({ error: "simulationId requerido" });
    const result = await computeSimulation(uid, simulationId, customAmount ? parseInt(customAmount) : null);
    if (!result) return res.status(404).json({ error: "Simulación no encontrada" });
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: "Error en la simulación" });
  }
});

export default router;
