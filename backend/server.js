// ─────────────────────────────────────────────────────────────────────────────
// server.js — punto de entrada del backend Sky
//
// RESPONSABILIDAD: arrancar Express y montar las rutas.
// NO contiene lógica de negocio. NO contiene prompts. NO contiene datos.
// Cada cosa vive en su carpeta correspondiente.
// ─────────────────────────────────────────────────────────────────────────────

import express from "express";
import cors from "cors";
import dotenv from "dotenv";

import chatRoute         from "./routes/chat.js";
import transactionsRoute from "./routes/transactions.js";
import summaryRoute      from "./routes/summary.js";
import challengesRoute   from "./routes/challenges.js";
import simulateRoute     from "./routes/simulate.js";
import goalsRoute        from "./routes/goals.js";
import { extractUserId } from "./middleware/auth.js";

dotenv.config();

const app  = express();
const PORT = process.env.PORT || 3001;

// ── Middleware ────────────────────────────────────────────────────────────────
app.use(cors());
app.use(express.json());
app.use(extractUserId); // lee x-user-id de cada request → disponible en req.userId

// ── Rutas ─────────────────────────────────────────────────────────────────────
// Todas bajo /api/ para que el frontend sepa claramente qué es llamada de red
app.use("/api/chat",         chatRoute);
app.use("/api/transactions", transactionsRoute);
app.use("/api/summary",      summaryRoute);
app.use("/api/challenges",   challengesRoute);
app.use("/api/simulate",     simulateRoute);
app.use("/api/goals",        goalsRoute);

// ── Health check ──────────────────────────────────────────────────────────────
app.get("/api/health", (_, res) => res.json({ status: "ok", app: "sky-backend" }));

// ── Error global ──────────────────────────────────────────────────────────────
app.use((err, req, res, _next) => {
  console.error("[error]", err.message);
  res.status(500).json({ error: "Error interno del servidor" });
});

app.listen(PORT, () => {
  console.log(`✅ Sky backend corriendo en http://localhost:${PORT}`);
  console.log(`   Rutas: /api/chat | /api/transactions | /api/summary | /api/challenges | /api/simulate`);
});
