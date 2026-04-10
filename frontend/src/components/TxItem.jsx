// components/TxItem.jsx
// Fila de una transacción.
//
// FIX: antes mostraba "-" hardcodeado para TODOS los items, incluyendo ingresos.
// Ahora: income → verde con "+", el resto → rojo con "-".

import { C } from "../data/colors.js";
import { fmtK, fmtDate, catOf } from "../utils/format.js";

export default function TxItem({ tx, onDelete, compact = false }) {
  const cat      = catOf(tx.category);
  const isIncome = tx.category === "income" || tx.category === "transfer";
  const sign     = isIncome ? "+" : "-";
  const color    = isIncome ? "#22C55E" : C.red;

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: compact ? "8px 0" : "10px 0",
      borderBottom: `1px solid ${C.border}`,
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
          {tx.description || tx.desc || cat.label}
        </div>
        <div style={{ fontSize: 11, color: C.textMuted, marginTop: 1 }}>
          {cat.label} · {fmtDate(tx.date ?? tx.created_at ?? "")}
          {tx.bank_name && <span> · {tx.bank_name}</span>}
        </div>
      </div>

      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color }}>
          {sign}{fmtK(Math.abs(tx.amount ?? 0))}
        </div>
        {onDelete && (
          <button
            onClick={() => onDelete(tx.id)}
            style={{ fontSize: 10, color: C.textMuted, background: "none", border: "none", cursor: "pointer", padding: 0 }}
          >
            eliminar
          </button>
        )}
      </div>
    </div>
  );
}