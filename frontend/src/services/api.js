// ─────────────────────────────────────────────────────────────────────────────
// services/api.js
//
// Único canal frontend → backend.
// userId se pasa en el header x-user-id en TODAS las llamadas.
// El backend lo lee desde el header — no desde el body, no desde el .env.
// ─────────────────────────────────────────────────────────────────────────────

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:3001/api";

// userId se inyecta globalmente — Sky.jsx lo establece al iniciar
let _userId = null;
export function setUserId(id) { _userId = id; }

async function request(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    // El backend lee el userId desde este header en cada request
    // así nunca necesita DEV_USER_ID ni configuración manual
    ..._userId ? { "x-user-id": _userId } : {},
    ...(options.headers || {}),
  };

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });

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
  return request("/transactions", {
    method: "POST",
    body:   JSON.stringify(tx),
  });
}

export async function deleteTransaction(id) {
  return request(`/transactions/${id}`, { method: "DELETE" });
}

// ── Chat ──────────────────────────────────────────────────────────────────────
export async function sendChat(message, history = []) {
  return request("/chat", {
    method: "POST",
    body:   JSON.stringify({ message, history }),
  });
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
  return request("/goals", {
    method: "POST",
    body:   JSON.stringify(goal),
  });
}

export async function updateGoalSaved(id, savedAmount) {
  return request(`/goals/${id}`, {
    method: "PATCH",
    body:   JSON.stringify({ savedAmount }),
  });
}

export async function deleteGoal(id) {
  return request(`/goals/${id}`, { method: "DELETE" });
}
