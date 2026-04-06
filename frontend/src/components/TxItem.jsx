// components/TxItem.jsx
// Fila de una transacción. Solo muestra, no calcula.

import { C } from "../data/colors.js";
import { fmtK, fmtDate, catOf } from "../utils/format.js";

export default function TxItem({ tx, onDelete }) {
  const cat = catOf(tx.category);
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "10px 0", borderBottom: `1px solid ${C.border}`,
    }}>
      <div style={{
        width: 38, height: 38, borderRadius: 12, background: cat.bg,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 17, flexShrink: 0,
      }}>
        {cat.icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 13, fontWeight: 600, color: C.textPrimary,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {tx.desc}
        </div>
        <div style={{ fontSize: 11, color: C.textMuted, marginTop: 1 }}>
          {cat.label} · {fmtDate(tx.date)}
        </div>
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.red }}>
          -{fmtK(tx.amount)}
        </div>
        <button
          onClick={() => onDelete(tx.id)}
          style={{ fontSize: 10, color: C.textMuted, background: "none", border: "none", cursor: "pointer", padding: 0 }}
        >
          eliminar
        </button>
      </div>
    </div>
  );
}
