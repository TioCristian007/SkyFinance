// components/GoalCard.jsx
// Tarjeta de una meta financiera con barra de progreso y proyección.
// No calcula nada — recibe todo del backend (goal.projection).

import { C } from "../data/colors.js";
import { fmt, fmtK } from "../utils/format.js";

const TYPE_STYLES = {
  principal: {
    label:      "Misión principal",
    labelColor: "#7A5000",
    labelBg:    "#FFFDE7",
    border:     "#F9A825",
    iconBg:     "#FFFDE7",
  },
  secundaria: {
    label:      "Misión secundaria",
    labelColor: "#1B5E20",
    labelBg:    "#E8F5E9",
    border:     C.green,
    iconBg:     C.greenLight,
  },
};

export default function GoalCard({ goal, onAddSavings, onDelete }) {
  const style = TYPE_STYLES[goal.type] ?? TYPE_STYLES.secundaria;
  const { pct, remaining, monthsToGoal, projectedDate } = goal.projection;
  const isComplete = pct >= 100;

  return (
    <div style={{
      background:   C.white,
      borderRadius: 16,
      padding:      "14px 16px",
      border:       `1.5px solid ${isComplete ? C.green : style.border}`,
      position:     "relative",
      animation:    "fadeUp 0.25s ease",
    }}>

      {/* Badge tipo */}
      <div style={{
        position:     "absolute",
        top:          12,
        right:        12,
        fontSize:     10,
        fontWeight:   600,
        padding:      "2px 8px",
        borderRadius: 20,
        background:   isComplete ? C.greenLight : style.labelBg,
        color:        isComplete ? C.greenDark   : style.labelColor,
      }}>
        {isComplete ? "✓ Completada" : style.label}
      </div>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 14 }}>
        <div style={{
          width: 44, height: 44, borderRadius: 12,
          background:  style.iconBg,
          display:     "flex",
          alignItems:  "center",
          justifyContent: "center",
          fontSize:    22,
          flexShrink:  0,
        }}>
          {goal.icon}
        </div>
        <div style={{ flex: 1, paddingRight: 80 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.textPrimary, marginBottom: 2 }}>
            {goal.title}
          </div>
          <div style={{ fontSize: 12, color: C.textSecondary }}>
            Meta: {fmt(goal.targetAmount)}
            {goal.deadline && ` · hasta ${goal.deadline}`}
          </div>
        </div>
      </div>

      {/* Barra de progreso */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
          <span style={{ fontSize: 12, color: C.textSecondary, fontWeight: 500 }}>
            Ahorrado: {fmt(goal.savedAmount)}
          </span>
          <span style={{ fontSize: 13, fontWeight: 700, color: isComplete ? C.green : C.textPrimary }}>
            {pct}%
          </span>
        </div>
        <div style={{ height: 8, background: C.border, borderRadius: 99, overflow: "hidden" }}>
          <div style={{
            height:     "100%",
            width:      `${Math.min(pct, 100)}%`,
            background: isComplete
              ? `linear-gradient(90deg,${C.green},${C.greenDark})`
              : goal.type === "principal"
                ? `linear-gradient(90deg,#F9A825,#F57C00)`
                : `linear-gradient(90deg,${C.green},${C.greenDark})`,
            borderRadius: 99,
            transition:   "width 0.6s ease",
          }} />
        </div>
      </div>

      {/* Proyección */}
      {!isComplete && (
        <div style={{
          background:   C.bg,
          borderRadius: 10,
          padding:      "8px 12px",
          marginBottom: 12,
          display:      "flex",
          justifyContent: "space-between",
          alignItems:   "center",
        }}>
          <div>
            <div style={{ fontSize: 11, color: C.textMuted, fontWeight: 600, marginBottom: 2 }}>
              FALTA
            </div>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>
              {fmt(remaining)}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 11, color: C.textMuted, fontWeight: 600, marginBottom: 2 }}>
              AL RITMO ACTUAL
            </div>
            <div style={{ fontSize: 13, fontWeight: 700, color: monthsToGoal ? C.textPrimary : C.amber }}>
              {monthsToGoal
                ? monthsToGoal === 1
                  ? "1 mes más"
                  : `${monthsToGoal} meses más`
                : "Sin ahorro activo"}
            </div>
          </div>
        </div>
      )}

      {/* Acciones */}
      {!isComplete && (
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => onAddSavings(goal)}
            style={{
              flex:         1,
              padding:      "9px",
              borderRadius: 10,
              border:       `1.5px solid ${goal.type === "principal" ? "#F9A825" : C.green}`,
              background:   goal.type === "principal" ? "#FFFDE7" : C.greenLight,
              color:        goal.type === "principal" ? "#7A5000" : C.greenDark,
              fontSize:     12,
              fontWeight:   700,
              cursor:       "pointer",
              fontFamily:   "inherit",
            }}
          >
            + Agregar ahorro
          </button>
          <button
            onClick={() => onDelete(goal.id)}
            style={{
              padding:      "9px 12px",
              borderRadius: 10,
              border:       `1px solid ${C.border}`,
              background:   C.white,
              color:        C.textMuted,
              fontSize:     12,
              cursor:       "pointer",
              fontFamily:   "inherit",
            }}
          >
            Eliminar
          </button>
        </div>
      )}

      {isComplete && (
        <div style={{
          textAlign:  "center",
          fontSize:   13,
          fontWeight: 700,
          color:      C.green,
          padding:    "6px 0",
        }}>
          🎉 ¡Meta alcanzada!
        </div>
      )}
    </div>
  );
}
