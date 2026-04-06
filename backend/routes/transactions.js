// routes/transactions.js
import express from "express";
import { getTransactions, addTransaction, deleteTransaction, getSummary } from "../services/financeService.js";

const router = express.Router();

router.get("/", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    res.json({ transactions: await getTransactions(uid) });
  } catch (e) {
    res.status(500).json({ error: "Error al cargar transacciones" });
  }
});

router.post("/", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    const { amount, category, desc, date } = req.body;
    if (!amount || !category || !desc) return res.status(400).json({ error: "Faltan datos: amount, category, desc" });
    const transaction = await addTransaction(uid, { amount: parseInt(amount), category, desc, date });
    const summary     = await getSummary(uid);
    res.json({ transaction, summary });
  } catch (error) {
    console.error("[transactions] Error:", error.message);
    res.status(500).json({ error: "Error al guardar la transacción" });
  }
});

router.delete("/:id", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    const deleted = await deleteTransaction(uid, req.params.id);
    if (!deleted) return res.status(404).json({ error: "Transacción no encontrada" });
    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ error: "Error al eliminar" });
  }
});

export default router;
