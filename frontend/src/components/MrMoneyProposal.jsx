// ─────────────────────────────────────────────────────────────────────────────
// components/MrMoneyProposal.jsx
// Propuestas de Mr. Money — el usuario aprueba o rechaza cada acción.
// ─────────────────────────────────────────────────────────────────────────────

import { C } from "../data/colors.js";

const CHALLENGE_META = {
  no_uber:     { label: "Sin Uber 7 días",        icon: "🚗", pts: 150 },
  food_budget: { label: "Comida bajo $80K",        icon: "🍔", pts: 200 },
  no_entert:   { label: "Sin entretención 5 días", icon: "🎮", pts: 100 },
  save_60k:    { label: "Ahorra $60K este mes",    icon: "💰", pts: 250 },
  no_subs:     { label: "Cancela 1 suscripción",   icon: "📺", pts: 80  },
  daily_track: { label: "Registra 5 gastos",       icon: "📝", pts: 120 },
};

const fmt = (n) =>
  new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n);

const card = {
  background: C.white,
  border:     `1.5px solid ${C.green}`,
  borderRadius: 14,
  padding: "14px 16px",
  marginTop: 8,
  animation: "fadeUp 0.25s ease",
};

const label = (color = C.green) => ({
  fontSize: 11, fontWeight: 700, color,
  letterSpacing: "0.06em", textTransform: "uppercase",
  marginBottom: 6, display: "flex", alignItems: "center", gap: 4,
});

const title = {
  fontSize: 14, fontWeight: 700, color: C.textPrimary, marginBottom: 4,
};

const reason = {
  fontSize: 12.5, color: C.textSecondary, lineHeight: 1.5, marginBottom: 12,
};

const btnRow = { display: "flex", gap: 8 };

const btnPrimary = (loading) => ({
  flex: 1, padding: "8px 0", borderRadius: 10, border: "none",
  background: `linear-gradient(135deg,${C.green},${C.greenDark})`,
  color: C.white, fontSize: 13, fontWeight: 700,
  cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.7 : 1,
});

const btnSecondary = {
  padding: "8px 14px", borderRadius: 10,
  border: `1px solid ${C.border}`, background: "transparent",
  color: C.textSecondary, fontSize: 13, cursor: "pointer",
};

const btnDanger = (loading) => ({
  flex: 1, padding: "8px 0", borderRadius: 10, border: "none",
  background: loading ? C.border : C.red,
  color: C.white, fontSize: 13, fontWeight: 700,
  cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.7 : 1,
});

// ── Cards individuales ────────────────────────────────────────────────────────

function GoalProposalCard({ input, onAccept, onReject, loading }) {
  return (
    <div style={card}>
      <div style={label()}>✨ Propuesta de meta</div>
      <div style={title}>{input.title}</div>
      <div style={{ fontSize: 13, color: C.green, fontWeight: 700, marginBottom: 4 }}>
        {fmt(input.target_amount)}
        {input.deadline && (
          <span style={{ fontSize: 11, fontWeight: 400, color: C.textSecondary, marginLeft: 8 }}>
            → {new Date(input.deadline).toLocaleDateString("es-CL", { month: "short", year: "numeric" })}
          </span>
        )}
      </div>
      <div style={reason}>{input.reasoning}</div>
      <div style={btnRow}>
        <button style={btnPrimary(loading)} onClick={onAccept} disabled={loading}>
          {loading ? "Creando..." : "Crear esta meta"}
        </button>
        <button style={btnSecondary} onClick={onReject}>No, gracias</button>
      </div>
    </div>
  );
}

function DeleteGoalCard({ input, onAccept, onReject, loading }) {
  return (
    <div style={{ ...card, border: `1.5px solid ${C.red}` }}>
      <div style={label(C.red)}>🗑️ Eliminar meta</div>
      <div style={title}>{input.goal_title}</div>
      <div style={reason}>{input.reasoning}</div>
      <div style={btnRow}>
        <button style={btnDanger(loading)} onClick={onAccept} disabled={loading}>
          {loading ? "Eliminando..." : "Sí, eliminar"}
        </button>
        <button style={btnSecondary} onClick={onReject}>Cancelar</button>
      </div>
    </div>
  );
}

function ChallengeProposalCard({ input, onAccept, onReject, loading }) {
  const ch = CHALLENGE_META[input.challenge_id] || { label: input.challenge_id, icon: "🎯", pts: 0 };
  return (
    <div style={card}>
      <div style={label()}>🏆 Desafío recomendado</div>
      <div style={title}>{ch.icon} {ch.label}</div>
      <div style={{ fontSize: 11, color: C.gold || "#F59E0B", fontWeight: 700, marginBottom: 4 }}>
        +{ch.pts} puntos al completar
      </div>
      <div style={reason}>{input.reasoning}</div>
      <div style={btnRow}>
        <button style={btnPrimary(loading)} onClick={onAccept} disabled={loading}>
          {loading ? "Activando..." : "Aceptar desafío"}
        </button>
        <button style={btnSecondary} onClick={onReject}>No ahora</button>
      </div>
    </div>
  );
}

function ContributionCard({ input, onAccept, onReject, loading }) {
  return (
    <div style={card}>
      <div style={label()}>💰 Aporte a meta</div>
      <div style={title}>{input.goal_title}</div>
      <div style={{ fontSize: 13, color: C.green, fontWeight: 700, marginBottom: 4 }}>
        + {fmt(input.amount)}
      </div>
      <div style={reason}>{input.reasoning}</div>
      <div style={btnRow}>
        <button style={btnPrimary(loading)} onClick={onAccept} disabled={loading}>
          {loading ? "Guardando..." : "Confirmar aporte"}
        </button>
        <button style={btnSecondary} onClick={onReject}>No ahora</button>
      </div>
    </div>
  );
}

// ── Componente principal ──────────────────────────────────────────────────────
export function MrMoneyProposals({ proposals, onAccept, onReject, loadingId }) {
  if (!proposals?.length) return null;

  return (
    <div style={{ marginTop: 4 }}>
      {proposals.map((p) => {
        const pid     = p.id || p.type;
        const loading = loadingId === pid;
        const accept  = () => onAccept(p);
        const reject  = () => onReject(p);

        if (p.type === "propose_goal")             return <GoalProposalCard   key={pid} input={p.input} onAccept={accept} onReject={reject} loading={loading} />;
        if (p.type === "propose_delete_goal")       return <DeleteGoalCard     key={pid} input={p.input} onAccept={accept} onReject={reject} loading={loading} />;
        if (p.type === "propose_challenge")         return <ChallengeProposalCard key={pid} input={p.input} onAccept={accept} onReject={reject} loading={loading} />;
        if (p.type === "propose_goal_contribution") return <ContributionCard   key={pid} input={p.input} onAccept={accept} onReject={reject} loading={loading} />;
        return null;
      })}
    </div>
  );
}