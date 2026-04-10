// ─────────────────────────────────────────────────────────────────────────────
// services/financeService.js
// Lógica financiera centralizada. Lee y escribe en Supabase via dbService.
//
// FIXES v2:
//   · balance real desde bank_accounts.last_balance (suma de cuentas activas)
//   · Si no hay bancos → fallback income_range - expenses
//   · expenses solo cuenta transacciones category !== "income"
//   · bankAccounts expuesto en summary para que Mr. Money lo vea
// ─────────────────────────────────────────────────────────────────────────────

import * as db from "./dbService.js";
import { trackSpendingEvent, trackGoalEvent } from "./ariaService.js";
import { getBankBalances } from "./bankSyncService.js";

const MOCK_CHALLENGES = [
  { id: "no_uber",     label: "Sin Uber 7 días",         icon: "🚗", desc: "No gastes en transporte esta semana", category: "transport",     limitAmt: 0,     days: 7,  pts: 150, difficulty: "Medio"   },
  { id: "food_budget", label: "Comida bajo $80K",         icon: "🍔", desc: "Gasta menos de $80.000 en comida",   category: "food",          limitAmt: 80000, days: 30, pts: 200, difficulty: "Difícil" },
  { id: "no_entert",   label: "Sin entretención 5 días",  icon: "🎮", desc: "Pausa el gasto en ocio 5 días",      category: "entertainment", limitAmt: 0,     days: 5,  pts: 100, difficulty: "Fácil"   },
  { id: "save_60k",    label: "Ahorra $60K este mes",     icon: "💰", desc: "Reduce gastos para ahorrar $60.000", category: null,            limitAmt: 60000, days: 30, pts: 250, difficulty: "Difícil" },
  { id: "no_subs",     label: "Cancela 1 suscripción",    icon: "📺", desc: "Elimina una suscripción que no usas",category: "subscriptions", limitAmt: 0,     days: 1,  pts: 80,  difficulty: "Fácil"   },
  { id: "daily_track", label: "Registra 5 gastos",        icon: "📝", desc: "Anota 5 transacciones en la app",   category: null,            limitAmt: 5,     days: 7,  pts: 120, difficulty: "Fácil"   },
];

const BADGE_DEFINITIONS = [
  { id: "first_tx",    label: "Primera TX",   icon: "✏️", condition: (pts, txs, done) => txs >= 1   },
  { id: "saver",       label: "Ahorrador",    icon: "💰", condition: (pts, txs, done) => done >= 1  },
  { id: "disciplined", label: "Disciplinado", icon: "🎯", condition: (pts, txs, done) => done >= 3  },
  { id: "tracker",     label: "Rastreador",   icon: "📊", condition: (pts, txs, done) => txs >= 10  },
  { id: "century",     label: "100 puntos",   icon: "⭐", condition: (pts, txs, done) => pts >= 100 },
  { id: "elite",       label: "Elite Sky",    icon: "🏆", condition: (pts, txs, done) => pts >= 500 },
];

function getUid(userId) { return userId || null; }

function parseIncomeRange(range) {
  const map = { "0-500k": 350000, "500k-1M": 750000, "1M-2M": 1500000, "2M+": 2500000 };
  return map[range] || 1200000;
}

function getCurrentPeriod() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

// ── Summary ───────────────────────────────────────────────────────────────────

export async function getSummary(userId) {
  const uid = getUid(userId);

  const [profile, transactions, bankData] = await Promise.all([
    db.getProfile(uid),
    db.getTransactions(uid),
    getBankBalances(uid).catch(() => ({ accounts: [], totalBalance: 0 })),
  ]);

  const estimatedIncome = parseIncomeRange(profile?.income_range);
  const hasBankAccounts = bankData.accounts.length > 0;

  // ── Filtrar transacciones al mes en curso ────────────────────────────────
  // Sin este filtro, expenses e income acumulan TODO el historial bancario,
  // inflando los números N veces según cuántos meses de movimientos existan.
  const period     = getCurrentPeriod();
  const monthTxs   = transactions.filter(t => t.date && t.date.startsWith(period));

  // Banco sincroniza gastos como negativos (ej: -4890), entradas manuales como positivos.
  // Usamos Math.abs para unificar ambas fuentes. Nunca filtramos por signo.
  const expenseTxs = monthTxs.filter(t => t.category !== "income" && t.amount != null && t.amount !== 0);
  const incomeTxs  = monthTxs.filter(t => t.category === "income"  && t.amount != null && t.amount !== 0);

  const expenses   = expenseTxs.reduce((s, t) => s + Math.abs(t.amount || 0), 0);
  const bankIncome = incomeTxs.reduce((s, t)  => s + Math.abs(t.amount || 0), 0);

  // ── income: fuente única, sin mezclar estimado con real ──────────────────
  // Math.max(estimatedIncome, bankIncome) es incorrecto: mezcla un número
  // ficticio del perfil con ingresos reales del banco.
  // Regla: si hay ingresos reales este mes → usarlos. Si no → estimado del perfil.
  const income = hasBankAccounts && bankIncome > 0 ? bankIncome : estimatedIncome;

  // ── balance: saldo real si hay bancos, proyección estimada si no ─────────
  const balance = hasBankAccounts
    ? bankData.totalBalance
    : Math.max(0, estimatedIncome - expenses);

  // ── Totales por categoría (solo mes en curso) ────────────────────────────
  const categoryTotals = {};
  expenseTxs.forEach((t) => {
    categoryTotals[t.category] = (categoryTotals[t.category] || 0) + t.amount;
  });

  const topCategory = Object.entries(categoryTotals).sort((a, b) => b[1] - a[1])[0] || null;

  // ── Tasas ────────────────────────────────────────────────────────────────
  // savingsRate nunca debe ser null — es calculable siempre que haya un income.
  const spendingRate = income > 0 ? Math.max(0, Math.round((expenses / income) * 100)) : 0;
  const savingsRate  = income > 0 ? Math.max(0, Math.round(((income - expenses) / income) * 100)) : 0;

  return {
    income,
    expenses,
    balance,
    spendingRate,
    savingsRate,
    categoryTotals,
    transactionCount: transactions.length,
    topCategory:      topCategory ? { category: topCategory[0], amount: topCategory[1] } : null,
    period,
    currency:         "CLP",
    // Flag para que el frontend sepa si income es dato real o estimado
    incomeIsReal:     hasBankAccounts && bankIncome > 0,
    // Datos bancarios expuestos para Mr. Money y el frontend
    bankAccounts:     bankData.accounts,
    totalBankBalance: bankData.totalBalance,
    hasBankAccounts,
  };
}

// ── Transactions ──────────────────────────────────────────────────────────────

export async function getTransactions(userId) {
  return db.getTransactions(getUid(userId));
}

export async function addTransaction(userId, tx) {
  const uid   = getUid(userId);
  const newTx = await db.insertTransaction(uid, tx);
  if (!newTx) throw new Error("Error al guardar la transacción");

  db.getProfile(uid).then((profile) => {
    if (profile) trackSpendingEvent(profile, newTx).catch(() => {});
  });

  return newTx;
}

export async function deleteTransaction(userId, txId) {
  return db.removeTransaction(getUid(userId), txId);
}

// ── Goals ─────────────────────────────────────────────────────────────────────

export async function getGoals(userId) {
  const uid   = getUid(userId);
  const goals = await db.getGoals(uid);
  const sum   = await getSummary(uid);

  // monthlyCapacity = cuánto puede ahorrar el usuario por mes.
  // Antes usaba totalBankBalance ($3.8M de saldo) — incorrecto, inflaba todas
  // las proyecciones. La capacidad mensual es ingreso menos gastos del mes.
  const monthlyCapacity = Math.max(0, sum.income - sum.expenses);

  return goals.map((g) => ({
    ...g,
    projection: calcGoalProjection(g, monthlyCapacity),
  }));
}

export async function addGoal(userId, goalData) {
  const uid  = getUid(userId);
  const goal = await db.insertGoal(uid, goalData);
  if (!goal) return { error: "Error al crear la meta" };

  const sum             = await getSummary(uid);
  const monthlyCapacity = Math.max(0, sum.income - sum.expenses);
  const goalWithProjection = { ...goal, projection: calcGoalProjection(goal, monthlyCapacity) };

  db.getProfile(uid).then((profile) => {
    if (profile) trackGoalEvent(profile, goalWithProjection, 0).catch(() => {});
  });

  return { goal: goalWithProjection };
}

export async function updateGoal(userId, goalId, updates) {
  const uid  = getUid(userId);
  const goal = await db.patchGoal(uid, goalId, updates);
  if (!goal) return { error: "Meta no encontrada" };

  const sum             = await getSummary(uid);
  const monthlyCapacity = Math.max(0, sum.income - sum.expenses);
  const pct             = Math.round(((goal.savedAmount || 0) / (goal.targetAmount || 1)) * 100);
  const goalWithProjection = { ...goal, projection: calcGoalProjection(goal, monthlyCapacity) };

  db.getProfile(uid).then((profile) => {
    if (profile) trackGoalEvent(profile, goalWithProjection, pct).catch(() => {});
  });

  return { goal: goalWithProjection };
}

export async function deleteGoal(userId, goalId) {
  return db.removeGoal(getUid(userId), goalId);
}

export function calcGoalProjection(goal, monthlyBalance) {
  const saved     = goal.savedAmount  || goal.saved_amount  || 0;
  const target    = goal.targetAmount || goal.target_amount || 1;
  const remaining = Math.max(0, target - saved);
  const pct       = Math.round((saved / target) * 100);
  const monthly   = Math.max(0, monthlyBalance || 0);

  let monthsToGoal  = null;
  let projectedDate = null;

  if (monthly > 0 && remaining > 0) {
    monthsToGoal = Math.ceil(remaining / monthly);
    const d      = new Date();
    d.setMonth(d.getMonth() + monthsToGoal);
    projectedDate = d.toISOString().split("T")[0];
  }

  return { pct, remaining, monthlySavings: monthly, monthsToGoal, projectedDate };
}

// ── Challenges ────────────────────────────────────────────────────────────────

export async function getUserChallengesState(userId) {
  const uid = getUid(userId);
  const [states, transactions, profile] = await Promise.all([
    db.getChallengeStates(uid),
    db.getTransactions(uid),
    db.getProfile(uid),
  ]);

  const activeIds    = states.filter(s => s.status === "active").map(s => s.challenge_id);
  const completedIds = states.filter(s => s.status === "completed").map(s => s.challenge_id);
  const points       = profile?.points || 0;

  const active    = MOCK_CHALLENGES.filter(ch => activeIds.includes(ch.id))
                      .map(ch => ({ ...ch, progress: calcChallengeProgress(ch, transactions) }));
  const completed = MOCK_CHALLENGES.filter(ch => completedIds.includes(ch.id));
  const available = MOCK_CHALLENGES.filter(ch => !activeIds.includes(ch.id) && !completedIds.includes(ch.id));

  return { active, completed, available, points };
}

export async function activateChallenge(userId, challengeId) {
  const uid    = getUid(userId);
  const ch     = MOCK_CHALLENGES.find(c => c.id === challengeId);
  if (!ch) return { error: "Desafío no encontrado" };

  const states = await db.getChallengeStates(uid);
  if (states.find(s => s.challenge_id === challengeId)) return { error: "Desafío ya activo o completado" };

  await db.insertChallengeState(uid, challengeId);
  return { success: true, challenge: ch };
}

export async function completeChallenge(userId, challengeId) {
  const uid          = getUid(userId);
  const transactions = await db.getTransactions(uid);
  const ch           = MOCK_CHALLENGES.find(c => c.id === challengeId);
  if (!ch) return { error: "Desafío no encontrado" };

  const progress = calcChallengeProgress(ch, transactions);
  if (!progress.done) return { error: "Desafío aún no completado" };

  await db.completeChallengeState(uid, challengeId, ch.pts);
  await db.addPoints(uid, ch.pts);
  const profile = await db.getProfile(uid);

  return { success: true, challenge: ch, pointsEarned: ch.pts, totalPoints: profile?.points || ch.pts };
}

export function calcChallengeProgress(challenge, transactions) {
  // Gastos bancarios = negativos, manuales = positivos → Math.abs unifica ambos
  const txs = (transactions || []).filter(t => t.category !== "income");

  if (challenge.id === "daily_track") {
    const done = Math.min(transactions.length, 5);
    return { pct: Math.round((done / 5) * 100), done: done >= 5 };
  }
  if (challenge.id === "save_60k") {
    const spent = txs.reduce((s, t) => s + Math.abs(t.amount || 0), 0);
    const saved = Math.max(0, 1200000 - spent);
    return { pct: Math.round((Math.min(saved, 60000) / 60000) * 100), done: saved >= 60000 };
  }
  if (challenge.category && challenge.limitAmt === 0) {
    const spent = txs.filter(t => t.category === challenge.category).reduce((s, t) => s + Math.abs(t.amount || 0), 0);
    return { pct: spent === 0 ? 100 : 0, done: spent === 0 };
  }
  if (challenge.category && challenge.limitAmt > 0) {
    const spent = txs.filter(t => t.category === challenge.category).reduce((s, t) => s + Math.abs(t.amount || 0), 0);
    const prog  = Math.max(0, challenge.limitAmt - spent);
    return { pct: Math.round((prog / challenge.limitAmt) * 100), done: spent > 0 && spent <= challenge.limitAmt };
  }
  return { pct: 0, done: false };
}

// ── Gamification ──────────────────────────────────────────────────────────────

export async function evaluateBadges(userId) {
  const uid = getUid(userId);
  const [profile, transactions, challengeStates, earnedIds] = await Promise.all([
    db.getProfile(uid),
    db.getTransactions(uid),
    db.getChallengeStates(uid),
    db.getEarnedBadges(uid),
  ]);

  const points    = profile?.points || 0;
  const doneCount = challengeStates.filter(s => s.status === "completed").length;

  const newBadges = BADGE_DEFINITIONS.filter(
    b => !earnedIds.includes(b.id) && b.condition(points, transactions.length, doneCount)
  );

  await Promise.all(newBadges.map(b => db.insertBadge(uid, b.id)));
  const allEarned = [...earnedIds, ...newBadges.map(b => b.id)];

  return {
    allBadges: BADGE_DEFINITIONS.map(b => ({ id: b.id, label: b.label, icon: b.icon, earned: allEarned.includes(b.id) })),
    newBadges,
  };
}

export async function getUserProfile(userId) {
  const uid     = getUid(userId);
  const profile = await db.getProfile(uid);
  const points  = profile?.points || 0;

  return {
    user: {
      id:       uid,
      name:     profile?.display_name || "Usuario",
      income:   parseIncomeRange(profile?.income_range),
      currency: "CLP",
    },
    points,
    level:         Math.floor(points / 100) + 1,
    levelProgress: points % 100,
    earnedBadgeIds: await db.getEarnedBadges(uid),
  };
}

// ── Simulation ────────────────────────────────────────────────────────────────

export async function computeSimulation(userId, simulationId, customAmount = null) {
  const uid          = getUid(userId);
  const [transactions, profile] = await Promise.all([
    db.getTransactions(uid),
    db.getProfile(uid),
  ]);

  const income = parseIncomeRange(profile?.income_range);
  const categoryTotals = {};
  transactions
    .filter(t => t.category !== "income")
    .forEach(t => { categoryTotals[t.category] = (categoryTotals[t.category] || 0) + t.amount; });

  const QUICK_SIMS = [
    { id: "uber",   category: "transport",     cutPct: 0.6 },
    { id: "eating", category: "food",          cutPct: 0.4 },
    { id: "subs",   category: "subscriptions", cutPct: 0.5 },
    { id: "save5",  fixedSavePct: 0.05 },
    { id: "save10", fixedSavePct: 0.10 },
  ];

  let monthlySaving = 0;
  if (simulationId === "custom" && customAmount) {
    monthlySaving = customAmount;
  } else {
    const sim = QUICK_SIMS.find(s => s.id === simulationId);
    if (!sim) return null;
    monthlySaving = sim.fixedSavePct
      ? Math.round(income * sim.fixedSavePct)
      : Math.round((categoryTotals[sim.category] || 30000) * sim.cutPct);
  }

  return { simulationId, monthlySaving, months3: monthlySaving * 3, months6: monthlySaving * 6, months12: monthlySaving * 12 };
}