// ─────────────────────────────────────────────────────────────────────────────
// components/MrMoneyProposal.jsx
//
// Muestra las propuestas de Mr. Money al usuario para su aprobación.
// Principio: Mr. Money propone, el usuario decide.
// ─────────────────────────────────────────────────────────────────────────────

import { C } from "../data/colors.js";

const CHALLENGE_LABELS = {
  no_uber:     { label: "Sin Uber 7 días",        icon: "🚗", pts: 150 },
  food_budget: { label: "Comida bajo $80K",        icon: "🍔", pts: 200 },
  no_entert:   { label: "Sin entretención 5 días", icon: "🎮", pts: 100 },
  save_60k:    { label: "Ahorra $60K este mes",    icon: "💰", pts: 250 },
  no_subs:     { label: "Cancela 1 suscripción",   icon: "📺", pts: 80  },
  daily_track: { label: "Registra 5 gastos",       icon: "📝", pts: 120 },
};

const fmt = (n) =>
  new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n);

// ── Card individual de propuesta ──────────────────────────────────────────────
function ProposalCard({ proposal, onAccept, onReject, loading }) {
  const { type, input } = proposal;

  const cardStyle = {
    background: C.white,
    border:     `1.5px solid ${C.green}`,
    borderRadius: 14,
    padding: "14px 16px",
    marginTop: 8,
    animation: "fadeUp 0.25s ease",
  };

  const labelStyle = {
    fontSize: 11,
    fontWeight: 700,
    color: C.green,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    marginBottom: 6,
    display: "flex",
    alignItems: "center",
    gap: 4,
  };

  const titleStyle = {
    fontSize: 14,
    fontWeight: 700,
    color: C.textPrimary,
    marginBottom: 4,
  };

  const reasonStyle = {
    fontSize: 12.5,
    color: C.textSecondary,
    lineHeight: 1.5,
    marginBottom: 12,
  };

  const btnRow = {
    display: "flex",
    gap: 8,
  };

  const btnAccept = {
    flex: 1,
    padding: "8px 0",
    borderRadius: 10,
    border: "none",
    background: `linear-gradient(135deg,${C.green},${C.greenDark})`,
    color: C.white,
    fontSize: 13,
    fontWeight: 700,
    cursor: loading ? "not-allowed" : "pointer",
    opacity: loading ? 0.7 : 1,
  };

  const btnReject = {
    padding: "8px 14px",
    borderRadius: 10,
    border: `1px solid ${C.border}`,
    background: "transparent",
    color: C.textSecondary,
    fontSize: 13,
    cursor: "pointer",
  };

  if (type === "propose_goal") {
    return (
      <div style={cardStyle}>
        <div style={labelStyle}>✨ Propuesta de meta</div>
        <div style={titleStyle}>{input.title}</div>
        <div style={{ fontSize: 13, color: C.green, fontWeight: 700, marginBottom: 4 }}>
          {fmt(input.target_amount)}
          {input.deadline && (
            <span style={{ fontSize: 11, fontWeight: 400, color: C.textSecondary, marginLeft: 8 }}>
              → {new Date(input.deadline).toLocaleDateString("es-CL", { month: "short", year: "numeric" })}
            </span>
          )}
        </div>
        <div style={reasonStyle}>{input.reasoning}</div>
        <div style={btnRow}>
          <button style={btnAccept} onClick={() => onAccept(proposal)} disabled={loading}>
            {loading ? "Creando..." : "Crear esta meta"}
          </button>
          <button style={btnReject} onClick={() => onReject(proposal)}>No, gracias</button>
        </div>
      </div>
    );
  }

  if (type === "propose_challenge") {
    const ch = CHALLENGE_LABELS[input.challenge_id] || { label: input.challenge_id, icon: "🎯", pts: 0 };
    return (
      <div style={cardStyle}>
        <div style={labelStyle}>🏆 Desafío recomendado</div>
        <div style={titleStyle}>{ch.icon} {ch.label}</div>
        <div style={{ fontSize: 11, color: C.gold || "#F59E0B", fontWeight: 700, marginBottom: 4 }}>
          +{ch.pts} puntos al completar
        </div>
        <div style={reasonStyle}>{input.reasoning}</div>
        <div style={btnRow}>
          <button style={btnAccept} onClick={() => onAccept(proposal)} disabled={loading}>
            {loading ? "Activando..." : "Aceptar desafío"}
          </button>
          <button style={btnReject} onClick={() => onReject(proposal)}>No ahora</button>
        </div>
      </div>
    );
  }

  if (type === "propose_goal_contribution") {
    return (
      <div style={cardStyle}>
        <div style={labelStyle}>💰 Aporte a meta</div>
        <div style={titleStyle}>{input.goal_title}</div>
        <div style={{ fontSize: 13, color: C.green, fontWeight: 700, marginBottom: 4 }}>
          + {fmt(input.amount)}
        </div>
        <div style={reasonStyle}>{input.reasoning}</div>
        <div style={btnRow}>
          <button style={btnAccept} onClick={() => onAccept(proposal)} disabled={loading}>
            {loading ? "Guardando..." : "Confirmar aporte"}
          </button>
          <button style={btnReject} onClick={() => onReject(proposal)}>No ahora</button>
        </div>
      </div>
    );
  }

  return null;
}

// ── Componente principal ───────────────────────────────────────────────────────
export function MrMoneyProposals({ proposals, onAccept, onReject, loadingId }) {
  if (!proposals || proposals.length === 0) return null;

  return (
    <div style={{ marginTop: 4 }}>
      {proposals.map((p) => (
        <ProposalCard
          key={p.id || p.type}
          proposal={p}
          onAccept={onAccept}
          onReject={onReject}
          loading={loadingId === (p.id || p.type)}
        />
      ))}
    </div>
  );
}