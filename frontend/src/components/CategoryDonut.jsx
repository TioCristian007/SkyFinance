// components/CategoryDonut.jsx
// Donut de distribución de gastos por categoría. SVG nativo, sin librerías.
// Hover es estado local — no genera re-renders en el padre.
// Solo el click propaga selectedCategory hacia arriba.

import { useState } from "react";
import { CATEGORIES, getCategory } from "../data/categories.js";
import { fmt } from "../utils/format.js";

// ── Paleta Sky: navy → verde (10 tonos) ─────────────────────────────────────
const SKY_DONUT_PALETTE = [
  '#0D1B2A', // navy core
  '#1E3A5F', // navy medio
  '#2A5C8A', // azul océano
  '#1B7A8C', // petróleo
  '#00897B', // teal oscuro
  '#00B894', // verde-teal
  '#00C853', // Sky green signature
  '#4CD964', // verde brillante
  '#7BE495', // verde menta
  '#B8F0C8', // verde muy claro
];
const OTHERS_COLOR = '#94A3B8';

// Mapping estable key → color del palette (ordenado alfabético → no varía por monto)
const SORTED_KEYS = [...CATEGORIES.map(c => c.key)].sort();
const CATEGORY_COLOR = Object.fromEntries(
  SORTED_KEYS.map((key, i) => [key, SKY_DONUT_PALETTE[i % SKY_DONUT_PALETTE.length]])
);

function sliceColor(key) {
  return CATEGORY_COLOR[key] ?? OTHERS_COLOR;
}

const CIRC = 2 * Math.PI * 80;  // ≈ 502.65

function buildSlices(transactions) {
  const expenses = transactions.filter(t => (t.amount ?? 0) < 0);
  const total    = expenses.reduce((s, t) => s + Math.abs(t.amount ?? 0), 0);
  if (total === 0) return { total: 0, slices: [] };

  const groups = {};
  for (const tx of expenses) {
    const key = tx.category ?? "other";
    groups[key] = (groups[key] ?? 0) + Math.abs(tx.amount ?? 0);
  }

  const sorted = Object.entries(groups).sort((a, b) => b[1] - a[1]);
  let cum = 0;
  return {
    total,
    slices: sorted.map(([key, value]) => {
      const arc   = (value / total) * CIRC;
      const start = cum;
      cum += arc;
      return {
        key, value,
        label: getCategory(key).label,
        color: sliceColor(key),
        arc, start,
        pct: value / total,
      };
    }),
  };
}

// ── Componente ───────────────────────────────────────────────────────────────

export default function CategoryDonut({ transactions, selectedCategory, onSelectCategory }) {
  const [hovered, setHovered] = useState(null);
  const { total, slices } = buildSlices(transactions);

  // Estado vacío
  if (total === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, padding: "28px 0" }}>
        <div style={{ position: "relative", width: "100%", maxWidth: 280 }}>
          <svg viewBox="0 0 200 200" style={{ width: "100%", height: "auto", display: "block" }}>
            <circle cx={100} cy={100} r={80} fill="none" stroke="#E8ECF0" strokeWidth={24} />
          </svg>
          <div style={{
            position: "absolute", inset: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <span style={{ fontSize: 36 }}>🌱</span>
          </div>
        </div>
        <span style={{ fontSize: 13, color: "#8A96A8" }}>Aún sin gastos este mes</span>
      </div>
    );
  }

  const active      = hovered ?? selectedCategory;
  const activeSlice = active ? slices.find(s => s.key === active) : null;
  const showActive  = Boolean(activeSlice);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>

      {/* SVG + texto central flotante */}
      <div style={{ position: "relative", width: "100%", maxWidth: 320 }}>
        <svg viewBox="0 0 200 200" style={{ width: "100%", height: "auto", display: "block" }}>
          {/* Track */}
          <circle cx={100} cy={100} r={80} fill="none" stroke="#E4EAF1" strokeWidth={28} />
          {/* Slices */}
          <g transform="rotate(-90 100 100)">
            {slices.map(s => {
              const isSelected = selectedCategory === s.key;
              const isHovered  = hovered === s.key;
              const fat        = isSelected || isHovered;
              return (
                <circle
                  key={s.key}
                  cx={100} cy={100} r={80}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={fat ? 28 : 24}
                  strokeLinecap="round"
                  strokeDasharray={`${s.arc} ${CIRC - s.arc}`}
                  strokeDashoffset={-s.start}
                  opacity={selectedCategory && !isSelected ? 0.35 : 1}
                  style={{
                    transition: "stroke-width 200ms ease-out, opacity 250ms ease, stroke-dasharray 400ms ease-out, stroke-dashoffset 400ms ease-out",
                    cursor: "pointer",
                  }}
                  onClick={() => onSelectCategory(selectedCategory === s.key ? null : s.key)}
                  onMouseEnter={() => setHovered(s.key)}
                  onMouseLeave={() => setHovered(null)}
                />
              );
            })}
          </g>
        </svg>

        {/* Texto central: dos capas con cross-fade */}
        <div style={{
          position: "absolute", inset: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          pointerEvents: "none",
        }}>
          {/* Reposo */}
          <div style={{
            position: "absolute", textAlign: "center",
            padding: "0 56px",
            opacity: showActive ? 0 : 1,
            transition: "opacity 250ms ease",
          }}>
            <div style={{
              fontSize: 20, fontWeight: 600, color: "#0D1B2A",
              lineHeight: 1.1, fontVariantNumeric: "tabular-nums",
            }}>
              {fmt(total)}
            </div>
            <div style={{ fontSize: 11, color: "#A0AAB4", marginTop: 4 }}>gastos</div>
          </div>
          {/* Activo (hover / seleccionado) */}
          <div style={{
            position: "absolute", textAlign: "center",
            padding: "0 44px",
            opacity: showActive ? 1 : 0,
            transition: "opacity 250ms ease",
          }}>
            {activeSlice && (
              <>
                <div style={{
                  fontSize: 13, fontWeight: 600,
                  color: activeSlice.color, lineHeight: 1.2,
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>
                  {activeSlice.label}
                </div>
                <div style={{
                  fontSize: 16, fontWeight: 400, color: "#0D1B2A",
                  lineHeight: 1.2, marginTop: 3, fontVariantNumeric: "tabular-nums",
                }}>
                  {fmt(activeSlice.value)}
                  <span style={{ fontSize: 12, color: "#A0AAB4", marginLeft: 4 }}>
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
            <span style={{
              width: 7, height: 7, borderRadius: "50%",
              background: s.color, flexShrink: 0,
            }} />
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
