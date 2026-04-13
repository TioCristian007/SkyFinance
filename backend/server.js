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
import bankingRoute      from "./routes/banking.js";
import { extractUserId } from "./middleware/auth.js";
import { verifyEncryptionReady } from "./services/encryptionService.js";

dotenv.config();

// Verificar encriptación al arrancar
verifyEncryptionReady();

const app  = express();
const PORT = process.env.PORT || 3001;

// ─── CORS ────────────────────────────────────────────────────────────────────
// En dev: permite localhost:5173 (Vite) automáticamente.
// En prod: lee CORS_ORIGINS (coma-separada) del env, ej:
//   CORS_ORIGINS=https://app.skyfinanzas.com,https://skyfinance.up.railway.app
// Si CORS_ORIGINS no está definida, en prod cae a "reflect origin" con warning
// (útil para debug inicial, endurecer después).

const DEV_ORIGINS = [
  "http://localhost:5173",
  "http://localhost:4173", // vite preview
  "http://127.0.0.1:5173",
];

const envOrigins = (process.env.CORS_ORIGINS || "")
  .split(",")
  .map(s => s.trim())
  .filter(Boolean);

const allowedOrigins = [...DEV_ORIGINS, ...envOrigins];

console.log("[cors] orígenes permitidos:", allowedOrigins.length ? allowedOrigins : "(ninguno configurado, reflejando origin)");

app.use(cors({
  origin(origin, cb) {
    // Sin origin (curl, same-origin, server-to-server) → permitir.
    if (!origin) return cb(null, true);

    if (allowedOrigins.includes(origin)) return cb(null, true);

    // Fallback: si no hay CORS_ORIGINS seteada, reflejar para no bloquear
    // durante setup inicial. En prod estable, definir CORS_ORIGINS y
    // este branch dejará de activarse.
    if (envOrigins.length === 0) {
      console.warn(`[cors] origin no en allowlist, reflejando por fallback: ${origin}`);
      return cb(null, true);
    }

    console.warn(`[cors] origin bloqueado: ${origin}`);
    return cb(new Error(`Origin ${origin} no permitido por CORS`));
  },
  credentials: true,
  methods: ["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
  allowedHeaders: ["Content-Type", "x-user-id", "Authorization"],
}));

app.use(express.json());
app.use(extractUserId);

app.use("/api/chat",         chatRoute);
app.use("/api/transactions", transactionsRoute);
app.use("/api/summary",      summaryRoute);
app.use("/api/challenges",   challengesRoute);
app.use("/api/simulate",     simulateRoute);
app.use("/api/goals",        goalsRoute);
app.use("/api/banking",      bankingRoute);

app.get("/api/health", (_, res) => res.json({ status: "ok", app: "sky-backend" }));

// Ruta raíz para health-check de Railway y verificación rápida en el browser
app.get("/", (_, res) => res.json({
  status: "ok",
  app: "sky-backend",
  routes: ["/api/health", "/api/chat", "/api/banking", "/api/transactions", "/api/summary", "/api/goals", "/api/challenges", "/api/simulate"],
}));

app.use((err, req, res, _next) => {
  console.error("[error]", err.message);
  res.status(500).json({ error: "Error interno del servidor" });
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`✅ Sky backend corriendo en puerto ${PORT}`);
  console.log(`   Rutas: /api/chat | /api/banking | /api/transactions | /api/summary`);
});
