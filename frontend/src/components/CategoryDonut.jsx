// components/CategoryDonut.jsx
// Donut de distribución de gastos/ingresos por categoría. SVG nativo, sin librerías.
// Hover es estado local — no genera re-renders en el padre.
// Solo el click propaga selectedCategory hacia arriba.

import { useState } from "react";
import { getCategory } from "../data/categories.js";
import { fmt } from "../utils/format.js";

const R       = 80;
const CIRC    = 2 * Math.PI * R;   // ≈ 502.65
const STROKE  = 14;
const GAP_PX  = 8;
const MIN_PCT = 0.05; // < 5% → se fusiona en "otros"; umbral de solape ≈ (14+8)/502.65 ≈ 4.37%

function sliceColor(key) {
  return getCategory(key).donutColor ?? '#94A3B8';
}

function buildSlices(transactions, isIncome) {
  const filtered = isIncome
    ? transactions.filter(t => (t.amount ?? 0) > 0)
    : transactions.filter(t => (t.amount ?? 0) < 0);

  const total = filtered.reduce((s, t) => s + Math.abs(t.amount ?? 0), 0);
  if (total === 0) return { total: 0, slices: [] };

  // Agrupar por categoría
  const rawGroups = {};
  for (const tx of filtered) {
    const key = tx.category ?? "other";
    rawGroups[key] = (rawGroups[key] ?? 0) + Math.abs(tx.amount ?? 0);
  }

  // Separar visible (≥ MIN_PCT) de las que van a "otros"
  const visible = {};
  let othersSum = 0;
  for (const [key, value] of Object.entries(rawGroups)) {
    if (value / total >= MIN_PCT) {
      visible[key] = (visible[key] ?? 0) + value;
    } else {
      othersSum += value;
    }
  }
  if (othersSum > 0) {
    visible["other"] = (visible["other"] ?? 0) + othersSum;
  }

  const sorted = Object.entries(visible).sort((a, b) => b[1] - a[1]);

  // Calcular geometría SVG exactamente: cumulativeArc += arc (real), nunca por adjustedArc
  let cumulativeArc = 0;
  return {
    total,
    slices: sorted.map(([key, value]) => {
      const arc         = (value / total) * CIRC;
      const adjustedArc = Math.max(arc - STROKE - GAP_PX, 0.5);
      const dasharray   = `${adjustedArc} ${CIRC - adjustedArc}`;
      const dashoffset  = -cumulativeArc;
      cumulativeArc += arc;
      return {
        key, value, arc,
        label: getCategory(key).label,
        icon:  getCategory(key).icon,
        color: sliceColor(key),
        dasharray, dashoffset,
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
            <circle cx={100} cy={100} r={R} fill="none" stroke="#E8ECF0" strokeWidth={STROKE} />
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
          <circle cx={100} cy={100} r={R} fill="none" stroke="#E4EAF1" strokeWidth={STROKE} />

          {isSingleSlice ? (
            <>
              {/* Hit area — disco transparente que cubre el anillo */}
              <circle
                cx={100} cy={100} r={R + STROKE / 2}
                fill="transparent"
                style={{ cursor: "pointer" }}
                onClick={() => onSelectCategory(selectedCategory === slices[0].key ? null : slices[0].key)}
                onMouseEnter={() => setHovered(slices[0].key)}
                onMouseLeave={() => setHovered(null)}
              />
              {/* Visual ring */}
              <circle
                cx={100} cy={100} r={R}
                fill="none"
                stroke={slices[0].color}
                strokeWidth={STROKE}
                style={{ pointerEvents: "none" }}
              />
            </>
          ) : (
            <g transform="rotate(-90 100 100)">
              {/* Wedge paths: invisibles, capturan hover en toda el área del slice */}
              {slices.map(s => {
                const aStart = -s.dashoffset / R;
                const aEnd   = (-s.dashoffset + s.arc) / R;
                const x1 = (100 + R * Math.cos(aStart)).toFixed(2);
                const y1 = (100 + R * Math.sin(aStart)).toFixed(2);
                const x2 = (100 + R * Math.cos(aEnd)).toFixed(2);
                const y2 = (100 + R * Math.sin(aEnd)).toFixed(2);
                const large = s.arc / R > Math.PI ? 1 : 0;
                const d = `M 100 100 L ${x1} ${y1} A ${R} ${R} 0 ${large} 1 ${x2} ${y2} Z`;
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
              {/* Arcos visuales: pointer-events none */}
              {slices.map(s => {
                const isSelected = selectedCategory === s.key;
                const fat        = isSelected || hovered === s.key;
                return (
                  <circle
                    key={s.key}
                    cx={100} cy={100} r={R}
                    fill="none"
                    stroke={s.color}
                    strokeWidth={fat ? STROKE + 4 : STROKE}
                    strokeLinecap="round"
                    strokeDasharray={s.dasharray}
                    strokeDashoffset={s.dashoffset}
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
        width: "100%", marginTop: 20,
        display: "grid", gridTemplateColumns: "1fr 1fr",
        gap: "4px 8px",
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
            <span style={{ width: 12, height: 12, borderRadius: "50%", background: s.color, flexShrink: 0 }} />
            <span style={{
              flex: 1, fontSize: 14, fontWeight: 600, color: "#0D1B2A",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {s.label}
            </span>
            <span style={{ fontSize: 14, fontWeight: 600, color: "#374151", flexShrink: 0 }}>
              {Math.round(s.pct * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
