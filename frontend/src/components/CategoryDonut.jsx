// components/CategoryDonut.jsx
// Donut de distribución de gastos/ingresos por categoría. SVG nativo, sin librerías.
// Hover es estado local — no genera re-renders en el padre.
// Solo el click propaga selectedCategory hacia arriba.

import { useState } from "react";
import { getCategory } from "../data/categories.js";
import { fmt } from "../utils/format.js";

const CIRC   = 2 * Math.PI * 80;
const STROKE = 16;
const GAP_PX = 8;  // gap visual entre slices (8 = STROKE/2 → sin solapamiento de caps)

function sliceColor(key) {
  return getCategory(key).donutColor ?? '#94A3B8';
}

function buildSlices(transactions, isIncome) {
  const filtered = isIncome
    ? transactions.filter(t => (t.amount ?? 0) > 0)
    : transactions.filter(t => (t.amount ?? 0) < 0);

  const total = filtered.reduce((s, t) => s + Math.abs(t.amount ?? 0), 0);
  if (total === 0) return { total: 0, slices: [] };

  const rawGroups = {};
  for (const tx of filtered) {
    const key = tx.category ?? "other";
    rawGroups[key] = (rawGroups[key] ?? 0) + Math.abs(tx.amount ?? 0);
  }

  // Categorías con pct < 2% se agrupan en "other" para evitar slices clamped
  const groups = {};
  for (const [key, value] of Object.entries(rawGroups)) {
    if (value / total < 0.02) {
      groups["other"] = (groups["other"] ?? 0) + value;
    } else {
      groups[key] = (groups[key] ?? 0) + value;
    }
  }

  const sorted = Object.entries(groups).sort((a, b) => b[1] - a[1]);

  let cum = 0;
  return {
    total,
    slices: sorted.map(([key, value]) => {
      const fullArc = (value / total) * CIRC;
      // round cap extiende STROKE visual (STROKE/2 a cada lado).
      // Restar STROKE compensa; GAP_PX da la separación entre slices.
      // gap visual final = GAP_PX; visualArc = fullArc - GAP_PX (fidelidad preservada).
      const drawArc = Math.max(fullArc - STROKE - GAP_PX, 0.5);
      const start   = cum;
      cum += fullArc; // avance por arco completo — nunca por drawArc
      return {
        key, value, fullArc,
        label: getCategory(key).label,
        icon:  getCategory(key).icon,
        color: sliceColor(key),
        drawArc, start,
        pct: value / total,
      };
    }),
  };
}

// ── Componente ───────────────────────────────────────────────────────────────

export default function CategoryDonut({ transactions, selectedCategory, onSelectCategory, tipoFilter }) {
  const [hovered, setHovered] = useState(null);

  const isIncome    = tipoFilter === "income";
  const centerLabel = isIncome ? "ingresos" : "gastos";
  const emptyMsg    = isIncome ? "Sin ingresos en este período 🌱" : "Aún sin gastos este mes 🌱";

  const { total, slices } = buildSlices(transactions, isIncome);

  // Estado vacío
  if (total === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, padding: "28px 0" }}>
        <div style={{ position: "relative", width: "100%", maxWidth: 280 }}>
          <svg viewBox="0 0 200 200" style={{ width: "100%", height: "auto", display: "block" }}>
            <circle cx={100} cy={100} r={80} fill="none" stroke="#E8ECF0" strokeWidth={STROKE} />
          </svg>
          <div style={{
            position: "absolute", inset: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <span style={{ fontSize: 36 }}>🌱</span>
          </div>
        </div>
        <span style={{ fontSize: 13, color: "#8A96A8" }}>{emptyMsg}</span>
      </div>
    );
  }

  const active      = hovered ?? selectedCategory;
  const activeSlice = active ? slices.find(s => s.key === active) : null;
  const showActive  = Boolean(activeSlice);
  const isSingleSlice = slices.length === 1;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>

      {/* SVG + texto central flotante */}
      <div style={{ position: "relative", width: "100%", maxWidth: 420 }}>
        <svg viewBox="0 0 200 200" style={{ width: "100%", height: "auto", display: "block" }}>
          {/* Track */}
          <circle cx={100} cy={100} r={80} fill="none" stroke="#E4EAF1" strokeWidth={STROKE} />

          {isSingleSlice ? (
            <>
              {/* Hit area — disco transparente que cubre todo el anillo */}
              <circle
                cx={100} cy={100} r={88}
                fill="transparent"
                style={{ cursor: "pointer" }}
                onClick={() => onSelectCategory(selectedCategory === slices[0].key ? null : slices[0].key)}
                onMouseEnter={() => setHovered(slices[0].key)}
                onMouseLeave={() => setHovered(null)}
              />
              {/* Visual ring */}
              <circle
                cx={100} cy={100} r={80}
                fill="none"
                stroke={slices[0].color}
                strokeWidth={STROKE}
                style={{ pointerEvents: "none" }}
              />
            </>
          ) : (
            <g transform="rotate(-90 100 100)">
              {/* Wedge paths: invisibles, capturan hover en toda el área del slice
                  (incluyendo el hueco central). Se renderizan ANTES que los arcos
                  visuales para que queden debajo en z-order. */}
              {slices.map(s => {
                const aStart = s.start / 80;
                const aEnd   = (s.start + s.fullArc) / 80;
                const x1 = (100 + 80 * Math.cos(aStart)).toFixed(2);
                const y1 = (100 + 80 * Math.sin(aStart)).toFixed(2);
                const x2 = (100 + 80 * Math.cos(aEnd)).toFixed(2);
                const y2 = (100 + 80 * Math.sin(aEnd)).toFixed(2);
                const large = s.fullArc / 80 > Math.PI ? 1 : 0;
                const d = `M 100 100 L ${x1} ${y1} A 80 80 0 ${large} 1 ${x2} ${y2} Z`;
                return (
                  <path
                    key={`w-${s.key}`}
                    d={d}
                    fill="transparent"
                    stroke="none"
                    style={{ cursor: "pointer" }}
                    onClick={() => onSelectCategory(selectedCategory === s.key ? null : s.key)}
                    onMouseEnter={() => setHovered(s.key)}
                    onMouseLeave={() => setHovered(null)}
                  />
                );
              })}
              {/* Arcos visuales: pointer-events none — los wedges capturan los eventos */}
              {slices.map(s => {
                const isSelected = selectedCategory === s.key;
                const fat        = isSelected || hovered === s.key;
                return (
                  <circle
                    key={s.key}
                    cx={100} cy={100} r={80}
                    fill="none"
                    stroke={s.color}
                    strokeWidth={fat ? STROKE + 4 : STROKE}
                    strokeLinecap="round"
                    strokeDasharray={`${s.drawArc} ${CIRC - s.drawArc}`}
                    strokeDashoffset={-s.start}
                    opacity={selectedCategory && !isSelected ? 0.35 : 1}
                    style={{
                      transition: "stroke-width 200ms ease-out, opacity 250ms ease",
                      pointerEvents: "none",
                    }}
                  />
                );
              })}
            </g>
          )}
        </svg>

        {/* Texto central: dos capas con cross-fade */}
        <div style={{
          position: "absolute", inset: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          pointerEvents: "none",
        }}>
          {/* Reposo */}
          <div style={{
            position: "absolute", textAlign: "center", padding: "0 56px",
            opacity: showActive ? 0 : 1, transition: "opacity 250ms ease",
          }}>
            <div style={{
              fontSize: 20, fontWeight: 600, color: "#0D1B2A",
              lineHeight: 1.1, fontVariantNumeric: "tabular-nums",
            }}>
              {fmt(total)}
            </div>
            <div style={{ fontSize: 11, color: "#A0AAB4", marginTop: 4 }}>{centerLabel}</div>
          </div>

          {/* Activo (hover / seleccionado): emoji + label + monto · % */}
          <div style={{
            position: "absolute", textAlign: "center", padding: "0 40px",
            opacity: showActive ? 1 : 0, transition: "opacity 250ms ease",
            width: "100%",
          }}>
            {activeSlice && (
              <>
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  gap: 4, lineHeight: 1.2, overflow: "hidden",
                }}>
                  <span style={{ fontSize: 24, flexShrink: 0 }}>{activeSlice.icon}</span>
                  <span style={{
                    fontSize: 18, fontWeight: 600, color: activeSlice.color,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}>
                    {activeSlice.label}
                  </span>
                </div>
                <div style={{
                  fontSize: 22, fontWeight: 400, color: "#0D1B2A",
                  lineHeight: 1.2, marginTop: 4, fontVariantNumeric: "tabular-nums",
                  whiteSpace: "nowrap",
                }}>
                  {fmt(activeSlice.value)}
                  <span style={{ fontSize: 14, color: "#A0AAB4", marginLeft: 4 }}>
                    · {Math.round(activeSlice.pct * 100)}%
                  </span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Leyenda completa en 2 columnas */}
      <div style={{
        width: "100%", marginTop: 14,
        display: "grid", gridTemplateColumns: "1fr 1fr",
        gap: "1px 8px",
      }}>
        {slices.map(s => (
          <div
            key={s.key}
            onClick={() => onSelectCategory(selectedCategory === s.key ? null : s.key)}
            onMouseEnter={() => setHovered(s.key)}
            onMouseLeave={() => setHovered(null)}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "4px 5px", borderRadius: 6, cursor: "pointer",
              background: selectedCategory === s.key
                ? `${s.color}1A`
                : hovered === s.key ? `${s.color}0D` : "transparent",
              transition: "background 0.15s",
            }}
          >
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: s.color, flexShrink: 0 }} />
            <span style={{
              flex: 1, fontSize: 12, color: "#0D1B2A",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {s.label}
            </span>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#6B7A8D", flexShrink: 0 }}>
              {Math.round(s.pct * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
