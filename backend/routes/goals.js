// routes/goals.js
import express from "express";
import { getGoals, addGoal, updateGoal, deleteGoal } from "../services/financeService.js";

const router = express.Router();

router.get("/", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    res.json({ goals: await getGoals(uid) });
  } catch (e) {
    res.status(500).json({ error: "Error al cargar metas" });
  }
});

router.post("/", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    const result = await addGoal(uid, req.body);
    if (result.error) return res.status(400).json({ error: result.error });
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: "Error al crear la meta" });
  }
});

router.patch("/:id", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    const result = await updateGoal(uid, req.params.id, req.body);
    if (result.error) return res.status(404).json({ error: result.error });
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: "Error al actualizar la meta" });
  }
});

router.delete("/:id", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    const deleted = await deleteGoal(uid, req.params.id);
    if (!deleted) return res.status(404).json({ error: "Meta no encontrada" });
    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ error: "Error al eliminar la meta" });
  }
});

export default router;
