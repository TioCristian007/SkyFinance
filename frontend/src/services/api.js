// ─────────────────────────────────────────────────────────────────────────────
// services/api.js — único canal frontend → backend
// Auth: Authorization: Bearer <access_token> en TODAS las llamadas
//
// BASE_URL:
//   - Dev local: usa "/api" y el proxy de Vite (vite.config.js) redirige
//     al backend Python en http://127.0.0.1:8000. Esto evita CORS en dev.
//   - Producción: usa VITE_API_URL (inyectada en build-time por Railway).
//     Debe apuntar a la URL pública del backend, incluyendo /api al final.
//     Ej: https://api.skyfinanzas.com/api
//
// Si olvidas setear VITE_API_URL en Railway al buildear el frontend,
// el código cae a "/api" (relativo). Eso fallará visiblemente en prod
// (404 del dominio del frontend), que es mucho mejor que golpear el
// localhost de la máquina del usuario final.
// ─────────────────────────────────────────────────────────────────────────────

function resolveBaseUrl() {
  const raw = import.meta.env.VITE_API_URL;
  if (!raw || !raw.trim()) {
    // Sin env var → ruta relativa. En dev el proxy la resuelve.
    return "/api";
  }
  // Normaliza trailing slashes para evitar "//summary".
  return raw.trim().replace(/\/+$/, "");
}

const BASE_URL = resolveBaseUrl();
const DEBUG    = typeof window !== "undefined" ? (window.__SKY_DEBUG ?? true) : true;

if (DEBUG) console.log("[api] BASE_URL:", BASE_URL);

let _accessToken = null;

export function setAccessToken(token) {
  if (token !== _accessToken) {
    if (DEBUG) console.log("[api] setAccessToken: token actualizado");
    _accessToken = token;
  }
}

async function request(path, options = {}) {
  if (!_accessToken) {
    console.warn("[api] request sin accessToken → el backend va a devolver 401", path);
  }

  const headers = {
    "Content-Type": "application/json",
    ...(_accessToken ? { "Authorization": `Bearer ${_accessToken}` } : {}),
    ...(options.headers || {}),
  };

  if (DEBUG) console.log(`[api] → ${options.method || "GET"} ${path}`);

  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  } catch (netErr) {
    console.error(`[api] network fail ${path}:`, netErr.message);
    throw new Error("No hay conexión con el backend. ¿Está corriendo?");
  }

  if (DEBUG) console.log(`[api] ← ${res.status} ${path}`);

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "Error de red" }));
    throw new Error(err.error ?? `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Summary ───────────────────────────────────────────────────────────────────
export async function getSummary() {
  return request("/summary");
}

// ── Transactions ──────────────────────────────────────────────────────────────
export async function getTransactions() {
  return request("/transactions");
}

export async function addTransaction(tx) {
  return request("/transactions", { method: "POST", body: JSON.stringify(tx) });
}

export async function deleteTransaction(id) {
  return request(`/transactions/${id}`, { method: "DELETE" });
}

// ── Chat ──────────────────────────────────────────────────────────────────────
export async function sendChat(message, history = []) {
  return request("/chat", { method: "POST", body: JSON.stringify({ message, history }) });
}

// ── Challenges ────────────────────────────────────────────────────────────────
export async function getChallenges() {
  return request("/challenges");
}

export async function activateChallenge(id) {
  return request(`/challenges/${id}/activate`, { method: "POST" });
}

export async function completeChallenge(id) {
  return request(`/challenges/${id}/complete`, { method: "POST" });
}

// ── Simulate ──────────────────────────────────────────────────────────────────
export async function runSimulation(simulationId, customAmount = null) {
  return request("/simulate", {
    method: "POST",
    body:   JSON.stringify({ simulationId, customAmount }),
  });
}

// ── Goals ─────────────────────────────────────────────────────────────────────
export async function getGoals() {
  return request("/goals");
}

export async function addGoal(goal) {
  return request("/goals", { method: "POST", body: JSON.stringify(goal) });
}

export async function updateGoalSaved(id, savedAmount) {
  return request(`/goals/${id}`, { method: "PATCH", body: JSON.stringify({ savedAmount }) });
}

export async function deleteGoal(id) {
  return request(`/goals/${id}`, { method: "DELETE" });
}

// ── Profile ───────────────────────────────────────────────────────────────────
export async function patchProfile(data) {
  return request("/profile", { method: "PATCH", body: JSON.stringify(data) });
}

// ── Banking ───────────────────────────────────────────────────────────────────

export async function getSupportedBanks() {
  return request("/banking/banks");
}

export async function getBankAccounts() {
  return request("/banking/accounts");
}

export async function connectBank({ bankId, rut, password }) {
  return request("/banking/accounts", {
    method: "POST",
    body:   JSON.stringify({ bank_id: bankId, rut, password }),
  });
}

export async function syncBankAccount(accountId) {
  return request(`/banking/sync/${accountId}`, { method: "POST" });
}

export async function syncAllBanks() {
  return request("/banking/sync-all", { method: "POST" });
}

export async function disconnectBank(accountId) {
  return request(`/banking/accounts/${accountId}`, { method: "DELETE" });
}
