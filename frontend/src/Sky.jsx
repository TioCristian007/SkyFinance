// ─────────────────────────────────────────────────────────────────────────────
// Sky.jsx — Rediseño frontend completo · Abril 2026
//
// DROP-IN REPLACEMENT de Sky.jsx original.
// Mantiene exactamente la misma interfaz de props, mismos imports de api.js,
// misma lógica de negocio y llamadas al backend.
// Solo cambia la capa visual.
//
// Props: { userId, userEmail }
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useRef, useEffect } from "react";
import { fmt, fmtK, nowTime } from "./utils/format.js";
import { BADGES } from "./data/challenges.js";
import { QUICK_SIMS } from "./data/simulations.js";
import * as api from "./services/api.js";
import { setUserId } from "./services/api.js";
import { signOut } from "./services/supabase.js";

import DonutChart      from "./components/DonutChart.jsx";
import CatBars         from "./components/CatBars.jsx";
import TxItem          from "./components/TxItem.jsx";
import AddTxForm       from "./components/AddTxForm.jsx";
import GoalCard        from "./components/GoalCard.jsx";
import AddGoalForm     from "./components/AddGoalForm.jsx";
import AddSavingsModal from "./components/AddSavingsModal.jsx";
import { ChatBubble, TypingDots, XPBar } from "./components/ChatComponents.jsx";
import { ChallengeCard, BadgeItem }      from "./components/ChallengeComponents.jsx";
import BankConnect                        from "./components/BankConnect.jsx";
import { MrMoneyProposals }              from "./components/MrMoneyProposal.jsx";
import SimulationChart                   from "./components/SimulationChart.jsx";

// ─────────────────────────────────────────────────────────────────────────────
// CONSTANTES
// ─────────────────────────────────────────────────────────────────────────────

const CHAT_STARTERS = [
  "¿Cómo voy este mes?",
  "Quiero ahorrar para un viaje",
  "¿Qué desafío me recomiendas?",
  "¿Cuánto ahorro al año si reduzco Uber?",
  "Analiza mis gastos",
];

const INITIAL_MESSAGE = {
  id: 0, role: "bot", time: nowTime(),
  text: "Hola. Soy Mr. Money, tu asistente en Sky.\n\nCargando tu resumen financiero...",
};

// Bancos chilenos — colores institucionales reales + logos
const BANK_META = {
  "Banco Estado": { bg: "#D42B2B", abbr: "BE", logo: "/assets/banks/bancoestado.png" },
  "Santander":    { bg: "#EC0000", abbr: "SA", logo: "/assets/banks/santander.png" },
  "BCI":          { bg: "#F5F5F5", abbr: "BC", logo: "/assets/banks/bci.png", logoDark: true },
  "Itaú":         { bg: "#F57F17", abbr: "IT", logo: null },
  "Falabella":    { bg: "#2D6B2D", abbr: "FA", logo: "/assets/banks/falabella.png" },
  "Scotiabank":   { bg: "#E65100", abbr: "SC", logo: null },
  "BICE":         { bg: "#2E7D32", abbr: "BI", logo: null },
  "de Chile":     { bg: "#1A237E", abbr: "CH", logo: "/assets/banks/banco-chile.png" },
};

const getBankMeta = (name = "") => {
  for (const [k, v] of Object.entries(BANK_META)) {
    if (name.includes(k)) return v;
  }
  return { bg: "#223650", abbr: name.slice(0, 2).toUpperCase() || "??", logo: null };
};

// Paleta de diseño
const P = {
  navy:     "#0D1B2A",
  navy2:    "#142233",
  navy3:    "#1C2F44",
  navy4:    "#223650",
  green:    "#00C853",
  green2:   "#00A844",
  green3:   "#007A32",
  greenBg:  "rgba(0,200,83,0.08)",
  greenBd:  "rgba(0,200,83,0.2)",
  bg:       "#F2F5F9",
  surface:  "#FFFFFF",
  border:   "#E4EAF1",
  border2:  "#D0D9E6",
  text:     "#0D1B2A",
  text2:    "#4A5568",
  text3:    "#8A96A8",
  red:      "#E53935",
  amber:    "#F59E0B",
  gold:     "#F9A825",
};

// Categorías con colores asignados
const CAT_COLORS = {
  food:          "#00C853",
  transport:     "#F59E0B",
  entertainment: "#8B5CF6",
  health:        "#06B6D4",
  housing:       "#3B82F6",
  education:     "#10B981",
  clothing:      "#EC4899",
  income:        "#00C853",
  other:         "#8A96A8",
};

// ─────────────────────────────────────────────────────────────────────────────
// ESTILOS GLOBALES (inyectados una vez)
// ─────────────────────────────────────────────────────────────────────────────

const GLOBAL_STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@300;400;500;600;700;800&family=Geist+Mono:wght@400;500&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Geist', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: ${P.bg};
    color: ${P.text};
  }

  button { cursor: pointer; font-family: inherit; }
  input, textarea { font-family: inherit; }
  input[type=number]::-webkit-inner-spin-button { -webkit-appearance: none; }

  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-thumb { background: ${P.border2}; border-radius: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }

  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes slideDown {
    from { opacity: 0; transform: translateX(-50%) translateY(-10px); }
    to   { opacity: 1; transform: translateX(-50%) translateY(0); }
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
  @keyframes shimmer {
    0%   { background-position: -200% 0; }
    100% { background-position:  200% 0; }
  }

  .sky-nav-item:hover { background: rgba(255,255,255,0.06) !important; color: rgba(255,255,255,0.75) !important; }
  .sky-nav-item.active { background: rgba(0,200,83,0.1) !important; color: ${P.green} !important; font-weight: 700 !important; border: 1px solid rgba(0,200,83,0.2) !important; }

  .sky-card { transition: box-shadow 0.15s, transform 0.15s; }
  .sky-card:hover { box-shadow: 0 4px 20px rgba(13,27,42,0.07); transform: translateY(-1px); }

  .sky-bank-row:hover { background: rgba(255,255,255,0.04) !important; }
  .sky-tx-row:hover   { background: ${P.bg} !important; }
  .sky-starter:hover  { border-color: ${P.green} !important; color: ${P.green} !important; background: rgba(0,200,83,0.06) !important; }
`;

// ─────────────────────────────────────────────────────────────────────────────
// COMPONENTES PEQUEÑOS INTERNOS
// ─────────────────────────────────────────────────────────────────────────────

/** Punto decorativo mínimo */
const StatusDot = ({ size = 6, color }) => (
  <div style={{
    width: size, height: size, borderRadius: "50%",
    background: color || P.green, flexShrink: 0,
  }} />
);

/** Logo de banco — muestra logo real si existe, fallback a abreviación */
const BankLogo = ({ meta, size = 40, borderRadius = 10 }) => (
  <div style={{
    width: size, height: size, borderRadius,
    background: meta.bg, display: "flex", alignItems: "center",
    justifyContent: "center", flexShrink: 0, overflow: "hidden",
  }}>
    {meta.logo ? (
      <img
        src={meta.logo}
        alt=""
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
        onError={e => {
          e.target.style.display = "none";
          e.target.parentNode.insertAdjacentHTML("beforeend",
            `<span style="font-size:${Math.round(size * 0.28)}px;font-weight:800;color:#fff;letter-spacing:0.05em">${meta.abbr}</span>`
          );
        }}
      />
    ) : (
      <span style={{ fontSize: Math.round(size * 0.28), fontWeight: 800, color: "#fff", letterSpacing: "0.05em" }}>
        {meta.abbr}
      </span>
    )}
  </div>
);


/** KPI card del topbar del dashboard */
const KpiCard = ({ label, value, color, sub }) => (
  <div className="sky-card" style={{
    background: P.surface, border: `1px solid ${P.border}`,
    borderRadius: 14, padding: "18px 20px",
  }}>
    <div style={{ fontSize: 11, color: P.text3, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 8 }}>
      {label}
    </div>
    <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.6px", color, marginBottom: 4, fontVariantNumeric: "tabular-nums" }}>
      {value}
    </div>
    <div style={{ fontSize: 11, color: P.text3 }}>{sub}</div>
  </div>
);

/** Card de banco individual — versión compacta para grid */
const BankCardCompact = ({ acc, total, blurred = false }) => {
  const meta  = getBankMeta(acc.bankName);
  const pct   = total > 0 ? Math.round((acc.balance / total) * 100) : 0;
  const fmtCLP = (n) => new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n ?? 0);
  const bStyle = blurred ? { filter: "blur(9px)", userSelect: "none" } : {};

  return (
    <div className="sky-bank-row" style={{
      padding: "18px 20px",
      borderRight: "1px solid rgba(255,255,255,0.06)",
      borderBottom: "1px solid rgba(255,255,255,0.06)",
      display: "flex", flexDirection: "column", gap: 12,
      transition: "background 0.12s",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <BankLogo meta={meta} size={40} borderRadius={10} />
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#fff" }}>{acc.bankName ?? "Banco"}</div>
          <div style={{ fontSize: 11, color: "rgba(255,255,255,0.35)", marginTop: 1, fontFamily: "'Geist Mono', monospace" }}>
            {acc.accountType ?? "Cuenta"} · ••{acc.last4 ?? "••••"}
          </div>
        </div>
      </div>
      <div>
        <div style={{ fontSize: 18, fontWeight: 800, color: "#fff", letterSpacing: "-0.5px", fontVariantNumeric: "tabular-nums", ...bStyle }}>
          {fmtCLP(acc.balance)}
        </div>
        <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 2 }}>
          hace {acc.minutesAgo ?? "?"} min
        </div>
      </div>
      <div style={{ height: 3, background: "rgba(255,255,255,0.08)", borderRadius: 99, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: meta.bg, opacity: 0.7, borderRadius: 99 }} />
      </div>
    </div>
  );
};

/** Card de banco — versión expandida para la página Bancos */
const BankCardFull = ({ acc, blurred = false }) => {
  const meta   = getBankMeta(acc.bankName);
  const fmtCLP = (n) => new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n ?? 0);
  const bStyle = blurred ? { filter: "blur(9px)", userSelect: "none" } : {};

  return (
    <div className="sky-bank-row" style={{
      display: "flex", alignItems: "center", gap: 14,
      padding: "16px 22px",
      borderBottom: "1px solid rgba(255,255,255,0.06)",
      transition: "background 0.12s",
    }}>
      <BankLogo meta={meta} size={48} borderRadius={12} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: "#fff" }}>{acc.bankName ?? "Banco"}</div>
        <div style={{ fontSize: 12, color: "rgba(255,255,255,0.35)", marginTop: 1, fontFamily: "'Geist Mono', monospace" }}>
          {acc.accountType ?? "Cuenta"} · ••{acc.last4 ?? "••••"}
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 17, fontWeight: 800, color: "#fff", fontVariantNumeric: "tabular-nums", ...bStyle }}>
          {fmtCLP(acc.balance)}
        </div>
        <div style={{ fontSize: 11, color: "rgba(255,255,255,0.3)", marginTop: 2 }}>
          hace {acc.minutesAgo ?? "?"} min
        </div>
      </div>
    </div>
  );
};

/** Ítem de movimiento en el ticker live */
const TickerItem = ({ tx }) => {
  const isIncome = tx.category === "income";
  const fmtK2 = (n) => {
    const a = Math.abs(n ?? 0);
    if (a >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
    if (a >= 1_000) return `$${Math.round(n / 1_000)}K`;
    return `$${Math.round(n)}`;
  };

  return (
    <div className="sky-bank-row" style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "10px 20px",
      borderBottom: "1px solid rgba(255,255,255,0.04)",
      transition: "background 0.1s",
    }}>
      <div style={{
        width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
        background: isIncome ? P.green : "#FF6B6B",
      }} />
      <div style={{ flex: 1, overflow: "hidden" }}>
        <div style={{ fontSize: 13, color: "rgba(255,255,255,0.7)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {tx.description ?? tx.category}
        </div>
      </div>
      <div style={{ fontSize: 13, fontWeight: 700, flexShrink: 0, color: isIncome ? P.green : "#FF6B6B", fontVariantNumeric: "tabular-nums" }}>
        {isIncome ? "+" : "−"}{fmtK2(tx.amount)}
      </div>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// COMPONENTE PRINCIPAL
// ─────────────────────────────────────────────────────────────────────────────

export default function Sky({ userId, userEmail }) {
  setUserId(userId);

  // ── Navegación ──────────────────────────────────────────────────────────────
  const [tab, setTab] = useState("dashboard");

  // ── Datos del servidor ──────────────────────────────────────────────────────
  const [summary,    setSummary]    = useState(null);
  const [profile,    setProfile]    = useState({ points: 0, level: 1, levelProgress: 0, earnedBadgeIds: [] });
  const [allBadges,  setAllBadges]  = useState([]);
  const [txs,        setTxs]        = useState([]);
  const [challenges, setChallenges] = useState({ active: [], completed: [], available: [] });
  const [goals,      setGoals]      = useState([]);
  const [bankBalances, setBankBalances] = useState({ accounts: [], totalBalance: 0 });

  // ── UI local ────────────────────────────────────────────────────────────────
  const [loading,      setLoading]      = useState(true);
  const [txLoading,    setTxLoading]    = useState(false);
  const [messages,     setMsgs]         = useState([INITIAL_MESSAGE]);
  const [input,        setInput]        = useState("");
  const [typing,       setTyping]       = useState(false);
  const [apiError,     setApiErr]       = useState(false);
  const [toast,        setToast]        = useState(null);
  const [showAddGoal,  setShowAddGoal]  = useState(false);
  const [goalLoading,  setGoalLoading]  = useState(false);
  const [savingsTarget, setSavingsTarget] = useState(null);
  const [txFilter,     setTxFilter]     = useState("all");
  const [bankFilter,   setBankFilter]   = useState("all");
  const [dateFilter,   setDateFilter]   = useState("mes-actual"); // "mes-actual" | "ultimos-30"
  const [privacyMode,  setPrivacyMode]  = useState(false);
  const [simMode,      setSimMode]      = useState("quick");
  const [activeSim,    setActiveSim]    = useState(null);
  const [simResult,    setSimResult]    = useState(null);
  const [simLabel,     setSimLabel]     = useState("");
  const [customAmt,    setCustomAmt]    = useState("");
  const [pendingProposals,    setPendingProposals]    = useState([]);
  const [proposalLoadingId,   setProposalLoadingId]   = useState(null);
  const [initialSimType,      setInitialSimType]      = useState(null);

  const bottomRef = useRef(null);
  const inputRef  = useRef(null);

  // ── Carga inicial ────────────────────────────────────────────────────────────
  useEffect(() => {
    async function init() {
      try {
        const [summaryRes, txRes, chRes, goalsRes, bankAccRes] = await Promise.all([
          api.getSummary(),
          api.getTransactions(),
          api.getChallenges(),
          api.getGoals(),
          api.getBankAccounts().catch(() => ({ accounts: [], totalBalance: 0 })),
        ]);
        setSummary(summaryRes.summary);
        setProfile(summaryRes.profile);
        setAllBadges(summaryRes.badges.allBadges);
        setTxs(txRes.transactions);
        setChallenges(chRes);
        setGoals(goalsRes.goals);
        // Fuente única de verdad para cuentas bancarias:
        // la llamada directa a /api/banking/accounts tiene prioridad
        // (más fresca), con fallback a lo que embedió /api/summary.
        const bankData = bankAccRes.accounts?.length
          ? bankAccRes
          : {
              accounts:     summaryRes.summary.bankAccounts    || [],
              totalBalance: summaryRes.summary.totalBankBalance || 0,
            };
        setBankBalances(bankData);

        const hasBanks      = summaryRes.summary.hasBankAccounts;
        const incomeIsReal  = summaryRes.summary.incomeIsReal;
        const displayBal    = hasBanks
          ? summaryRes.summary.totalBankBalance
          : summaryRes.summary.balance;
        const balLabel = hasBanks ? "en saldo bancario real" : "disponibles estimados";
        const incomeLabel = incomeIsReal
          ? `Ingresaste ${fmt(summaryRes.summary.income)} este mes.`
          : `Tu ingreso estimado es ${fmt(summaryRes.summary.income)}/mes.`;

        setMsgs([{
          ...INITIAL_MESSAGE,
          text: `Hola, ${summaryRes.profile.user.name}. Soy Mr. Money, tu asistente financiero.\n\nTienes ${fmt(displayBal)} ${balLabel}. ${incomeLabel} ¿En qué te ayudo hoy?`,
        }]);
      } catch (e) {
        console.error("[Sky] init error:", e.message);
      } finally {
        setLoading(false);
      }
    }
    init();
  }, []);

  useEffect(() => {
    if (tab === "chat") bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, typing, tab]);

  // ── Helpers ──────────────────────────────────────────────────────────────────
  const showToast = (msg, type = "green") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3000);
  };

  const addBotMsg = (text) =>
    setMsgs((prev) => [...prev, { id: Date.now() + Math.random(), role: "bot", text, time: nowTime() }]);

  const refreshSummary = async () => {
    try {
      const res = await api.getSummary();
      setSummary(res.summary);
      setProfile(res.profile);
      setAllBadges(res.badges.allBadges);
      if (res.badges.newBadges?.length) {
        res.badges.newBadges.forEach((b) => showToast(`🏅 Badge: ${b.label}!`, "gold"));
      }
    } catch (e) {
      console.error("[Sky] refreshSummary:", e.message);
    }
  };

  // ── Chat ──────────────────────────────────────────────────────────────────────
  const send = async (text) => {
    if (!text.trim() || typing) return;
    setMsgs((prev) => [...prev, { id: Date.now(), role: "user", text: text.trim(), time: nowTime() }]);
    setInput(""); setTyping(true); setApiErr(false);
    try {
      const result = await api.sendChat(text, messages);
      addBotMsg(result.reply);
      if (result.proposals?.length) setPendingProposals((prev) => [...prev, ...result.proposals]);
      if (result.navigations?.length) {
        const nav = result.navigations[0];
        setInitialSimType(nav.simulation_type);
        if (nav.custom_amount) setCustomAmt(String(nav.custom_amount));
        setTab("simulate");
      }
    } catch {
      setApiErr(true);
      addBotMsg(`Tienes ${fmt(summary?.balance ?? 0)} disponibles. ¿En qué te ayudo?`);
    } finally {
      setTyping(false);
      inputRef.current?.focus();
    }
  };

  // ── Transacciones ─────────────────────────────────────────────────────────────
  const addTx = async (tx) => {
    setTxLoading(true);
    try {
      const { transaction, summary: newSummary } = await api.addTransaction(tx);
      setTxs((prev) => [transaction, ...prev]);
      setSummary(newSummary);
      showToast("Gasto registrado ✓");
      await refreshSummary();
    } catch { showToast("Error al guardar el gasto", "red"); }
    finally { setTxLoading(false); }
  };

  const deleteTx = async (id) => {
    try {
      await api.deleteTransaction(id);
      setTxs((prev) => prev.filter((t) => t.id !== id));
      await refreshSummary();
    } catch (e) { console.error("[Sky] deleteTx:", e.message); }
  };

  // ── Desafíos ──────────────────────────────────────────────────────────────────
  const activateCh = async (ch) => {
    try {
      await api.activateChallenge(ch.id);
      showToast(`Desafío aceptado: ${ch.label}`);
      setChallenges(await api.getChallenges());
    } catch { showToast("Error al activar el desafío", "red"); }
  };

  const completeCh = async (ch) => {
    try {
      const { reply, pointsEarned } = await api.completeChallenge(ch.id);
      showToast(`🏆 +${pointsEarned} puntos!`, "gold");
      setChallenges(await api.getChallenges());
      await refreshSummary();
      setTab("chat"); setTyping(true);
      addBotMsg(reply);
    } catch (e) { console.error("[Sky] completeCh:", e.message); }
    finally { setTyping(false); }
  };

  // ── Simulaciones ──────────────────────────────────────────────────────────────
  const runSim = async (simId, customAmount = null) => {
    setActiveSim(simId);
    try {
      const result = await api.runSimulation(simId, customAmount);
      const label  = simId === "custom"
        ? `Ahorrar ${fmtK(customAmount)}/mes`
        : QUICK_SIMS.find((s) => s.id === simId)?.label ?? simId;
      setSimResult(result);
      setSimLabel(label);
    } catch { showToast("Error al calcular la simulación", "red"); }
  };

  // ── Metas ─────────────────────────────────────────────────────────────────────
  const createGoal = async (goalData) => {
    setGoalLoading(true);
    try {
      const { goal } = await api.addGoal(goalData);
      setGoals((prev) => [goal, ...prev]);
      setShowAddGoal(false);
      showToast(`Meta creada: ${goal.title}`);
    } catch { showToast("Error al crear la meta", "red"); }
    finally { setGoalLoading(false); }
  };

  const removeGoal = async (id) => {
    try {
      await api.deleteGoal(id);
      setGoals((prev) => prev.filter((g) => g.id !== id));
      showToast("Meta eliminada");
    } catch { showToast("Error al eliminar", "red"); }
  };

  const confirmAddSavings = async (goalId, newSavedAmount) => {
    try {
      const { goal } = await api.updateGoalSaved(goalId, newSavedAmount);
      setGoals((prev) => prev.map((g) => g.id === goalId ? goal : g));
      setSavingsTarget(null);
      if (goal.projection.pct >= 100) showToast("🎉 ¡Meta alcanzada!", "gold");
      else showToast("Ahorro actualizado ✓");
    } catch { showToast("Error al actualizar", "red"); }
  };

  // ── Propuestas de Mr. Money ────────────────────────────────────────────────
  const handleProposalAccept = async (proposal) => {
    const pid = proposal.id || proposal.type;
    setProposalLoadingId(pid);
    try {
      const { type, input: inp } = proposal;
      if (type === "propose_goal") {
        await createGoal({ title: inp.title, targetAmount: inp.target_amount, deadline: inp.deadline || null });
        addBotMsg(`✅ Meta "${inp.title}" creada.`);
      }
      if (type === "propose_challenge") {
        await api.activateChallenge(inp.challenge_id);
        showToast("Desafío activado ✓");
        setChallenges(await api.getChallenges());
        addBotMsg("🏆 Desafío activado. A por ello.");
      }
      if (type === "propose_delete_goal") {
        await removeGoal(inp.goal_id);
        addBotMsg(`🗑️ Meta "${inp.goal_title}" eliminada.`);
      }
      if (type === "propose_goal_contribution") {
        const goal = goals.find((g) => g.id === inp.goal_id);
        if (goal) {
          await confirmAddSavings(inp.goal_id, (goal.saved_amount || 0) + inp.amount);
          addBotMsg(`💰 Aporte de ${new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(inp.amount)} registrado en "${inp.goal_title}".`);
        }
      }
      setPendingProposals((prev) => prev.filter((p) => (p.id || p.type) !== pid));
    } catch (e) {
      showToast("Error al ejecutar la acción", "red");
      console.error("[proposal]:", e.message);
    } finally { setProposalLoadingId(null); }
  };

  const handleProposalReject = (proposal) => {
    const pid = proposal.id || proposal.type;
    setPendingProposals((prev) => prev.filter((p) => (p.id || p.type) !== pid));
    addBotMsg("Entendido, lo dejo para después. ¿En qué más te ayudo?");
  };

  // ─────────────────────────────────────────────────────────────────────────────
  // LOADING SCREEN
  // ─────────────────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div style={{
        minHeight: "100vh", background: P.navy,
        display: "flex", alignItems: "center", justifyContent: "center",
        flexDirection: "column", gap: 20,
      }}>
        <img
          src="/assets/sky-logo-transparent.png" alt="Sky"
          style={{ height: 40, opacity: 0.9 }}
          onError={e => { e.target.style.display = "none"; }}
        />
        <div style={{
          width: 32, height: 32, borderRadius: "50%",
          border: `3px solid rgba(0,200,83,0.25)`,
          borderTopColor: P.green,
          animation: "spin 0.8s linear infinite",
        }} />
        <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
        <div style={{ fontSize: 13, color: "rgba(255,255,255,0.35)", fontFamily: "'Geist', sans-serif" }}>
          Cargando...
        </div>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // VALORES DERIVADOS
  // ─────────────────────────────────────────────────────────────────────────────

  const income          = summary?.income          ?? 0;
  const expenses        = summary?.expenses        ?? 0;
  const savingsRate     = summary?.savingsRate     ?? 0;
  const catTotals       = summary?.categoryTotals  ?? {};
  const points          = profile?.points          ?? 0;
  const hasBankAccounts = (bankBalances.accounts?.length ?? 0) > 0;
  const totalBankBal    = hasBankAccounts ? bankBalances.totalBalance : 0;
  // balance: saldo real si hay bancos, proyección si no
  const balance         = hasBankAccounts ? totalBankBal : (summary?.balance ?? 0);
  const spendingRate    = summary?.spendingRate ?? 0;
  // incomeIsReal: true = ingreso viene de transacciones bancarias reales del mes
  //               false = estimado del rango del perfil (alpha / sin banco)
  const incomeIsReal    = summary?.incomeIsReal ?? false;

  const fmtCLP = (n) => new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n ?? 0);

  // ── Filtrado por fecha para Movimientos ──────────────────────────────────────
  const todayStr = new Date().toISOString().split("T")[0];            // "2026-04-09"
  const period   = `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, "0")}`; // "2026-04"
  const cutoff30 = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().split("T")[0];        // hace 30 días

  const dateBoundTxs = txs.filter(tx => {
    const d = tx.date ?? tx.created_at ?? "";
    if (dateFilter === "mes-actual")  return d.startsWith(period);
    if (dateFilter === "ultimos-30")  return d >= cutoff30;
    return true;
  });

  // ── Helper de privacidad: oculta números cuando privacyMode está activo ────
  // Permite mostrar la app sin exponer datos financieros personales
  const N = (val) => privacyMode ? "•••" : val;   // valores de texto
  const $ = privacyMode ? { filter: "blur(9px)", userSelect: "none", transition: "filter 0.2s" } : {};

  const filteredTxs = dateBoundTxs.filter(tx => {
    const typeOk = txFilter === "all" ? true : txFilter === "income" ? tx.category === "income" : tx.category !== "income";
    const bankOk = bankFilter === "all" ? true : tx.bank_account_id === bankFilter;
    return typeOk && bankOk;
  });

  // Nav items
  const NAV = [
    { key: "dashboard",  label: "Dashboard",    badge: 0 },
    { key: "bancos",     label: "Mis Cuentas",  badge: 0 },
    { key: "expenses",   label: "Movimientos",  badge: 0 },
    { key: "goals",      label: "Metas",        badge: 0 },
    { key: "challenges", label: "Desafíos",     badge: challenges.active.length },
    { key: "simulate",   label: "Simular",      badge: 0 },
    { key: "chat",       label: "Mr. Money",    badge: 0, special: true },
  ];

  // Íconos SVG inline para nav
  const NAV_ICONS = {
    dashboard:  <svg viewBox="0 0 18 18" fill="none" width="16" height="16"><rect x="1" y="1" width="7" height="7" rx="2" stroke="currentColor" strokeWidth="1.5"/><rect x="10" y="1" width="7" height="7" rx="2" stroke="currentColor" strokeWidth="1.5"/><rect x="1" y="10" width="7" height="7" rx="2" stroke="currentColor" strokeWidth="1.5"/><rect x="10" y="10" width="7" height="7" rx="2" stroke="currentColor" strokeWidth="1.5"/></svg>,
    bancos:     <svg viewBox="0 0 18 18" fill="none" width="16" height="16"><path d="M1 7h16M3 7V4l6-2 6 2v3M3 7v8h12V7" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/><rect x="7" y="11" width="4" height="4" rx="1" stroke="currentColor" strokeWidth="1.5"/></svg>,
    expenses:   <svg viewBox="0 0 18 18" fill="none" width="16" height="16"><path d="M3 5h12M3 9h8M3 13h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/><path d="M14 11l2 2-2 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>,
    goals:      <svg viewBox="0 0 18 18" fill="none" width="16" height="16"><circle cx="9" cy="9" r="7" stroke="currentColor" strokeWidth="1.5"/><circle cx="9" cy="9" r="3" stroke="currentColor" strokeWidth="1.5"/><circle cx="9" cy="9" r="1" fill="currentColor"/></svg>,
    challenges: <svg viewBox="0 0 18 18" fill="none" width="16" height="16"><path d="M9 1l2 5h5l-4 3 1.5 5L9 11l-4.5 3L6 9 2 6h5L9 1z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg>,
    simulate:   <svg viewBox="0 0 18 18" fill="none" width="16" height="16"><path d="M2 14L6 8l3 4 3-6 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>,
    chat:       <svg viewBox="0 0 18 18" fill="none" width="16" height="16"><path d="M2 3h14a1 1 0 011 1v8a1 1 0 01-1 1H6l-4 3V4a1 1 0 011-1z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg>,
  };

  const PAGE_TITLES = {
    dashboard:  ["Dashboard",       "Resumen financiero del mes"],
    bancos:     ["Mis Cuentas",     hasBankAccounts ? `${bankBalances.accounts.length} cuenta${bankBalances.accounts.length !== 1 ? "s" : ""} conectada${bankBalances.accounts.length !== 1 ? "s" : ""}` : "Conecta tus bancos vía Open Banking"],
    expenses:   ["Movimientos",     `${txs.length} movimientos registrados`],
    goals:      ["Metas",           `${goals.length} meta${goals.length !== 1 ? "s" : ""} activa${goals.length !== 1 ? "s" : ""}`],
    challenges: ["Desafíos",        `${challenges.completed.length} desafío${challenges.completed.length !== 1 ? "s" : ""} completado${challenges.completed.length !== 1 ? "s" : ""}`],
    simulate:   ["Simular",         "Proyecciones y escenarios financieros"],
    chat:       ["Mr. Money",       "Tu copiloto financiero"],
  };

  const [pageTitle, pageSub] = PAGE_TITLES[tab] ?? ["Sky", ""];

  // ─────────────────────────────────────────────────────────────────────────────
  // RENDER
  // ─────────────────────────────────────────────────────────────────────────────

  return (
    <>
      <style>{GLOBAL_STYLES}</style>

      {/* ── Toast ── */}
      {toast && (
        <div style={{
          position: "fixed", top: 20, left: "50%",
          transform: "translateX(-50%)", zIndex: 9999,
          padding: "11px 22px", borderRadius: 30, color: "#fff",
          fontSize: 13, fontWeight: 700,
          background: toast.type === "gold"
            ? "linear-gradient(135deg,#F9A825,#E65100)"
            : toast.type === "red"
            ? "linear-gradient(135deg,#E53935,#B71C1C)"
            : `linear-gradient(135deg,${P.green},${P.green2})`,
          boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
          animation: "slideDown 0.25s ease",
          whiteSpace: "nowrap",
          fontFamily: "'Geist', sans-serif",
        }}>
          {toast.msg}
        </div>
      )}

      {/* ── ROOT LAYOUT ── */}
      <div style={{ display: "flex", height: "100vh", background: P.bg, overflow: "hidden" }}>

        {/* ════════════════════════════════════════
            SIDEBAR
        ════════════════════════════════════════ */}
        <aside style={{
          width: 240, flexShrink: 0,
          background: P.navy,
          display: "flex", flexDirection: "column",
          height: "100vh", overflow: "hidden",
        }}>
          {/* Logo */}
          <div style={{ padding: "18px 20px 16px", borderBottom: "1px solid rgba(255,255,255,0.07)", display: "flex", alignItems: "center", gap: 10 }}>
            <img
              src="/assets/sky-logo-transparent.png"
              alt="Sky"
              style={{ height: 30, objectFit: "contain", flexShrink: 0 }}
              onError={e => {
                e.target.style.display = "none";
                e.target.parentNode.insertAdjacentHTML("afterbegin", `<div style="width:32px;height:32px;border-radius:9px;background:#00C853;display:flex;align-items:center;justify-content:center;flex-shrink:0"><svg viewBox="0 0 20 20" width="18" height="18" fill="none"><path d="M10 2L2 7v11h16V7L10 2z" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/><path d="M7 18v-6h6v6" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/></svg></div>`);
              }}
            />
            <div>
              <div style={{ fontSize: 17, fontWeight: 800, color: "#fff", letterSpacing: "-0.3px", lineHeight: 1 }}>Sky</div>
              <div style={{ fontSize: 9, color: P.green, fontWeight: 700, letterSpacing: "0.15em", marginTop: 2 }}>FINANZAS</div>
            </div>
          </div>

          {/* Balance card con botón de privacidad integrado */}
          <div style={{
            margin: "14px 14px 6px",
            background: "rgba(255,255,255,0.05)",
            border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: 14, padding: "16px",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
              <div style={{ fontSize: 9, color: "rgba(255,255,255,0.35)", fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase" }}>
                {hasBankAccounts ? "Saldo Real" : "Disponible · Est."}
              </div>
              {/* Botón ocultar números — aquí junto al balance, donde tiene sentido */}
              <button
                onClick={() => setPrivacyMode(v => !v)}
                title={privacyMode ? "Mostrar números" : "Ocultar números"}
                style={{ background: "none", border: "none", cursor: "pointer", padding: "2px 4px", display: "flex", alignItems: "center", gap: 4, borderRadius: 6, transition: "opacity 0.15s", opacity: 0.6 }}
                onMouseOver={e => e.currentTarget.style.opacity = "1"}
                onMouseOut={e => e.currentTarget.style.opacity = "0.6"}
              >
                <svg viewBox="0 0 16 16" width="13" height="13" fill="none">
                  {privacyMode
                    ? <><path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z" stroke={P.green} strokeWidth="1.4"/><circle cx="8" cy="8" r="2" stroke={P.green} strokeWidth="1.4"/><path d="M2 2l12 12" stroke={P.green} strokeWidth="1.4" strokeLinecap="round"/></>
                    : <><path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z" stroke="rgba(255,255,255,0.5)" strokeWidth="1.4"/><circle cx="8" cy="8" r="2" stroke="rgba(255,255,255,0.5)" strokeWidth="1.4"/></>
                  }
                </svg>
                <span style={{ fontSize: 9, fontWeight: 700, color: privacyMode ? P.green : "rgba(255,255,255,0.4)" }}>
                  {privacyMode ? "VISIBLE" : "OCULTAR"}
                </span>
              </button>
            </div>
            <div style={{ fontSize: 22, fontWeight: 800, color: balance < 0 ? "#FF6B6B" : "#fff", letterSpacing: "-0.8px", marginBottom: 12, fontVariantNumeric: "tabular-nums", ...$ }}>
              {fmtCLP(balance)}
            </div>
            <div style={{ display: "flex", borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 10 }}>
              {[["Ingresos", fmtK(income), P.green], ["Gastos", fmtK(expenses), "#FF6B6B"]].map(([l, v, col]) => (
                <div key={l} style={{ flex: 1 }}>
                  <div style={{ fontSize: 9, color: "rgba(255,255,255,0.3)", fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase" }}>{l}</div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: col, marginTop: 2, fontVariantNumeric: "tabular-nums", ...$ }}>{v}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Nav */}
          <nav style={{ flex: 1, overflowY: "auto", padding: "8px 10px" }}>
            {NAV.map(({ key, label, badge, special }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`sky-nav-item${tab === key ? " active" : ""}`}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  width: "100%", padding: special ? "12px 12px" : "10px 12px",
                  border: "1px solid transparent",
                  background: "transparent",
                  color: "rgba(255,255,255,0.45)",
                  fontSize: 13, fontWeight: 500,
                  marginBottom: special ? 0 : 2,
                  marginTop: special ? 6 : 0,
                  textAlign: "left",
                  position: "relative",
                  transition: "all 0.15s",
                  borderTop: special ? "1px solid rgba(255,255,255,0.07)" : undefined,
                  borderRadius: special ? "0 0 10px 10px" : 10,
                }}
              >
                {tab === key && !special && (
                  <div style={{ position: "absolute", left: 0, top: "25%", height: "50%", width: 3, background: P.green, borderRadius: "0 3px 3px 0" }} />
                )}
                <span style={{ width: 18, height: 18, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, color: special && tab !== key ? P.green : "currentColor", opacity: 0.8 }}>
                  {NAV_ICONS[key]}
                </span>
                <span style={{ flex: 1, color: special && tab !== key ? "rgba(0,200,83,0.85)" : "inherit" }}>{label}</span>
                {badge > 0 && (
                  <span style={{ background: P.green, color: "#fff", borderRadius: 10, fontSize: 9, fontWeight: 800, padding: "2px 6px" }}>{badge}</span>
                )}
              </button>
            ))}
          </nav>

          {/* Footer: progreso + usuario */}
          <div style={{ padding: "14px 14px 18px", borderTop: "1px solid rgba(255,255,255,0.07)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <span style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", fontWeight: 600, letterSpacing: "0.08em" }}>PROGRESO</span>
              <span style={{ fontSize: 10, color: "rgba(255,255,255,0.4)", fontWeight: 600 }}>{points} puntos</span>
            </div>
            <div style={{ height: 3, background: "rgba(255,255,255,0.1)", borderRadius: 99, overflow: "hidden", marginBottom: 12 }}>
              <div style={{ height: "100%", width: `${Math.min(profile?.levelProgress ?? 0, 100)}%`, background: P.green, borderRadius: 99, transition: "width 0.6s" }} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 32, height: 32, borderRadius: "50%", background: "rgba(0,200,83,0.15)", border: "1.5px solid rgba(0,200,83,0.3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700, color: P.green, flexShrink: 0 }}>
                {(profile?.user?.name || "U").charAt(0).toUpperCase()}
              </div>
              <div style={{ flex: 1, overflow: "hidden" }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#fff", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{profile?.user?.name ?? "Usuario"}</div>
                <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{userEmail}</div>
              </div>
              <button
                onClick={async () => { try { await signOut(); } catch (e) { console.error(e); } }}
                title="Cerrar sesión"
                style={{ background: "rgba(255,255,255,0.07)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, color: "rgba(255,255,255,0.4)", fontSize: 12, padding: "5px 8px", flexShrink: 0, transition: "all 0.15s" }}
              >⏻</button>
            </div>
          </div>
        </aside>

        {/* ════════════════════════════════════════
            MAIN CONTENT
        ════════════════════════════════════════ */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

          {/* Topbar */}
          <div style={{ background: P.surface, borderBottom: `1px solid ${P.border}`, padding: "0 28px", height: 58, display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: P.text, letterSpacing: "-0.2px" }}>{pageTitle}</div>
              <div style={{ fontSize: 12, color: P.text3, marginTop: 1 }}>{pageSub}</div>
            </div>
          </div>

          {/* ── SCROLL AREA ── */}
          <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden" }}>

            {/* ══════════════════════════════
                DASHBOARD
            ══════════════════════════════ */}
            {tab === "dashboard" && (
              <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 20, animation: "fadeUp 0.22s ease" }}>

                {/* KPI Row */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
                  <KpiCard label="Saldo Total"      value={<span style={$}>{fmtCLP(balance)}</span>}        color={balance >= 0 ? P.green : P.red} sub={hasBankAccounts ? "· bancario real" : "· estimado"} />
                  <KpiCard label="Ingresos del mes" value={<span style={$}>{fmtCLP(income)}</span>}         color={P.text}  sub={incomeIsReal ? `${txs.filter(t=>t.category==="income").length} depósitos · real` : "· estimado del perfil"} />
                  <KpiCard label="Gastos del mes"   value={<span style={$}>{fmtCLP(expenses)}</span>}       color={P.red}   sub={`${txs.filter(t=>t.category!=="income").length} transacciones`} />
                  <KpiCard label="Tasa de ahorro"   value={<span style={$}>{`${savingsRate}%`}</span>} color={savingsRate >= 20 ? P.green : savingsRate >= 10 ? P.amber : P.red} sub={savingsRate >= 20 ? "Excelente ritmo" : savingsRate >= 10 ? "Ritmo moderado" : "Puedes mejorar"} />
                </div>

                {/* ─── MOMENTUM + BANKS ─── */}
                {/* Psicología aplicada:
                    · Lideramos con el LOGRO (savings rate), no con el número bruto
                    · El balance aparece al fondo de la columna derecha, como contexto
                    · Framing de progreso: "ahorras 33%" activa sensación de ganancia
                    · Near-miss en metas: 68% completado compele a terminar
                    · Bancos separados = números manejables, no un total intimidante
                */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>

                  {/* ── COLUMNA IZQUIERDA: Momentum ── */}
                  <div style={{
                    background: "linear-gradient(150deg, #0D1B2A 0%, #0F2336 60%, #102438 100%)",
                    borderRadius: 18, padding: "22px 22px",
                    border: "1px solid rgba(0,200,83,0.14)",
                    display: "flex", flexDirection: "column",
                  }}>
                    {/* Status row */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 22 }}>
                      <span style={{ fontSize: 9, fontWeight: 700, color: "rgba(255,255,255,0.35)", letterSpacing: "0.12em", textTransform: "uppercase" }}>
                        {hasBankAccounts ? `${bankBalances.accounts?.length ?? 0} cuenta${(bankBalances.accounts?.length ?? 0) !== 1 ? "s" : ""} conectada${(bankBalances.accounts?.length ?? 0) !== 1 ? "s" : ""}` : "Sin banco conectado"}
                      </span>
                      <button
                        onClick={() => setTab("bancos")}
                        style={{ background: "rgba(255,255,255,0.07)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 7, color: "rgba(255,255,255,0.45)", fontSize: 11, fontWeight: 600, padding: "4px 10px", cursor: "pointer" }}
                      >
                        {hasBankAccounts ? "Ver cuentas" : "Conectar"}
                      </button>
                    </div>

                    {/* HERO: Savings rate — el logro, no el saldo */}
                    {/* La tasa de ahorro es el número que hace sentir al usuario que GANA */}
                    <div style={{ marginBottom: 2 }}>
                      <span style={{
                        fontFamily: "'Geist', sans-serif",
                        fontSize: 52, fontWeight: 800, lineHeight: 1,
                        letterSpacing: "-2px",
                        color: savingsRate >= 20 ? P.green : savingsRate >= 10 ? P.amber : "rgba(255,255,255,0.7)",
                        ...$,
                      }}>
                        {savingsRate}%
                      </span>
                    </div>
                    <div style={{ fontSize: 12, color: "rgba(255,255,255,0.4)", marginBottom: 16, fontWeight: 400 }}>
                      de tus ingresos ahorrado este mes
                    </div>

                    {/* Savings bar — progreso visual */}
                    <div style={{ height: 3, background: "rgba(255,255,255,0.08)", borderRadius: 99, overflow: "hidden", marginBottom: 20 }}>
                      <div style={{
                        height: "100%",
                        width: `${Math.min(savingsRate, 100)}%`,
                        background: savingsRate >= 20
                          ? `linear-gradient(90deg,${P.green},${P.green2})`
                          : `linear-gradient(90deg,${P.amber},#D97706)`,
                        borderRadius: 99, transition: "width 1.2s ease",
                      }} />
                    </div>

                    {/* Income / Expenses — información, no alarma */}
                    <div style={{ display: "flex", gap: 8, marginBottom: "auto" }}>
                      <div style={{ flex: 1, background: "rgba(255,255,255,0.05)", borderRadius: 10, padding: "10px 12px" }}>
                        <div style={{ fontSize: 9, color: "rgba(255,255,255,0.3)", fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 5 }}>Ingresos</div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: P.green, fontVariantNumeric: "tabular-nums", ...$ }}>{fmtK(income)}</div>
                        {!incomeIsReal && <div style={{ fontSize: 9, color: "rgba(255,255,255,0.2)", marginTop: 2 }}>estimado</div>}
                      </div>
                      <div style={{ flex: 1, background: "rgba(255,255,255,0.05)", borderRadius: 10, padding: "10px 12px" }}>
                        <div style={{ fontSize: 9, color: "rgba(255,255,255,0.3)", fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 5 }}>Gastos</div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "#FF7070", fontVariantNumeric: "tabular-nums", ...$ }}>{fmtK(expenses)}</div>
                      </div>
                    </div>

                    {/* Meta activa — near-miss psychology */}
                    {/* Mostrar la meta más avanzada genera el efecto de "casi termino" */}
                    {goals.length > 0 && (() => {
                      const best = [...goals].sort((a, b) => (b.projection?.pct || 0) - (a.projection?.pct || 0))[0];
                      const pct  = Math.min(best.projection?.pct || 0, 100);
                      const months = best.projection?.monthsToGoal;
                      return (
                        <div
                          onClick={() => setTab("goals")}
                          style={{
                            marginTop: 16, background: "rgba(0,200,83,0.07)",
                            border: "1px solid rgba(0,200,83,0.15)", borderRadius: 12,
                            padding: "12px 14px", cursor: "pointer", transition: "background 0.15s",
                          }}
                          onMouseOver={e => { e.currentTarget.style.background = "rgba(0,200,83,0.12)"; }}
                          onMouseOut={e => { e.currentTarget.style.background = "rgba(0,200,83,0.07)"; }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 7 }}>
                            <span style={{ fontSize: 12, color: "rgba(255,255,255,0.65)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "70%" }}>
                              {best.title}
                            </span>
                            <span style={{ fontSize: 12, fontWeight: 700, color: P.green, flexShrink: 0 }}>{pct}%</span>
                          </div>
                          <div style={{ height: 4, background: "rgba(255,255,255,0.07)", borderRadius: 99, overflow: "hidden" }}>
                            <div style={{ height: "100%", width: `${pct}%`, background: `linear-gradient(90deg,${P.green},${P.green2})`, borderRadius: 99, transition: "width 1s ease" }} />
                          </div>
                          {months != null && (
                            <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 6 }}>
                              {months <= 1 ? "¡Lo logras el próximo mes!" : `${months} meses para lograrlo`}
                            </div>
                          )}
                        </div>
                      );
                    })()}

                    {goals.length === 0 && (
                      <button
                        onClick={() => setTab("goals")}
                        style={{ marginTop: 16, width: "100%", padding: "10px", borderRadius: 10, border: "1.5px dashed rgba(0,200,83,0.3)", background: "transparent", color: "rgba(0,200,83,0.6)", fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                      >
                        + Crear mi primera meta
                      </button>
                    )}
                  </div>

                  {/* ── COLUMNA DERECHA: Cuentas bancarias ── */}
                  {/* Fondo blanco = menos peso visual que el bloque negro original */}
                  {/* El total aparece al fondo, como dato de soporte, no como titular */}
                  <div style={{
                    background: P.surface, borderRadius: 18,
                    border: `1px solid ${P.border}`, overflow: "hidden",
                    display: "flex", flexDirection: "column",
                  }}>
                    <div style={{ padding: "14px 18px 10px", borderBottom: `1px solid ${P.border}` }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: P.text3, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                        Mis cuentas
                      </div>
                    </div>

                    {hasBankAccounts ? (
                      <>
                        {/* Bank rows: compactos, con barra proporcional */}
                        {bankBalances.accounts.map((acc) => {
                          const meta = getBankMeta(acc.bankName);
                          const pct  = bankBalances.totalBalance > 0
                            ? Math.round((acc.balance / bankBalances.totalBalance) * 100)
                            : 0;
                          return (
                            <div key={acc.id} className="sky-tx-row" style={{
                              padding: "13px 18px", borderBottom: `1px solid ${P.border}`,
                              display: "flex", alignItems: "center", gap: 12, transition: "background 0.1s",
                            }}>
                              <BankLogo meta={meta} size={36} borderRadius={9} />
                              <div style={{ flex: 1, overflow: "hidden", minWidth: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: 600, color: P.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                  {acc.bankName}
                                </div>
                                {/* Barra proporcional — muestra la distribución, no la magnitud */}
                                <div style={{ height: 3, background: P.bg, borderRadius: 99, overflow: "hidden", marginTop: 5 }}>
                                  <div style={{ height: "100%", width: `${pct}%`, background: meta.bg, opacity: 0.45, borderRadius: 99, transition: "width 0.9s ease" }} />
                                </div>
                              </div>
                              <div style={{ textAlign: "right", flexShrink: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: 700, color: P.text, fontVariantNumeric: "tabular-nums", ...$ }}>
                                  {fmtCLP(acc.balance)}
                                </div>
                                <div style={{ fontSize: 10, color: P.text3, marginTop: 2 }}>
                                  {acc.minutesAgo != null ? `hace ${acc.minutesAgo}m` : "·"}
                                </div>
                              </div>
                            </div>
                          );
                        })}

                        {/* Total al fondo — dato de soporte, no titular */}
                        {/* La jerarquía visual correcta: el logro (33%) arriba, el número bruto abajo */}
                        <div style={{ padding: "12px 18px", marginTop: "auto", background: P.bg, borderTop: `1px solid ${P.border}` }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <span style={{ fontSize: 11, color: P.text3, fontWeight: 600 }}>
                              Total · {bankBalances.accounts.length} cuenta{bankBalances.accounts.length !== 1 ? "s" : ""}
                            </span>
                            <span style={{ fontSize: 16, fontWeight: 800, color: P.text, fontVariantNumeric: "tabular-nums", letterSpacing: "-0.5px", ...$ }}>
                              {fmtCLP(bankBalances.totalBalance)}
                            </span>
                          </div>
                        </div>
                      </>
                    ) : (
                      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "32px 20px", gap: 10 }}>
                        <div style={{ fontSize: 28, opacity: 0.25 }}>🏦</div>
                        <div style={{ fontSize: 13, color: P.text3, textAlign: "center", lineHeight: 1.55 }}>
                          Conecta tu banco para<br/>ver tu saldo actualizado
                        </div>
                        <button
                          onClick={() => setTab("bancos")}
                          style={{ marginTop: 4, padding: "9px 20px", borderRadius: 9, border: "none", background: P.green, color: "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer" }}
                        >
                          Conectar banco
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                {/* ── TICKER: separado del bloque oscuro, sutil ── */}
                {/* Sacarlo del bloque negro lo hace menos pesado visualmente */}
                {txs.length > 0 && hasBankAccounts && (
                  <div style={{ background: P.surface, borderRadius: 14, border: `1px solid ${P.border}`, overflow: "hidden" }}>
                    <div style={{ padding: "9px 18px", borderBottom: `1px solid ${P.border}` }}>
                      <span style={{ fontSize: 9, fontWeight: 700, color: P.text3, letterSpacing: "0.1em", textTransform: "uppercase" }}>
                        Movimientos recientes
                      </span>
                    </div>
                    <div style={{ display: "flex", overflowX: "auto", scrollbarWidth: "none" }}>
                      {txs.slice(0, 6).map(tx => {
                        const isIncome = tx.category === "income";
                        return (
                          <div key={tx.id} style={{
                            flexShrink: 0, padding: "10px 16px",
                            borderRight: `1px solid ${P.border}`,
                            display: "flex", flexDirection: "column", gap: 3, minWidth: 140,
                          }}>
                            <div style={{ fontSize: 11, color: P.text2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 120 }}>
                              {tx.description ?? tx.category}
                            </div>
                            <div style={{ fontSize: 13, fontWeight: 700, color: isIncome ? P.green : P.text, fontVariantNumeric: "tabular-nums", ...$ }}>
                              {isIncome ? "+" : "−"}{fmtK(Math.abs(tx.amount ?? 0))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Mid grid: presupuesto + desafíos/metas */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>

                  {/* Presupuesto + Categorías */}
                  <div style={{ background: P.surface, borderRadius: 14, padding: "20px 22px", border: `1px solid ${P.border}` }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: P.text }}>Presupuesto del mes</div>
                      <button onClick={() => setTab("expenses")} style={{ fontSize: 11, fontWeight: 700, color: P.green3, background: P.greenBg, border: `1px solid ${P.greenBd}`, borderRadius: 7, padding: "4px 10px", cursor: "pointer" }}>Ver gastos</button>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 7 }}>
                      <span style={{ fontSize: 12, color: P.text2 }}>{fmtCLP(expenses)} de {fmtCLP(income)}</span>
                      <span style={{ fontSize: 12, fontWeight: 700, color: spendingRate > 85 ? P.red : P.green }}>{spendingRate ?? 0}%</span>
                    </div>
                    <div style={{ height: 8, background: P.bg, borderRadius: 99, overflow: "hidden", marginBottom: 18 }}>
                      <div style={{ height: "100%", width: `${Math.min(spendingRate ?? 0, 100)}%`, background: spendingRate > 85 ? `linear-gradient(90deg,${P.amber},${P.red})` : `linear-gradient(90deg,${P.green},${P.green2})`, borderRadius: 99, transition: "width 0.7s" }} />
                    </div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: P.text, marginBottom: 12 }}>Por categoría</div>
                    <CatBars categoryTotals={catTotals} />
                  </div>

                  {/* Desafíos + Metas */}
                  <div style={{ background: P.surface, borderRadius: 14, padding: "20px 22px", border: `1px solid ${P.border}`, display: "flex", flexDirection: "column" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: P.text }}>Desafíos activos</div>
                      <button onClick={() => setTab("challenges")} style={{ fontSize: 11, fontWeight: 700, color: P.green3, background: P.greenBg, border: `1px solid ${P.greenBd}`, borderRadius: 7, padding: "4px 10px", cursor: "pointer" }}>Ver todos</button>
                    </div>
                    {challenges.active.length === 0 ? (
                      <div style={{ textAlign: "center", padding: "16px 0", color: P.text3, fontSize: 13 }}>Sin desafíos activos</div>
                    ) : (
                      challenges.active.map(ch => (
                        <div key={ch.id} style={{ marginBottom: 12 }}>
                          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                            <span style={{ fontSize: 13, color: P.text, fontWeight: 600 }}>{ch.icon} {ch.label}</span>
                            <span style={{ fontSize: 12, fontWeight: 700, color: ch.progress?.done ? P.gold : P.green }}>{ch.progress?.pct ?? 0}%</span>
                          </div>
                          <div style={{ height: 5, background: P.bg, borderRadius: 99, overflow: "hidden" }}>
                            <div style={{ height: "100%", width: `${ch.progress?.pct ?? 0}%`, background: ch.progress?.done ? `linear-gradient(90deg,${P.gold},#E65100)` : `linear-gradient(90deg,${P.green},${P.green2})`, borderRadius: 99, transition: "width 0.6s" }} />
                          </div>
                          {ch.progress?.done && (
                            <button onClick={() => completeCh(ch)} style={{ marginTop: 6, width: "100%", padding: "7px", borderRadius: 8, border: "none", background: `linear-gradient(135deg,${P.gold},#E65100)`, color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>
                              ◆ Reclamar {ch.pts} pts
                            </button>
                          )}
                        </div>
                      ))
                    )}

                    {goals.length > 0 && (
                      <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${P.border}` }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                          <div style={{ fontSize: 13, fontWeight: 700, color: P.text }}>Metas</div>
                          <button onClick={() => setTab("goals")} style={{ fontSize: 11, fontWeight: 700, color: P.green3, background: P.greenBg, border: `1px solid ${P.greenBd}`, borderRadius: 7, padding: "4px 10px", cursor: "pointer" }}>Ver metas</button>
                        </div>
                        {goals.slice(0, 2).map(g => (
                          <div key={g.id} style={{ marginBottom: 8 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                              <span style={{ fontSize: 12, color: P.text, fontWeight: 600 }}>{g.title}</span>
                              <span style={{ fontSize: 11, color: P.text3 }}>{g.projection?.pct ?? 0}%</span>
                            </div>
                            <div style={{ height: 5, background: P.bg, borderRadius: 99, overflow: "hidden" }}>
                              <div style={{ height: "100%", width: `${Math.min(g.projection?.pct ?? 0, 100)}%`, background: P.green, borderRadius: 99 }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Badges */}
                <div style={{ background: P.surface, borderRadius: 14, padding: "18px 22px", border: `1px solid ${P.border}` }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: P.text, marginBottom: 14 }}>Colección de Badges</div>
                  <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
                    {allBadges.map(b => <BadgeItem key={b.id} badge={b} earned={b.earned} />)}
                  </div>
                </div>
              </div>
            )}

            {/* ══════════════════════════════
                MIS CUENTAS (BANCOS)
            ══════════════════════════════ */}
            {tab === "bancos" && (
              <div style={{ padding: "24px 28px", animation: "fadeUp 0.22s ease" }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 20, alignItems: "start" }}>

                  {/* Izquierda — BankConnect es la fuente única de verdad */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

                    {/* Header de total — solo cuando hay cuentas conectadas */}
                    {hasBankAccounts && (
                      <div style={{ background: P.navy, borderRadius: 16, padding: "18px 22px" }}>
                        <div style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
                          Saldo total · {bankBalances.accounts.length} cuenta{bankBalances.accounts.length !== 1 ? "s" : ""}
                        </div>
                        <div style={{ fontSize: 30, fontWeight: 800, color: "#fff", letterSpacing: "-1px", fontVariantNumeric: "tabular-nums", ...$ }}>
                          {fmtCLP(bankBalances.totalBalance)}
                        </div>
                      </div>
                    )}

                    {/* BankConnect: maneja lista de cuentas, sync, 2FA,
                        botón "+ Conectar otro banco", formulario con
                        Falabella + Banco de Chile + bancos próximamente */}
                    <div style={{ background: P.surface, borderRadius: 16, border: `1px solid ${P.border}` }}>
                      <BankConnect
                        onSyncComplete={async () => {
                          const [summaryRes, bankAccRes] = await Promise.all([
                            api.getSummary(),
                            api.getBankAccounts().catch(() => ({ accounts: [], totalBalance: 0 })),
                          ]);
                          setSummary(summaryRes.summary);
                          setProfile(summaryRes.profile);
                          setBankBalances(bankAccRes);
                        }}
                      />
                    </div>
                  </div>

                  {/* Derecha sticky — ticker + resumen */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 14, position: "sticky", top: 24 }}>
                    <div style={{ background: P.navy, borderRadius: 16, overflow: "hidden" }}>
                      <div style={{ padding: "14px 18px 10px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                        <span style={{ fontSize: 10, fontWeight: 700, color: "rgba(255,255,255,0.4)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Últimos movimientos</span>
                      </div>
                      <div style={{ maxHeight: 380, overflowY: "auto" }}>
                        {txs.slice(0, 20).map(tx => <TickerItem key={tx.id} tx={tx} />)}
                        {txs.length === 0 && (
                          <div style={{ padding: "32px 20px", textAlign: "center", color: "rgba(255,255,255,0.25)", fontSize: 13 }}>
                            Conecta un banco para ver movimientos
                          </div>
                        )}
                      </div>
                    </div>

                    <div style={{ background: P.surface, borderRadius: 14, padding: "16px 18px", border: `1px solid ${P.border}` }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: P.text, marginBottom: 12 }}>Resumen bancario</div>
                      {[
                        ["Cuentas conectadas", bankBalances.accounts?.length ?? 0],
                        ["Movimientos totales", txs.length],
                        ["Tasa de ahorro", <span style={$}>{`${savingsRate ?? 0}%`}</span>],
                      ].map(([l, v]) => (
                        <div key={l} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${P.border}` }}>
                          <span style={{ fontSize: 13, color: P.text2 }}>{l}</span>
                          <span style={{ fontSize: 13, fontWeight: 700, color: P.text }}>{v}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* ══════════════════════════════
                MOVIMIENTOS
            ══════════════════════════════ */}
            {tab === "expenses" && (() => {
              // Math.abs unifica montos negativos (banco) y positivos (manuales)
              const filteredExpenses = filteredTxs.filter(t => t.category !== "income").reduce((s, t) => s + Math.abs(t.amount || 0), 0);
              const filteredIncome2  = filteredTxs.filter(t => t.category === "income").reduce((s, t) => s + Math.abs(t.amount || 0), 0);

              const banksInTxs = [...new Map(
                dateBoundTxs.filter(t => t.bank_account_id).map(t => [t.bank_account_id, {
                  id:   t.bank_account_id,
                  name: bankBalances.accounts?.find(a => a.id === t.bank_account_id)?.bankName ?? "Banco",
                  abbr: getBankMeta(bankBalances.accounts?.find(a => a.id === t.bank_account_id)?.bankName).abbr,
                }])
              ).values()];

              const dateLabel = dateFilter === "mes-actual"
                ? `1–${new Date().getDate()} de ${new Date().toLocaleString("es-CL", { month: "long" })}`
                : "Últimos 30 días";

              return (
                /* Layout de altura fija — ocupa exactamente el viewport disponible */
                <div style={{ display: "flex", gap: 16, padding: "16px 24px", height: "calc(100vh - 58px)", overflow: "hidden", animation: "fadeUp 0.22s ease" }}>

                  {/* ── Panel izquierdo: fijo, no scrollea ── */}
                  <div style={{ width: 248, flexShrink: 0, display: "flex", flexDirection: "column", gap: 10, height: "100%", overflowY: "auto" }}>

                    {/* Filtros arriba — siempre visibles al abrir */}
                    <div style={{ background: P.surface, borderRadius: 12, padding: "12px 14px", border: `1px solid ${P.border}`, flexShrink: 0 }}>

                      {/* Período */}
                      <div style={{ fontSize: 10, fontWeight: 700, color: P.text3, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 6 }}>Período</div>
                      <div style={{ display: "flex", gap: 5, marginBottom: 10 }}>
                        {[["mes-actual", "Mes actual"], ["ultimos-30", "Últimos 30d"]].map(([val, lbl]) => (
                          <button key={val} onClick={() => setDateFilter(val)} style={{ flex: 1, padding: "7px 0", borderRadius: 7, border: "none", fontSize: 11, fontWeight: 600, background: dateFilter === val ? P.navy : P.bg, color: dateFilter === val ? "#fff" : P.text3, cursor: "pointer", transition: "all 0.15s" }}>{lbl}</button>
                        ))}
                      </div>

                      {/* Tipo */}
                      <div style={{ fontSize: 10, fontWeight: 700, color: P.text3, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 6 }}>Tipo</div>
                      <div style={{ display: "flex", gap: 5, marginBottom: banksInTxs.length > 1 ? 10 : 0 }}>
                        {[["all", "Todos"], ["expense", "Gastos"], ["income", "Ingresos"]].map(([val, lbl]) => (
                          <button key={val} onClick={() => setTxFilter(val)} style={{ flex: 1, padding: "7px 0", borderRadius: 7, border: "none", fontSize: 11, fontWeight: 600, background: txFilter === val ? P.navy : P.bg, color: txFilter === val ? "#fff" : P.text3, cursor: "pointer", transition: "all 0.15s" }}>{lbl}</button>
                        ))}
                      </div>

                      {/* Banco */}
                      {banksInTxs.length > 1 && (
                        <>
                          <div style={{ fontSize: 10, fontWeight: 700, color: P.text3, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 6 }}>Banco</div>
                          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                            <button onClick={() => setBankFilter("all")} style={{ padding: "5px 9px", borderRadius: 7, border: "none", fontSize: 11, fontWeight: 600, background: bankFilter === "all" ? P.navy : P.bg, color: bankFilter === "all" ? "#fff" : P.text3, cursor: "pointer" }}>Todos</button>
                            {banksInTxs.map(b => (
                              <button key={b.id} onClick={() => setBankFilter(b.id)} style={{ padding: "5px 9px", borderRadius: 7, border: "none", fontSize: 11, fontWeight: 600, background: bankFilter === b.id ? P.navy : P.bg, color: bankFilter === b.id ? "#fff" : P.text3, cursor: "pointer" }}>{b.abbr}</button>
                            ))}
                          </div>
                        </>
                      )}
                    </div>

                    {/* Resumen del período */}
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7, flexShrink: 0 }}>
                      {[
                        ["Gastos",   <span style={$}>{fmtK(filteredExpenses)}</span>, P.red],
                        ["Ingresos", <span style={$}>{fmtK(filteredIncome2)}</span>,  P.green],
                        ["Registros", filteredTxs.length, P.text],
                        ["Período",   dateLabel,           P.text3],
                      ].map(([l, v, col]) => (
                        <div key={l} style={{ background: P.surface, borderRadius: 10, padding: "9px 10px", border: `1px solid ${P.border}`, textAlign: "center" }}>
                          <div style={{ fontSize: 13, fontWeight: 800, color: col, fontVariantNumeric: "tabular-nums" }}>{v}</div>
                          <div style={{ fontSize: 10, color: P.text3, marginTop: 1 }}>{l}</div>
                        </div>
                      ))}
                    </div>

                    {/* Agregar movimiento */}
                    <div style={{ background: P.surface, borderRadius: 12, padding: "14px 16px", border: `1px solid ${P.border}` }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: P.text, marginBottom: 10 }}>Agregar manual</div>
                      <AddTxForm onAdd={addTx} disabled={txLoading} />
                    </div>
                  </div>

                  {/* ── Lista de movimientos: ocupa el resto de la altura ── */}
                  <div style={{ flex: 1, background: P.surface, borderRadius: 14, border: `1px solid ${P.border}`, overflow: "hidden", display: "flex", flexDirection: "column", minWidth: 0, height: "100%" }}>
                    <div style={{ padding: "11px 18px", borderBottom: `1px solid ${P.border}`, display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: P.text }}>
                        Movimientos <span style={{ fontWeight: 400, color: P.text3, fontSize: 12 }}>· {dateLabel}</span>
                      </div>
                      <div style={{ fontSize: 12, color: P.text3 }}>{filteredTxs.length} resultado{filteredTxs.length !== 1 ? "s" : ""}</div>
                    </div>

                    {/* Lista con flex: 1 y overflowY: auto — se adapta al espacio disponible */}
                    <div style={{ flex: 1, overflowY: "auto" }}>
                      {filteredTxs.length === 0 ? (
                        <div style={{ padding: "40px 20px", textAlign: "center", color: P.text3, fontSize: 13 }}>
                          {txs.length === 0 ? "Sin transacciones aún. ¡Agrega la primera!" : "Sin movimientos en este período"}
                        </div>
                      ) : (
                        filteredTxs.map(tx => {
                          // Categoría: usa los datos de categories.js para icono y label real
                          const isIncome = tx.category === "income" || tx.category === "transfer";
                          const catKey   = tx.category ?? "other";
                          // Colores y labels por categoría (inline para no depender de import aquí)
                          const CAT_UI = {
                            food: { icon: "🍔", label: "Comida", color: "#7B1FA2" },
                            transport: { icon: "🚌", label: "Transporte", color: "#F57C00" },
                            shopping: { icon: "🛍️", label: "Compras", color: "#C62828" },
                            subscriptions: { icon: "📱", label: "Suscripciones", color: "#00838F" },
                            entertainment: { icon: "🎮", label: "Entretención", color: "#AD1457" },
                            utilities: { icon: "💡", label: "Servicios", color: "#F9A825" },
                            housing: { icon: "🏠", label: "Vivienda", color: "#1565C0" },
                            health: { icon: "💊", label: "Salud", color: "#2E7D32" },
                            debt_payment: { icon: "💳", label: "Cuotas", color: "#4527A0" },
                            savings: { icon: "🏦", label: "Ahorro", color: "#00695C" },
                            insurance: { icon: "🛡️", label: "Seguros", color: "#37474F" },
                            transfer: { icon: "↔️", label: "Transferencia", color: "#5D4037" },
                            banking_fee: { icon: "🏛️", label: "Comisión", color: "#78909C" },
                            education: { icon: "📚", label: "Educación", color: "#1B5E20" },
                            income: { icon: "💰", label: "Ingreso", color: "#33691E" },
                            other: { icon: "📦", label: "Otros", color: "#6B7A8D" },
                          };
                          const cat = CAT_UI[catKey] ?? CAT_UI.other;
                          const bankName = bankBalances.accounts?.find(a => a.id === tx.bank_account_id)?.bankName;
                          const rawDate  = tx.date ?? tx.created_at ?? "";
                          const dateDisplay = rawDate
                            ? new Date(rawDate + (rawDate.length === 10 ? "T12:00:00" : "")).toLocaleDateString("es-CL", { day: "numeric", month: "short" })
                            : "";

                          return (
                            <div key={tx.id} className="sky-tx-row" style={{
                              display: "flex", alignItems: "center", gap: 12,
                              padding: "10px 18px",
                              borderBottom: `1px solid ${P.border}`,
                              transition: "background 0.1s",
                            }}>
                              {/* Icono de categoría */}
                              <div style={{
                                width: 34, height: 34, borderRadius: 9, flexShrink: 0,
                                background: `${cat.color}18`,
                                display: "flex", alignItems: "center", justifyContent: "center",
                                fontSize: 15,
                              }}>
                                {cat.icon}
                              </div>

                              {/* Descripción + meta info */}
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: 600, color: P.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                  {tx.description ?? tx.desc ?? cat.label}
                                </div>
                                <div style={{ fontSize: 11, color: P.text3, marginTop: 2, display: "flex", gap: 5, alignItems: "center", flexWrap: "nowrap" }}>
                                  <span style={{ background: `${cat.color}14`, color: cat.color, borderRadius: 4, padding: "1px 6px", fontWeight: 600, fontSize: 10, flexShrink: 0 }}>
                                    {cat.label}
                                  </span>
                                  <span style={{ flexShrink: 0 }}>{dateDisplay}</span>
                                  {bankName && <span style={{ flexShrink: 0, color: P.text3 }}>· {bankName}</span>}
                                </div>
                              </div>

                              {/* Monto */}
                              <div style={{ textAlign: "right", flexShrink: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: 700, color: isIncome ? P.green : P.red, fontVariantNumeric: "tabular-nums", ...$ }}>
                                  {isIncome ? "+" : "−"}{fmtK(Math.abs(tx.amount ?? 0))}
                                </div>
                                <button
                                  onClick={() => deleteTx(tx.id)}
                                  style={{ fontSize: 10, color: P.text3, background: "none", border: "none", cursor: "pointer", padding: 0, marginTop: 2 }}
                                >
                                  eliminar
                                </button>
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                </div>
              );
            })()}

            {/* ══════════════════════════════
                METAS
            ══════════════════════════════ */}
            {tab === "goals" && (
              <div style={{ padding: "24px 28px", animation: "fadeUp 0.22s ease" }}>
                <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 20, alignItems: "start" }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                      {[
                        [goals.length, "Total", "◎"],
                        [goals.filter(g => g.type === "principal").length, "Principales", "⭐"],
                        [goals.filter(g => (g.projection?.pct ?? 0) >= 100).length, "Logradas", "✓"],
                      ].map(([v, l, ic]) => (
                        <div key={l} style={{ background: P.surface, borderRadius: 12, padding: "14px 10px", border: `1px solid ${P.border}`, textAlign: "center" }}>
                          <div style={{ fontSize: 16, color: P.green, marginBottom: 4 }}>{ic}</div>
                          <div style={{ fontSize: 20, fontWeight: 800, color: P.text }}>{v}</div>
                          <div style={{ fontSize: 11, color: P.text3 }}>{l}</div>
                        </div>
                      ))}
                    </div>
                    <div style={{ background: P.surface, borderRadius: 14, padding: "18px 20px", border: `1px solid ${P.border}` }}>
                      {!showAddGoal ? (
                        <button onClick={() => setShowAddGoal(true)} style={{ width: "100%", padding: 14, borderRadius: 10, border: `2px dashed ${P.green}`, background: P.greenBg, color: P.green3, fontSize: 14, fontWeight: 700, cursor: "pointer" }}>
                          + Nueva meta financiera
                        </button>
                      ) : (
                        <>
                          <div style={{ fontSize: 13, fontWeight: 700, color: P.text, marginBottom: 12 }}>Nueva meta</div>
                          <AddGoalForm onAdd={createGoal} onCancel={() => setShowAddGoal(false)} disabled={goalLoading} />
                        </>
                      )}
                    </div>
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    {goals.length === 0 && !showAddGoal && (
                      <div style={{ background: P.surface, borderRadius: 14, padding: "48px 24px", border: `1px solid ${P.border}`, textAlign: "center" }}>
                        <div style={{ fontSize: 32, color: P.green, marginBottom: 10 }}>◎</div>
                        <div style={{ fontSize: 15, fontWeight: 700, color: P.text, marginBottom: 6 }}>Sin metas todavía</div>
                        <div style={{ fontSize: 13, color: P.text3 }}>Crea tu primera meta y Sky te dirá cuándo la alcanzarás</div>
                      </div>
                    )}
                    {goals.filter(g => g.type === "principal").length > 0 && (
                      <>
                        <div style={{ fontSize: 11, fontWeight: 700, color: P.text3, letterSpacing: "0.07em" }}>⭐ MISIONES PRINCIPALES</div>
                        {goals.filter(g => g.type === "principal").map(g => (
                          <GoalCard key={g.id} goal={g} onAddSavings={goal => setSavingsTarget(goal)} onDelete={removeGoal} />
                        ))}
                      </>
                    )}
                    {goals.filter(g => g.type === "secundaria").length > 0 && (
                      <>
                        <div style={{ fontSize: 11, fontWeight: 700, color: P.text3, letterSpacing: "0.07em", marginTop: 8 }}>◎ MISIONES SECUNDARIAS</div>
                        {goals.filter(g => g.type === "secundaria").map(g => (
                          <GoalCard key={g.id} goal={g} onAddSavings={goal => setSavingsTarget(goal)} onDelete={removeGoal} />
                        ))}
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* ══════════════════════════════
                DESAFÍOS
            ══════════════════════════════ */}
            {tab === "challenges" && (
              <div style={{ padding: "24px 28px", animation: "fadeUp 0.22s ease" }}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14, marginBottom: 20, maxWidth: 560 }}>
                  {[
                    [challenges.completed.length, "Completados", "✓"],
                    [`${points} pts`,              "Acumulados",  "⭐"],
                    [challenges.active.length,     "Activos",     "◆"],
                  ].map(([v, l, ic]) => (
                    <div key={l} className="sky-card" style={{ background: P.surface, borderRadius: 14, padding: "16px 18px", border: `1px solid ${P.border}`, textAlign: "center" }}>
                      <div style={{ fontSize: 18, color: P.green, marginBottom: 5 }}>{ic}</div>
                      <div style={{ fontSize: 22, fontWeight: 800, color: P.text }}>{v}</div>
                      <div style={{ fontSize: 12, color: P.text3, marginTop: 2 }}>{l}</div>
                    </div>
                  ))}
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
                  <div>
                    {challenges.active.length > 0 && (
                      <>
                        <div style={{ fontSize: 11, fontWeight: 700, color: P.text3, letterSpacing: "0.07em", marginBottom: 10 }}>EN PROGRESO</div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 20 }}>
                          {challenges.active.map(ch => (
                            <ChallengeCard key={ch.id} ch={ch} isActive prog={ch.progress} onActivate={activateCh} onComplete={completeCh} isDone={false} />
                          ))}
                        </div>
                      </>
                    )}
                    <div style={{ fontSize: 11, fontWeight: 700, color: P.text3, letterSpacing: "0.07em", marginBottom: 10 }}>DISPONIBLES</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      {challenges.available.map(ch => (
                        <ChallengeCard key={ch.id} ch={ch} isActive={false} onActivate={activateCh} onComplete={completeCh} isDone={false} />
                      ))}
                    </div>
                  </div>
                  <div>
                    {challenges.completed.length > 0 && (
                      <>
                        <div style={{ fontSize: 11, fontWeight: 700, color: P.text3, letterSpacing: "0.07em", marginBottom: 10 }}>COMPLETADOS</div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                          {challenges.completed.map(ch => (
                            <ChallengeCard key={ch.id} ch={ch} isActive={false} onActivate={() => {}} onComplete={() => {}} isDone />
                          ))}
                        </div>
                      </>
                    )}
                    {allBadges.length > 0 && (
                      <div style={{ background: P.surface, borderRadius: 14, padding: "16px 18px", border: `1px solid ${P.border}`, marginTop: challenges.completed.length > 0 ? 16 : 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: P.text, marginBottom: 12 }}>Badges</div>
                        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                          {allBadges.map(b => <BadgeItem key={b.id} badge={b} earned={b.earned} />)}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* ══════════════════════════════
                SIMULAR
            ══════════════════════════════ */}
            {tab === "simulate" && (
              <div style={{ padding: "24px 28px", animation: "fadeUp 0.22s ease" }}>
                <SimulationChart summary={summary} goals={goals} initialSimType={initialSimType} />
              </div>
            )}

            {/* ══════════════════════════════
                MR. MONEY (CHAT)
            ══════════════════════════════ */}
            {tab === "chat" && (
              <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 58px)", animation: "fadeUp 0.22s ease" }}>

                {/* Mr. Money header */}
                <div style={{ padding: "10px 28px", background: P.surface, borderBottom: `1px solid ${P.border}`, display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
                  {/* Foto real de Mr. Money desde assets */}
                  <div style={{ width: 42, height: 42, borderRadius: "50%", overflow: "hidden", border: `2px solid ${P.greenBd}`, flexShrink: 0, background: P.navy }}>
                    <img
                      src="/assets/mr-money.png"
                      alt="Mr. Money"
                      style={{ width: "100%", height: "100%", objectFit: "cover" }}
                      onError={e => {
                        e.target.style.display = "none";
                        e.target.parentNode.innerHTML = `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center"><svg viewBox="0 0 24 24" width="20" height="20" fill="none"><circle cx="12" cy="8" r="4" stroke="#00C853" stroke-width="1.5"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" stroke="#00C853" stroke-width="1.5" stroke-linecap="round"/></svg></div>`;
                      }}
                    />
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: P.text }}>Mr. Money</div>
                    <div style={{ fontSize: 11, color: P.text3, marginTop: 1 }}>Asistente financiero</div>
                  </div>
                </div>

                {/* Quick starters */}
                <div style={{ padding: "10px 28px 0", display: "flex", gap: 8, overflowX: "auto", scrollbarWidth: "none", flexShrink: 0 }}>
                  {CHAT_STARTERS.map(s => (
                    <button key={s} onClick={() => send(s)} className="sky-starter" style={{ flexShrink: 0, padding: "7px 14px", borderRadius: 20, border: `1px solid ${P.border}`, background: P.surface, fontSize: 12, fontWeight: 500, color: P.text3, whiteSpace: "nowrap", cursor: "pointer", transition: "all 0.15s" }}>
                      {s}
                    </button>
                  ))}
                </div>

                {/* Messages */}
                <div style={{ flex: 1, overflowY: "auto", padding: "14px 28px", display: "flex", flexDirection: "column", gap: 10 }}>
                  {messages.map(m => (
                    <div key={m.id}>
                      <ChatBubble msg={m} />
                      {m.role === "bot" && m.id === messages[messages.length - 1]?.id && pendingProposals.length > 0 && (
                        <MrMoneyProposals proposals={pendingProposals} onAccept={handleProposalAccept} onReject={handleProposalReject} loadingId={proposalLoadingId} />
                      )}
                    </div>
                  ))}
                  {typing && <TypingDots />}
                  <div ref={bottomRef} />
                </div>

                {/* API error banner */}
                {apiError && (
                  <div style={{ padding: "8px 28px", background: "#FFF8E1", fontSize: 12, color: P.amber, textAlign: "center", flexShrink: 0 }}>
                    ⚠ Sin conexión al servidor — modo básico
                  </div>
                )}

                {/* Input */}
                <div style={{ padding: "10px 28px 18px", background: P.surface, borderTop: `1px solid ${P.border}`, display: "flex", gap: 10, alignItems: "center", flexShrink: 0 }}>
                  <div
                    style={{ flex: 1, display: "flex", alignItems: "center", background: P.bg, border: `1.5px solid ${P.border}`, borderRadius: 28, padding: "0 16px", gap: 8, transition: "border-color 0.15s" }}
                    onFocusCapture={e => { e.currentTarget.style.borderColor = P.green; }}
                    onBlurCapture={e => { e.currentTarget.style.borderColor = P.border; }}
                  >
                    <input
                      ref={inputRef}
                      value={input}
                      onChange={e => setInput(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
                      placeholder="Consulta a Mr. Money..."
                      style={{ flex: 1, padding: "13px 0", background: "transparent", border: "none", fontSize: 14, color: P.text, outline: "none" }}
                    />
                  </div>
                  <button
                    onClick={() => send(input)}
                    disabled={!input.trim() || typing}
                    style={{
                      width: 46, height: 46, borderRadius: "50%", border: "none",
                      background: input.trim() && !typing ? `linear-gradient(135deg,${P.green},${P.green2})` : P.border,
                      color: "#fff", fontSize: 20, display: "flex", alignItems: "center", justifyContent: "center",
                      flexShrink: 0, cursor: input.trim() && !typing ? "pointer" : "default",
                      transition: "all 0.2s",
                    }}
                  >↑</button>
                </div>
              </div>
            )}

          </div>
        </div>
      </div>

      {/* Modal de ahorro */}
      {savingsTarget && (
        <AddSavingsModal goal={savingsTarget} onConfirm={confirmAddSavings} onCancel={() => setSavingsTarget(null)} />
      )}
    </>
  );
}