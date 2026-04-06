// components/ChallengeCard.jsx
import { C } from "../data/colors.js";

const DIFF_COLOR = { Fácil: C.green,  Medio: C.amber,    Difícil: C.red };
const DIFF_BG    = { Fácil: C.greenLight, Medio: "#FFF3E0", Difícil: "#FFEBEE" };

export function ChallengeCard({ ch, onActivate, onComplete, isActive, prog, isDone }) {
  const diffCol = DIFF_COLOR[ch.difficulty] ?? C.textSecondary;
  const diffBg  = DIFF_BG[ch.difficulty]    ?? C.bg;

  return (
    <div style={{
      background: C.white, borderRadius: 16, padding: "14px 16px",
      border: `1.5px solid ${isDone ? C.gold : isActive ? C.green : C.border}`,
      position: "relative", animation: "fadeUp 0.25s ease", opacity: isDone ? 0.72 : 1,
    }}>
      {isDone && <div style={{ position: "absolute", top: 10, right: 12, fontSize: 18 }}>✅</div>}

      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: isActive ? 12 : 0 }}>
        <div style={{
          width: 40, height: 40, borderRadius: 12,
          background: isDone ? "#FFFDE7" : isActive ? C.greenLight : C.bg,
          display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, flexShrink: 0,
        }}>
          {ch.icon}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>{ch.label}</span>
            <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 20, background: diffBg, color: diffCol }}>
              {ch.difficulty}
            </span>
          </div>
          <div style={{ fontSize: 12, color: C.textSecondary, marginBottom: 3 }}>{ch.desc}</div>
          <div style={{ fontSize: 11, color: C.textMuted }}>{ch.pts} pts · {ch.days} {ch.days === 1 ? "día" : "días"}</div>
        </div>
      </div>

      {isActive && prog && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
            <span style={{ fontSize: 12, color: C.textSecondary, fontWeight: 500 }}>Progreso</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: prog.done ? C.gold : C.green }}>{prog.pct}%</span>
          </div>
          <div style={{ height: 7, background: C.border, borderRadius: 99, overflow: "hidden", marginBottom: prog.done ? 10 : 0 }}>
            <div style={{ height: "100%", width: `${prog.pct}%`, background: prog.done ? C.gold : C.green, borderRadius: 99, transition: "width 0.6s ease" }} />
          </div>
          {prog.done && (
            <button onClick={() => onComplete(ch)} style={{
              width: "100%", padding: "10px", borderRadius: 12, border: "none", cursor: "pointer",
              background: `linear-gradient(135deg,${C.gold},#E65100)`, color: C.white, fontSize: 13, fontWeight: 700, fontFamily: "inherit",
            }}>
              🏆 Reclamar {ch.pts} puntos
            </button>
          )}
        </div>
      )}

      {!isActive && !isDone && (
        <button onClick={() => onActivate(ch)} style={{
          marginTop: 10, width: "100%", padding: "9px", borderRadius: 12,
          border: `1.5px solid ${C.green}`, background: C.greenLight, color: C.greenDark,
          fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
        }}>
          Aceptar desafío
        </button>
      )}
    </div>
  );
}

// components/BadgeItem.jsx
export function BadgeItem({ badge, earned }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 5, opacity: earned ? 1 : 0.3 }}>
      <div style={{
        width: 50, height: 50, borderRadius: 14,
        background: earned ? "#FFFDE7" : C.bg,
        border: `2px solid ${earned ? C.gold : C.border}`,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 22, transition: "all 0.3s",
      }}>
        {badge.icon}
      </div>
      <div style={{ fontSize: 10, fontWeight: 600, color: earned ? C.textPrimary : C.textMuted, textAlign: "center", maxWidth: 58, lineHeight: 1.2 }}>
        {badge.label}
      </div>
    </div>
  );
}
