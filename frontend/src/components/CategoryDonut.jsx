// components/CategoryDonut.jsx
// Donut de distribución de gastos por categoría. SVG nativo, sin librerías.
// Hover es estado local (no genera re-renders en el padre).
// Solo el click propaga selectedCategory hacia arriba.

import { useState } from "react";
import { getCategory } from "../data/categories.js";
import { fmt } from "../utils/format.js";

const CIRC = 2 * Math.PI * 80;   // ≈ 502.65
const OTHERS = { key: "__otros__", label: "Otros", color: "#94A3B8", icon: "📦" };

function buildSlices(transactions) {
  const expenses = transactions.filter(t => (t.amount ?? 0) < 0);
  const total = expenses.reduce((s, t) => s + Math.abs(t.amount ?? 0), 0);
  if (total === 0) return { total: 0, slices: [] };

  const groups = {};
  for (const tx of expenses) {
    const key = tx.category ?? "other";
    groups[key] = (groups[key] ?? 0) + Math.abs(tx.amount ?? 0);
  }

  const sorted = Object.entries(groups).sort((a, b) => b[1] - a[1]);
  const top6   = sorted.slice(0, 6);
  const rest   = sorted.slice(6);
  const otrosTotal = rest.reduce((s, [, v]) => s + v, 0);

  const raw = [
    ...top6.map(([key, value]) => ({ key, value, meta: getCategory(key) })),
    ...(otrosTotal > 0 ? [{ key: OTHERS.key, value: otrosTotal, meta: OTHERS }] : []),
  ];

  let cum = 0;
  const slices = raw.map(s => {
    const arc = (s.value / total) * CIRC;
    const start = cum;
    cum += arc;
    return { ...s, arc, start, pct: s.value / total };
  });

  return { total, slices };
}

export default function CategoryDonut({ transactions, selectedCategory, onSelectCategory }) {
  const [hovered, setHovered] = useState(null);
  const { total, slices } = buildSlices(transactions);

  if (total === 0) {
    return (
      <div style={{
        flex: 1, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 14,
        padding: "24px 0",
      }}>
        <svg viewBox="0 0 200 200" width={220} height={220}>
          <circle cx={100} cy={100} r={80} fill="none" stroke="#E8ECF0" strokeWidth={28} />
          <circle cx={100} cy={100} r={44} fill="#F4F6F9" />
          <text x={100} y={97} textAnchor="middle" fontSize="13" fill="#A0AAB4" fontFamily="inherit">sin gastos</text>
          <text x={100} y={113} textAnchor="middle" fontSize="20" fill="#A0AAB4">🌱</text>
        </svg>
        <span style={{ fontSize: 13, color: "#8A96A8", textAlign: "center" }}>
          Aún sin gastos este mes 🌱
        </span>
      </div>
    );
  }

  const active = hovered ?? selectedCategory;
  const activeSlice = active ? slices.find(s => s.key === active) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: 1, minHeight: 0 }}>
      {/* SVG + centro flotante */}
      <div style={{ position: "relative", width: 220, height: 220, flexShrink: 0 }}>
        <svg viewBox="0 0 200 200" width={220} height={220} style={{ display: "block" }}>
          {/* Track */}
          <circle cx={100} cy={100} r={80} fill="none" stroke="#E8ECF0" strokeWidth={28} />
          {/* Slices */}
          <g transform="rotate(-90 100 100)">
            {slices.map(s => (
              <circle
                key={s.key}
                cx={100} cy={100} r={80}
                fill="none"
                stroke={s.meta.color}
                strokeWidth={28}
                strokeDasharray={`${s.arc} ${CIRC - s.arc}`}
                strokeDashoffset={-s.start}
                opacity={selectedCategory && s.key !== selectedCategory ? 0.3 : 1}
                style={{ transition: "opacity 150ms ease", cursor: "pointer" }}
                onClick={() => onSelectCategory(selectedCategory === s.key ? null : s.key)}
                onMouseEnter={() => setHovered(s.key)}
                onMouseLeave={() => setHovered(null)}
              />
            ))}
          </g>
        </svg>

        {/* Texto central absoluto */}
        <div style={{
          position: "absolute", inset: 0,
          display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center",
          pointerEvents: "none", textAlign: "center",
          padding: "0 48px",
        }}>
          {activeSlice ? (
            <>
              <span style={{ fontSize: 11, color: "#8A96A8", lineHeight: 1.3 }}>
                {activeSlice.meta.icon} {activeSlice.meta.label}
              </span>
              <span style={{ fontSize: 15, fontWeight: 800, color: "#0D1B2A", lineHeight: 1.2, marginTop: 3 }}>
                {fmt(activeSlice.value)}
              </span>
              <span style={{ fontSize: 11, color: "#8A96A8", marginTop: 2 }}>
                {Math.round(activeSlice.pct * 100)}%
              </span>
            </>
          ) : (
            <>
              <span style={{ fontSize: 15, fontWeight: 800, color: "#0D1B2A", lineHeight: 1.2 }}>
                {fmt(total)}
              </span>
              <span style={{ fontSize: 11, color: "#8A96A8", marginTop: 2 }}>gastos</span>
            </>
          )}
        </div>
      </div>

      {/* Leyenda */}
      <div style={{ width: "100%", marginTop: 4 }}>
        {slices.slice(0, 4).map(s => (
          <div
            key={s.key}
            onClick={() => onSelectCategory(selectedCategory === s.key ? null : s.key)}
            style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "5px 6px", borderRadius: 7,
              cursor: "pointer",
              background: selectedCategory === s.key ? `${s.meta.color}18` : "transparent",
              transition: "background 0.15s",
            }}
          >
            <span style={{
              width: 8, height: 8, borderRadius: "50%",
              background: s.meta.color, flexShrink: 0,
            }} />
            <span style={{ flex: 1, fontSize: 12, color: "#4A5568" }}>{s.meta.label}</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: "#0D1B2A" }}>
              {Math.round(s.pct * 100)}%
            </span>
          </div>
        ))}
        {slices.length > 4 && (
          <div style={{ fontSize: 11, color: "#A0AAB4", padding: "3px 6px" }}>
            + {slices.length - 4} más
          </div>
        )}
      </div>
    </div>
  );
}
