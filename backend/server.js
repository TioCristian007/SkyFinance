// ─────────────────────────────────────────────────────────────────────────────
// server.js — punto de entrada del backend Sky
// ─────────────────────────────────────────────────────────────────────────────

import express from "express";
import cors    from "cors";
import dotenv  from "dotenv";

import chatRoute         from "./routes/chat.js";
import transactionsRoute from "./routes/transactions.js";
import summaryRoute      from "./routes/summary.js";
import challengesRoute   from "./routes/challenges.js";
import simulateRoute     from "./routes/simulate.js";
import goalsRoute        from "./routes/goals.js";
import bankingRoute      from "./routes/banking.js";         // ← nuevo
import { extractUserId } from "./middleware/auth.js";
import { verifyEncryptionReady } from "./services/encryptionService.js"; // ← nuevo

dotenv.config();

// Verificar encriptación al arrancar
// Si BANK_ENCRYPTION_KEY no está definida, el servidor avisa pero no crashea
// (las rutas de banking simplemente fallarán hasta que se configure)
verifyEncryptionReady();

const app  = express();
const PORT = process.env.PORT || 3001;

app.use(cors());
app.use(express.json());
app.use(extractUserId);

app.use("/api/chat",         chatRoute);
app.use("/api/transactions", transactionsRoute);
app.use("/api/summary",      summaryRoute);
app.use("/api/challenges",   challengesRoute);
app.use("/api/simulate",     simulateRoute);
app.use("/api/goals",        goalsRoute);
app.use("/api/banking",      bankingRoute);                  // ← nuevo

app.get("/api/health", (_, res) => res.json({ status: "ok", app: "sky-backend" }));

app.use((err, req, res, _next) => {
  console.error("[error]", err.message);
  res.status(500).json({ error: "Error interno del servidor" });
});

app.listen(PORT, () => {
  console.log(`✅ Sky backend corriendo en http://localhost:${PORT}`);
  console.log(`   Rutas: /api/chat | /api/banking | /api/transactions | /api/summary`);
});