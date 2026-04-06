// components/CatBars.jsx
// Barras de gasto por categoría.
// Recibe categoryTotals del backend (ya calculados), no calcula nada.

import { C } from "../data/colors.js";
import { CATEGORIES } from "../data/categories.js";
import { fmtK } from "../utils/format.js";

export default function CatBars({ categoryTotals = {} }) {
  const max    = Math.max(...Object.values(categoryTotals), 1);
  const sorted = CATEGORIES
    .filter((c) => categoryTotals[c.key])
    .sort((a, b) => (categoryTotals[b.key] || 0) - (categoryTotals[a.key] || 0));

  if (!sorted.length)
    return (
      <div style={{ fontSize: 13, color: C.textMuted, textAlign: "center", padding: "12px 0" }}>
        Sin transacciones aún
      </div>
    );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {sorted.map((cat) => (
        <div key={cat.key}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span style={{ fontSize: 13, color: C.textPrimary, fontWeight: 500 }}>
              {cat.icon} {cat.label}
            </span>
            <span style={{ fontSize: 13, color: C.textSecondary, fontFamily: "monospace" }}>
              {fmtK(categoryTotals[cat.key])}
            </span>
          </div>
          <div style={{ height: 6, background: C.border, borderRadius: 99, overflow: "hidden" }}>
            <div style={{
              height: "100%",
              width: `${(categoryTotals[cat.key] / max) * 100}%`,
              background: cat.color,
              borderRadius: 99,
              transition: "width 0.6s ease",
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}
