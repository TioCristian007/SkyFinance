// ─────────────────────────────────────────────────────────────────────────────
// services/api.js — único canal frontend → backend
// userId se pasa en el header x-user-id en TODAS las llamadas
// ─────────────────────────────────────────────────────────────────────────────

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:3001/api";

let _userId = null;
export function setUserId(id) { _userId = id; }

async function request(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
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