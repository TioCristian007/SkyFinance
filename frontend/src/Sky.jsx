// ─────────────────────────────────────────────────────────────────────────────
// Sky.jsx — Componente raíz
//
// RESPONSABILIDAD: estado global de la app + coordinación entre páginas.
// NO contiene lógica de negocio. NO calcula nada financiero.
// NO arma prompts. NO llama a Anthropic.
//
// Flujo de datos:
//   Usuario interactúa → Sky.jsx llama a api.js → backend procesa →
//   Sky.jsx actualiza estado → componentes renderizan
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useRef, useEffect } from "react";
import { C } from "./data/colors.js";
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
import { MrMoneyProposals }              from "./components/MrMoneyProposal.jsx";

const CHAT_STARTERS = [
  "¿Cómo voy este mes?",
  "Quiero ahorrar para un viaje",
  "¿Qué desafío me recomiendas?",
  "¿Cuánto ahorro al año si reduzco Uber?",
  "Analiza mis gastos",
];

const TABS = [
  ["dashboard",  "📊", "Dashboard"],
  ["goals",      "🎯", "Metas"],
  ["challenges", "🏆", "Desafíos"],
  ["simulate",   "🔮", "Simular"],
  ["expenses",   "➕", "Gastos"],
  ["chat",       "💬", "Mr. Money"],
];

// ── Estado inicial del chat ───────────────────────────────────────────────────
const INITIAL_MESSAGE = {
  id: 0, role: "bot", time: nowTime(),
  text: "Hola. Soy Mr. Money, tu asesor financiero en Sky. 💼\n\nCargando tu resumen financiero...",
};

export default function Sky({ userId, userEmail }) {
  // Inyectar userId en api.js para que todas las llamadas lo incluyan
  // en el header x-user-id — sin DEV_USER_ID, sin configuración manual
  setUserId(userId);

  // ── Navegación ──────────────────────────────────────────────────────────────
  const [tab, setTab] = useState("dashboard");

  // ── Datos del servidor ──────────────────────────────────────────────────────
  // summary: { income, expenses, balance, spendingRate, savingsRate, categoryTotals, transactionCount }
  // profile: { user, points, level, levelProgress, earnedBadgeIds }
  // badges:  { allBadges, newBadges }
  const [summary,    setSummary]    = useState(null);
  const [profile,    setProfile]    = useState({ points: 0, level: 1, earnedBadgeIds: [] });
  const [allBadges,  setAllBadges]  = useState([]);
  const [txs,        setTxs]        = useState([]);
  const [challenges, setChallenges] = useState({ active: [], completed: [], available: [] });

  // ── UI local ────────────────────────────────────────────────────────────────
  const [loading,    setLoading]    = useState(true);
  const [txLoading,  setTxLoading]  = useState(false);
  const [messages,   setMsgs]       = useState([INITIAL_MESSAGE]);
  const [input,      setInput]      = useState("");
  const [typing,     setTyping]     = useState(false);
  const [apiError,   setApiErr]     = useState(false);
  const [toast,      setToast]      = useState(null);
  const [simMode,    setSimMode]    = useState("quick");
  const [activeSim,  setActiveSim]  = useState(null);
  const [simResult,  setSimResult]  = useState(null);
  const [simLabel,   setSimLabel]   = useState("");
  const [customAmt,  setCustomAmt]  = useState("");

  // ── Goals state ──────────────────────────────────────────────────────────────
  const [goals,          setGoals]          = useState([]);
  const [showAddGoal,    setShowAddGoal]    = useState(false);
  const [goalLoading,    setGoalLoading]    = useState(false);
  const [savingsTarget,  setSavingsTarget]  = useState(null);

  // ── Propuestas de Mr. Money ────────────────────────────────────────────────
  const [pendingProposals, setPendingProposals] = useState([]);
  const [proposalLoadingId, setProposalLoadingId] = useState(null);

  const bottomRef = useRef(null);
  const inputRef  = useRef(null);

  // ── Carga inicial — el frontend pide todo al backend ────────────────────────
  useEffect(() => {
    async function init() {
      try {
        const [summaryRes, txRes, chRes, goalsRes] = await Promise.all([
          api.getSummary(),
          api.getTransactions(),
          api.getChallenges(),
          api.getGoals(),
        ]);
        setSummary(summaryRes.summary);
        setProfile(summaryRes.profile);
        setAllBadges(summaryRes.badges.allBadges);
        setTxs(txRes.transactions);
        setChallenges(chRes);
        setGoals(goalsRes.goals);

        // Actualizar mensaje inicial con datos reales
        setMsgs([{
          ...INITIAL_MESSAGE,
          text: `Hola, ${summaryRes.profile.user.name}. Soy Mr. Money, tu asesor financiero en Sky. 💼\n\nCuentas con ${fmt(summaryRes.summary.balance)} disponibles este mes. Te recomiendo explorar los desafíos activos para optimizar tu ahorro.`,
        }]);
      } catch (e) {
        console.error("[Sky] init error:", e.message);
      } finally {
        setLoading(false);
      }
    }
    init();
  }, []);

  // ── Scroll automático en chat ────────────────────────────────────────────────
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
      console.error("[Sky] refreshSummary error:", e.message);
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
      if (result.proposals?.length) {
        setPendingProposals((prev) => [...prev, ...result.proposals]);
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
      showToast(`Gasto registrado ✓`);
      await refreshSummary();
    } catch (e) {
      showToast("Error al guardar el gasto", "red");
    } finally {
      setTxLoading(false);
    }
  };

  const deleteTx = async (id) => {
    try {
      await api.deleteTransaction(id);
      setTxs((prev) => prev.filter((t) => t.id !== id));
      await refreshSummary();
    } catch (e) {
      console.error("[Sky] deleteTx error:", e.message);
    }
  };

  // ── Desafíos ──────────────────────────────────────────────────────────────────
  const activateCh = async (ch) => {
    try {
      await api.activateChallenge(ch.id);
      showToast(`Desafío aceptado: ${ch.label}`);
      setChallenges(await api.getChallenges());
    } catch (e) {
      showToast("Error al activar el desafío", "red");
    }
  };

  const completeCh = async (ch) => {
    try {
      const { reply, pointsEarned } = await api.completeChallenge(ch.id);
      showToast(`🏆 +${pointsEarned} puntos!`, "gold");
      setChallenges(await api.getChallenges());
      await refreshSummary();
      setTab("chat"); setTyping(true);
      addBotMsg(reply);
    } catch (e) {
      console.error("[Sky] completeCh error:", e.message);
    } finally {
      setTyping(false);
    }
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
    } catch {
      showToast("Error al calcular la simulación", "red");
    }
  };

  // ── Metas financieras ─────────────────────────────────────────────────────────
  const createGoal = async (goalData) => {
    setGoalLoading(true);
    try {
      const { goal } = await api.addGoal(goalData);
      setGoals((prev) => [goal, ...prev]);
      setShowAddGoal(false);
      showToast(`Meta creada: ${goal.title}`);
    } catch (e) {
      showToast("Error al crear la meta", "red");
    } finally {
      setGoalLoading(false);
    }
  };

  // ── Handlers de propuestas de Mr. Money ────────────────────────────────────
  const handleProposalAccept = async (proposal) => {
    const pid = proposal.id || proposal.type;
    setProposalLoadingId(pid);
    try {
      const { type, input } = proposal;

      if (type === "propose_goal") {
        await createGoal({
          title:        input.title,
          targetAmount: input.target_amount,
          deadline:     input.deadline || null,
        });
        addBotMsg(`✅ Meta "${input.title}" creada. Buen inicio.`);
      }

      if (type === "propose_challenge") {
        await api.activateChallenge(input.challenge_id);
        showToast(`Desafío activado ✓`);
        setChallenges(await api.getChallenges());
        addBotMsg(`🏆 Desafío activado. A por ello.`);
      }

      if (type === "propose_goal_contribution") {
        const goal = goals.find((g) => g.id === input.goal_id);
        if (goal) {
          const newAmount = (goal.saved_amount || 0) + input.amount;
          await confirmAddSavings(input.goal_id, newAmount);
          addBotMsg(`💰 Aporte de ${new Intl.NumberFormat("es-CL",{style:"currency",currency:"CLP",maximumFractionDigits:0}).format(input.amount)} registrado en "${input.goal_title}".`);
        }
      }

      setPendingProposals((prev) => prev.filter((p) => (p.id || p.type) !== pid));
    } catch (e) {
      showToast("Error al ejecutar la acción", "red");
      console.error("[proposal] accept error:", e.message);
    } finally {
      setProposalLoadingId(null);
    }
  };

  const handleProposalReject = (proposal) => {
    const pid = proposal.id || proposal.type;
    setPendingProposals((prev) => prev.filter((p) => (p.id || p.type) !== pid));
    addBotMsg("Entendido, lo dejo para después. ¿En qué más te ayudo?");
  };

  const confirmAddSavings = async (goalId, newSavedAmount) => {
    try {
      const { goal } = await api.updateGoalSaved(goalId, newSavedAmount);
      setGoals((prev) => prev.map((g) => g.id === goalId ? goal : g));
      setSavingsTarget(null);
      if (goal.projection.pct >= 100) showToast("🎉 ¡Meta alcanzada!", "gold");
      else showToast("Ahorro actualizado ✓");
    } catch (e) {
      showToast("Error al actualizar", "red");
    }
  };

  const removeGoal = async (id) => {
    try {
      await api.deleteGoal(id);
      setGoals((prev) => prev.filter((g) => g.id !== id));
      showToast("Meta eliminada");
    } catch (e) {
      showToast("Error al eliminar", "red");
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={{ minHeight: "100vh", background: C.bg, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ fontSize: 14, color: C.textSecondary }}>Cargando Sky...</div>
      </div>
    );
  }

  const income      = summary?.income      ?? 0;
  const expenses    = summary?.expenses    ?? 0;
  const balance     = summary?.balance     ?? 0;
  const savingsRate = summary?.savingsRate ?? 0;
  const catTotals   = summary?.categoryTotals ?? {};
  const points      = profile?.points      ?? 0;

  return (
    <>
      <style>{`
        @keyframes bounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-5px)}}
        @keyframes fadeUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
        @keyframes slideDown{from{opacity:0;transform:translateY(-12px)}to{opacity:1;transform:translateY(0)}}
        *{box-sizing:border-box;margin:0;padding:0}
        ::-webkit-scrollbar{width:3px}::-webkit-scrollbar-thumb{background:#ddd;border-radius:4px}
        button{cursor:pointer;font-family:inherit}input{font-family:inherit}
        input[type=number]::-webkit-inner-spin-button{-webkit-appearance:none}
      `}</style>

      {/* Toast */}
      {toast && (
        <div style={{
          position: "fixed", top: 18, left: "50%", transform: "translateX(-50%)", zIndex: 9999,
          padding: "10px 20px", borderRadius: 24, color: C.white, fontSize: 13, fontWeight: 700,
          boxShadow: "0 8px 24px rgba(0,0,0,0.2)", animation: "slideDown 0.3s ease", whiteSpace: "nowrap",
          background: toast.type === "gold"
            ? `linear-gradient(135deg,${C.gold},#E65100)`
            : `linear-gradient(135deg,${C.green},${C.greenDark})`,
        }}>
          {toast.msg}
        </div>
      )}

      <div style={{ minHeight: "100vh", background: C.bg, display: "flex", alignItems: "center", justifyContent: "center", padding: 12, fontFamily: "-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif" }}>
        <div style={{ width: "100%", maxWidth: 420, minHeight: "92vh", maxHeight: 900, display: "flex", flexDirection: "column", borderRadius: 28, overflow: "hidden", boxShadow: "0 20px 60px rgba(0,0,0,0.13)", background: C.bg }}>

          {/* ── Header ── */}
          <div style={{ background: C.navy, padding: "16px 20px 14px", flexShrink: 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 11, color: "rgba(255,255,255,0.4)", letterSpacing: "0.08em", fontWeight: 600 }}>FINANZAS DE</div>
                <div style={{ fontSize: 17, fontWeight: 700, color: C.white }}>{profile?.user?.name ?? "—"}</div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ fontSize: 11, color: C.gold, fontWeight: 700, background: "rgba(249,168,37,0.15)", padding: "4px 10px", borderRadius: 20 }}>
                  ⭐ {points} pts
                </div>
                <div style={{ background: C.green, color: C.white, fontWeight: 800, fontSize: 13, padding: "5px 12px", borderRadius: 20 }}>
                  sky
                </div>
                <button
                  onClick={async () => { try { await signOut(); } catch(e) { console.error(e); } }}
                  title="Cerrar sesión"
                  style={{
                    background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.15)",
                    borderRadius: 20, color: "rgba(255,255,255,0.6)", fontSize: 12,
                    padding: "5px 10px", cursor: "pointer", fontFamily: "inherit",
                  }}
                >
                  Salir
                </button>
              </div>
            </div>

            <div style={{ background: "rgba(255,255,255,0.06)", borderRadius: 16, padding: "12px 16px", border: "1px solid rgba(255,255,255,0.08)", marginBottom: 10 }}>
              <div style={{ fontSize: 11, color: "rgba(255,255,255,0.45)", fontWeight: 600, letterSpacing: "0.06em", marginBottom: 4 }}>DISPONIBLE ESTE MES</div>
              <div style={{ fontSize: 24, fontWeight: 800, color: balance < 0 ? "#FF6B6B" : C.white, letterSpacing: "-1px", marginBottom: 8 }}>
                {fmt(balance)}
              </div>
              <div style={{ display: "flex", gap: 16 }}>
                {[
                  ["INGRESOS", fmtK(income),    C.green],
                  ["GASTADO",  fmtK(expenses),  "#FF6B6B"],
                  ["TX",       txs.length,       "#FFD166"],
                  ["AHORRO",   `${savingsRate}%`, savingsRate >= 20 ? C.green : C.amber],
                ].map(([l, v, col]) => (
                  <div key={l}>
                    <div style={{ fontSize: 10, color: "rgba(255,255,255,0.4)", fontWeight: 600 }}>{l}</div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: col }}>{v}</div>
                  </div>
                ))}
              </div>
            </div>
            <XPBar points={points} />
          </div>

          {/* ── Tabs ── */}
          <div style={{ display: "flex", background: C.white, borderBottom: `1px solid ${C.border}`, flexShrink: 0, overflowX: "auto", scrollbarWidth: "none" }}>
            {TABS.map(([key, icon, label]) => (
              <button key={key} onClick={() => setTab(key)} style={{
                flexShrink: 0, flex: 1, minWidth: 60, padding: "9px 2px", border: "none",
                background: "transparent", fontSize: 10,
                fontWeight: tab === key ? 700 : 500,
                color: tab === key ? C.green : C.textSecondary,
                borderBottom: tab === key ? `2.5px solid ${C.green}` : "2.5px solid transparent",
                transition: "all 0.2s",
              }}>
                <div style={{ fontSize: 14 }}>{icon}</div>
                <div>{label}</div>
                {key === "challenges" && challenges.active.length > 0 && (
                  <div style={{ width: 14, height: 14, borderRadius: "50%", background: C.green, color: C.white, fontSize: 8, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", margin: "2px auto 0" }}>
                    {challenges.active.length}
                  </div>
                )}
              </button>
            ))}
          </div>

          {/* ── Contenido ── */}
          <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column" }}>

            {/* DASHBOARD */}
            {tab === "dashboard" && (
              <div style={{ padding: "14px 14px 24px", display: "flex", flexDirection: "column", gap: 12 }}>
                {/* Donut + barra de progreso */}
                <div style={{ background: C.white, borderRadius: 18, padding: "14px 16px", border: `1px solid ${C.border}`, display: "flex", alignItems: "center", gap: 14 }}>
                  <DonutChart spent={expenses} total={income} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary, marginBottom: 4 }}>Presupuesto mensual</div>
                    <div style={{ fontSize: 12, color: C.textSecondary, marginBottom: 8 }}>
                      Usado {summary?.spendingRate ?? 0}% · {txs.length} transacciones
                    </div>
                    <div style={{ height: 7, background: C.border, borderRadius: 99 }}>
                      <div style={{ height: "100%", width: `${Math.min(summary?.spendingRate ?? 0, 100)}%`, background: (summary?.spendingRate ?? 0) > 85 ? C.red : C.green, borderRadius: 99, transition: "width 0.6s ease" }} />
                    </div>
                  </div>
                </div>

                {/* Desafíos activos (resumen) */}
                {challenges.active.length > 0 && (
                  <div style={{ background: C.white, borderRadius: 16, padding: "14px 16px", border: `1.5px solid ${C.greenLight}` }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary, marginBottom: 10 }}>🏆 Desafíos activos</div>
                    {challenges.active.map((ch) => (
                      <div key={ch.id} style={{ marginBottom: 10 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                          <span style={{ fontSize: 12, color: C.textPrimary, fontWeight: 600 }}>{ch.icon} {ch.label}</span>
                          <span style={{ fontSize: 12, fontWeight: 700, color: ch.progress?.done ? C.gold : C.green }}>{ch.progress?.pct ?? 0}%</span>
                        </div>
                        <div style={{ height: 6, background: C.border, borderRadius: 99, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${ch.progress?.pct ?? 0}%`, background: ch.progress?.done ? C.gold : C.green, borderRadius: 99, transition: "width 0.6s ease" }} />
                        </div>
                        {ch.progress?.done && (
                          <button onClick={() => completeCh(ch)} style={{ marginTop: 6, width: "100%", padding: "7px", borderRadius: 10, border: "none", cursor: "pointer", background: `linear-gradient(135deg,${C.gold},#E65100)`, color: C.white, fontSize: 12, fontWeight: 700, fontFamily: "inherit" }}>
                            🏆 Reclamar {ch.pts} pts
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* Categorías */}
                <div style={{ background: C.white, borderRadius: 16, padding: "14px 16px", border: `1px solid ${C.border}` }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary, marginBottom: 12 }}>Por categoría</div>
                  <CatBars categoryTotals={catTotals} />
                </div>

                {/* Badges */}
                <div style={{ background: C.white, borderRadius: 16, padding: "14px 16px", border: `1px solid ${C.border}` }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary, marginBottom: 12 }}>Colección de badges</div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    {allBadges.map((b) => <BadgeItem key={b.id} badge={b} earned={b.earned} />)}
                  </div>
                </div>

                {/* Accesos rápidos */}
                <div style={{ display: "flex", gap: 10 }}>
                  <button onClick={() => setTab("goals")}      style={{ flex: 1, padding: "12px", borderRadius: 14, border: `1.5px solid ${C.green}`, background: C.greenLight, color: C.greenDark, fontSize: 13, fontWeight: 700 }}>🎯 Metas</button>
                  <button onClick={() => setTab("challenges")} style={{ flex: 1, padding: "12px", borderRadius: 14, border: `1.5px solid ${C.gold}`, background: C.goldLight, color: "#7A5000", fontSize: 13, fontWeight: 700 }}>🏆 Desafíos</button>
                  <button onClick={() => setTab("simulate")}   style={{ flex: 1, padding: "12px", borderRadius: 14, border: "1.5px solid #7B1FA2", background: "#F3E5F5", color: "#7B1FA2", fontSize: 13, fontWeight: 700 }}>🔮 Simular</button>
                </div>
              </div>
            )}

            {/* METAS */}
            {tab === "goals" && (
              <div style={{ padding: "14px 14px 28px", display: "flex", flexDirection: "column", gap: 12 }}>

                {/* Resumen de metas */}
                <div style={{ display: "flex", gap: 10 }}>
                  {[
                    [goals.length,                                             "Total",       "🎯"],
                    [goals.filter(g => g.type === "principal").length,         "Principales", "⭐"],
                    [goals.filter(g => g.projection?.pct >= 100).length,       "Completadas", "✅"],
                  ].map(([v, l, ic]) => (
                    <div key={l} style={{ flex: 1, background: C.white, borderRadius: 14, padding: "12px", border: `1px solid ${C.border}`, textAlign: "center" }}>
                      <div style={{ fontSize: 18, marginBottom: 4 }}>{ic}</div>
                      <div style={{ fontSize: 16, fontWeight: 800, color: C.textPrimary }}>{v}</div>
                      <div style={{ fontSize: 11, color: C.textMuted }}>{l}</div>
                    </div>
                  ))}
                </div>

                {/* Botón nueva meta o formulario */}
                {!showAddGoal ? (
                  <button
                    onClick={() => setShowAddGoal(true)}
                    style={{
                      width: "100%", padding: "12px", borderRadius: 14,
                      border: `1.5px dashed ${C.green}`, background: C.greenLight,
                      color: C.greenDark, fontSize: 13, fontWeight: 700,
                      cursor: "pointer", fontFamily: "inherit",
                    }}
                  >
                    + Nueva meta
                  </button>
                ) : (
                  <AddGoalForm
                    onAdd={createGoal}
                    onCancel={() => setShowAddGoal(false)}
                    disabled={goalLoading}
                  />
                )}

                {/* Misiones principales */}
                {goals.filter(g => g.type === "principal").length > 0 && (
                  <>
                    <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>
                      ⭐ Misiones principales
                    </div>
                    {goals
                      .filter(g => g.type === "principal")
                      .map(g => (
                        <GoalCard
                          key={g.id}
                          goal={g}
                          onAddSavings={(goal) => setSavingsTarget(goal)}
                          onDelete={removeGoal}
                        />
                      ))
                    }
                  </>
                )}

                {/* Misiones secundarias */}
                {goals.filter(g => g.type === "secundaria").length > 0 && (
                  <>
                    <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>
                      🎯 Misiones secundarias
                    </div>
                    {goals
                      .filter(g => g.type === "secundaria")
                      .map(g => (
                        <GoalCard
                          key={g.id}
                          goal={g}
                          onAddSavings={(goal) => setSavingsTarget(goal)}
                          onDelete={removeGoal}
                        />
                      ))
                    }
                  </>
                )}

                {/* Estado vacío */}
                {goals.length === 0 && !showAddGoal && (
                  <div style={{
                    textAlign: "center", padding: "40px 20px",
                    background: C.white, borderRadius: 16, border: `1px solid ${C.border}`,
                  }}>
                    <div style={{ fontSize: 36, marginBottom: 12 }}>🎯</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: C.textPrimary, marginBottom: 6 }}>
                      Sin metas todavía
                    </div>
                    <div style={{ fontSize: 13, color: C.textSecondary }}>
                      Crea tu primera misión y Sky te dirá cuándo la alcanzarás al ritmo que vas.
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* CHALLENGES */}
            {tab === "challenges" && (
              <div style={{ padding: "14px 14px 28px", display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ display: "flex", gap: 10 }}>
                  {[
                    [challenges.completed.length, "Completados", "🎯"],
                    [`${points} pts`, "acumulados",  "⭐"],
                    [challenges.active.length,    "Activos",     "🔥"],
                  ].map(([v, l, ic]) => (
                    <div key={l} style={{ flex: 1, background: C.white, borderRadius: 14, padding: "12px", border: `1px solid ${C.border}`, textAlign: "center" }}>
                      <div style={{ fontSize: 18, marginBottom: 4 }}>{ic}</div>
                      <div style={{ fontSize: 16, fontWeight: 800, color: C.textPrimary }}>{v}</div>
                      <div style={{ fontSize: 11, color: C.textMuted }}>{l}</div>
                    </div>
                  ))}
                </div>

                {challenges.active.length > 0 && (
                  <>
                    <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>En progreso</div>
                    {challenges.active.map((ch) => (
                      <ChallengeCard key={ch.id} ch={ch} isActive prog={ch.progress} onActivate={activateCh} onComplete={completeCh} isDone={false} />
                    ))}
                  </>
                )}

                <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>Disponibles</div>
                {challenges.available.map((ch) => (
                  <ChallengeCard key={ch.id} ch={ch} isActive={false} onActivate={activateCh} onComplete={completeCh} isDone={false} />
                ))}

                {challenges.completed.length > 0 && (
                  <>
                    <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>Completados</div>
                    {challenges.completed.map((ch) => (
                      <ChallengeCard key={ch.id} ch={ch} isActive={false} onActivate={() => {}} onComplete={() => {}} isDone />
                    ))}
                  </>
                )}
              </div>
            )}

            {/* SIMULATE */}
            {tab === "simulate" && (
              <div style={{ padding: "14px 14px 28px", display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ display: "flex", background: C.white, borderRadius: 14, padding: 4, border: `1px solid ${C.border}` }}>
                  {[["quick", "⚡ Rápido"], ["custom", "✏️ Personalizado"]].map(([m, l]) => (
                    <button key={m} onClick={() => { setSimMode(m); setSimResult(null); setActiveSim(null); }} style={{
                      flex: 1, padding: "9px 0", borderRadius: 11, border: "none", fontSize: 12, fontWeight: 600, fontFamily: "inherit",
                      background: simMode === m ? C.navy : "transparent",
                      color: simMode === m ? C.white : C.textSecondary,
                      transition: "all 0.2s",
                    }}>
                      {l}
                    </button>
                  ))}
                </div>

                {simMode === "quick" && (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    {QUICK_SIMS.map((sim) => (
                      <button key={sim.id} onClick={() => runSim(sim.id)} style={{
                        padding: "14px 12px", borderRadius: 16, textAlign: "left", fontFamily: "inherit",
                        border: `1.5px solid ${activeSim === sim.id ? C.green : C.border}`,
                        background: activeSim === sim.id ? C.greenLight : C.white,
                        transition: "all 0.2s",
                      }}>
                        <div style={{ fontSize: 22, marginBottom: 6 }}>{sim.icon}</div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: activeSim === sim.id ? C.greenDark : C.textPrimary }}>
                          {sim.label}
                        </div>
                      </button>
                    ))}
                  </div>
                )}

                {simMode === "custom" && (
                  <div style={{ background: C.white, borderRadius: 18, padding: "16px 18px", border: `1px solid ${C.border}` }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: C.textPrimary, marginBottom: 4 }}>¿Cuánto quieres ahorrar extra?</div>
                    <div style={{ fontSize: 12, color: C.textSecondary, marginBottom: 14 }}>Mr. Money analizará si es realista para ti</div>
                    <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                      <input
                        value={customAmt} onChange={(e) => setCustomAmt(e.target.value)}
                        type="number" placeholder="Ej: 50000"
                        style={{ flex: 1, padding: "11px 14px", borderRadius: 12, border: `1.5px solid ${C.border}`, background: C.bg, fontSize: 14, color: C.textPrimary, outline: "none", fontFamily: "inherit" }}
                        onFocus={(e) => (e.target.style.borderColor = C.green)}
                        onBlur={(e)  => (e.target.style.borderColor = C.border)}
                        onKeyDown={(e) => e.key === "Enter" && runSim("custom", parseInt(customAmt))}
                      />
                      <button onClick={() => runSim("custom", parseInt(customAmt))} disabled={!customAmt} style={{
                        padding: "11px 18px", borderRadius: 12, border: "none", fontWeight: 700, fontSize: 13, fontFamily: "inherit",
                        background: customAmt ? `linear-gradient(135deg,${C.green},${C.greenDark})` : C.border, color: C.white,
                      }}>Ver →</button>
                    </div>
                    <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                      {[20000, 50000, 100000, 200000].map((n) => (
                        <button key={n} onClick={() => setCustomAmt(String(n))} style={{
                          padding: "5px 12px", borderRadius: 20, border: `1px solid ${C.border}`, fontFamily: "inherit",
                          background: customAmt == n ? C.greenLight : C.white,
                          color:      customAmt == n ? C.greenDark  : C.textSecondary,
                          fontSize: 12, fontWeight: 500,
                        }}>
                          {fmtK(n)}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {simResult && (
                  <div style={{ background: C.white, borderRadius: 18, border: `1.5px solid ${C.green}`, padding: "16px 18px", animation: "fadeUp 0.3s ease" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
                      <div style={{ width: 36, height: 36, borderRadius: 12, background: C.greenLight, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>💡</div>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>{simLabel}</div>
                      </div>
                    </div>
                    <div style={{ background: C.greenLight, borderRadius: 14, padding: "12px", marginBottom: 12, textAlign: "center" }}>
                      <div style={{ fontSize: 11, color: C.greenDark, fontWeight: 600, marginBottom: 4 }}>AHORRAS AL MES</div>
                      <div style={{ fontSize: 26, fontWeight: 800, color: C.greenDark }}>{fmtK(simResult.monthlySaving)}</div>
                    </div>
                    {[[3, simResult.months3], [6, simResult.months6], [12, simResult.months12]].map(([m, v]) => (
                      <div key={m} style={{ marginBottom: 8 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                          <span style={{ fontSize: 12, color: C.textSecondary }}>{m} meses</span>
                          <span style={{ fontSize: 13, fontWeight: 700, color: C.green }}>{fmtK(v)}</span>
                        </div>
                        <div style={{ height: 7, background: C.border, borderRadius: 99, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${(v / simResult.months12) * 100}%`, background: C.green, borderRadius: 99 }} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* EXPENSES */}
            {tab === "expenses" && (
              <div style={{ padding: "14px 14px 24px", display: "flex", flexDirection: "column", gap: 12 }}>
                <AddTxForm onAdd={addTx} disabled={txLoading} />
                <div style={{ background: C.white, borderRadius: 18, padding: "14px 16px", border: `1px solid ${C.border}` }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>Transacciones</div>
                    <div style={{ fontSize: 12, color: C.textMuted }}>{txs.length} registros</div>
                  </div>
                  {txs.length === 0
                    ? <div style={{ fontSize: 13, color: C.textMuted, textAlign: "center", padding: "20px 0" }}>Sin transacciones. ¡Agrega la primera!</div>
                    : txs.map((tx) => <TxItem key={tx.id} tx={tx} onDelete={deleteTx} />)
                  }
                </div>
              </div>
            )}

            {/* CHAT */}
            {tab === "chat" && (
              <>
                <div style={{ flex: 1, overflowY: "auto", padding: "14px 14px 8px", display: "flex", flexDirection: "column", gap: 6 }}>
                  {messages.map((m) => (
                    <div key={m.id}>
                      <ChatBubble msg={m} />
                      {/* Mostrar propuestas adjuntas al último mensaje del bot */}
                      {m.role === "bot" && m.id === messages[messages.length - 1]?.id && pendingProposals.length > 0 && (
                        <MrMoneyProposals
                          proposals={pendingProposals}
                          onAccept={handleProposalAccept}
                          onReject={handleProposalReject}
                          loadingId={proposalLoadingId}
                        />
                      )}
                    </div>
                  ))}
                  {typing && (
                    <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
                      <div style={{ width: 32, height: 32, borderRadius: "50%", background: `linear-gradient(135deg,${C.green},${C.greenDark})`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, flexShrink: 0 }}>💸</div>
                      <TypingDots />
                    </div>
                  )}
                  <div ref={bottomRef} />
                </div>

                {apiError && (
                  <div style={{ padding: "5px 14px", background: "#FFF3E0", fontSize: 12, color: C.amber, textAlign: "center", flexShrink: 0 }}>
                    ⚠ Sin conexión al servidor — modo básico
                  </div>
                )}

                <div style={{ padding: "7px 12px 4px", display: "flex", gap: 7, overflowX: "auto", scrollbarWidth: "none", background: C.white, borderTop: `1px solid ${C.border}`, flexShrink: 0 }}>
                  {CHAT_STARTERS.map((s) => (
                    <button key={s} onClick={() => send(s)} style={{ flexShrink: 0, padding: "6px 12px", borderRadius: 20, border: `1px solid ${C.border}`, background: C.white, fontSize: 12, fontWeight: 500, color: C.textSecondary, whiteSpace: "nowrap" }}>
                      {s}
                    </button>
                  ))}
                </div>

                <div style={{ padding: "10px 12px 14px", background: C.white, display: "flex", gap: 9, alignItems: "center", flexShrink: 0 }}>
                  <input
                    ref={inputRef} value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
                    placeholder="Consulte a Mr. Money..."
                    style={{ flex: 1, padding: "11px 16px", borderRadius: 24, border: `1.5px solid ${C.border}`, background: C.bg, fontSize: 13.5, color: C.textPrimary, outline: "none" }}
                    onFocus={(e) => (e.target.style.borderColor = C.green)}
                    onBlur={(e)  => (e.target.style.borderColor = C.border)}
                  />
                  <button
                    onClick={() => send(input)} disabled={!input.trim() || typing}
                    style={{
                      width: 42, height: 42, borderRadius: "50%", border: "none", flexShrink: 0,
                      background: input.trim() && !typing ? `linear-gradient(135deg,${C.green},${C.greenDark})` : C.border,
                      color: C.white, fontSize: 18, display: "flex", alignItems: "center", justifyContent: "center", transition: "all 0.2s",
                    }}
                  >
                    ↑
                  </button>
                </div>
              </>
            )}

          </div>
        </div>
      </div>

      {/* Modal agregar ahorro a meta */}
      {savingsTarget && (
        <AddSavingsModal
          goal={savingsTarget}
          onConfirm={confirmAddSavings}
          onCancel={() => setSavingsTarget(null)}
        />
      )}
    </>
  );
}