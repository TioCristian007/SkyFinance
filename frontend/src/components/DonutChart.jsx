// components/DonutChart.jsx
// Muestra el porcentaje gastado del presupuesto mensual.
// Solo recibe props y renderiza SVG. Cero lógica de negocio.

import { C } from "../data/colors.js";

export default function DonutChart({ spent, total }) {
  const pct   = Math.min(spent / total, 1);
  const r     = 36, cx = 44, cy = 44, sw = 9;
  const circ  = 2 * Math.PI * r;
  const col   = pct > 0.85 ? C.red : pct > 0.65 ? C.amber : C.green;

  return (
    <svg width={88} height={88} viewBox="0 0 88 88">
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={C.border} strokeWidth={sw} />
      <circle
        cx={cx} cy={cy} r={r} fill="none" stroke={col} strokeWidth={sw}
        strokeDasharray={`${pct * circ} ${circ}`}
        strokeLinecap="round"
        transform={`rotate(-90 ${cx} ${cy})`}
        style={{ transition: "stroke-dasharray 0.6s ease" }}
      />
      <text x={cx} y={cy - 4} textAnchor="middle" fontSize="13" fontWeight="700" fill={col}>
        {Math.round(pct * 100)}%
      </text>
      <text x={cx} y={cy + 11} textAnchor="middle" fontSize="9" fill={C.textMuted}>
        gastado
      </text>
    </svg>
  );
}
