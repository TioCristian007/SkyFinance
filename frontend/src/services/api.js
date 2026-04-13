// ─────────────────────────────────────────────────────────────────────────────
// services/api.js — único canal frontend → backend
// userId se pasa en el header x-user-id en TODAS las llamadas
//
// Esta versión incluye console logs de diagnóstico ligeros para poder ver
// en DevTools Console cada request, su userId al momento del disparo, y
// la respuesta/error. Si quieres silenciarlos, setea window.__SKY_DEBUG=false
// desde la consola o elimina los console.log antes de prod.
// ─────────────────────────────────────────────────────────────────────────────

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:3001/api";
const DEBUG    = typeof window !== "undefined" ? (window.__SKY_DEBUG ?? true) : true;

let _userId = null;
export function setUserId(id) {
  // Log solo si cambia — evita spam en cada render de Sky.jsx
  if (id !== _userId) {
    if (DEBUG) console.log("[api] setUserId:", id);
    _userId = id;
  }
}

async function request(path, options = {}) {
  if (!_userId) {
    // Aviso loud — si llegamos aquí algo en el árbol de auth está mal
    console.warn("[api] request sin userId → el backend va a devolver 401", path);
  }

  const headers = {
    "Content-Type": "application/json",
    ..._userId ? { "x-user-id": _userId } : {},
    ...(options.headers || {}),
  };

  if (DEBUG) console.log(`[api] → ${options.method || "GET"} ${path}`);

  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  } catch (netErr) {
    // Error de red puro: backend caído, CORS, DNS, etc.
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

// ── Banking ───────────────────────────────────────────────────────────────────

export async function getSupportedBanks() {
  return request("/banking/banks");
}

export async function getBankAccounts() {
  return request("/banking/accounts");
}

export async function connectBank({ bankId, rut, password }) {
  return request("/banking/connect", {
    method: "POST",
    body:   JSON.stringify({ bankId, rut, password }),
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
