// components/TxItem.jsx
// Fila de una transacción.
//
// Ingresos → verde Sky "#00C853" con "+". Gastos → color texto principal (neutro).
// Rojo reservado para estados de error; el gasto habitual no debe generar alarma visual.

import { C } from "../data/colors.js";
import { fmt, fmtDate, catOf } from "../utils/format.js";
import { getBankMeta } from "../data/banks.js";

export default function TxItem({ tx, onDelete, compact = false }) {
  const cat      = catOf(tx.category);
  const bankMeta = getBankMeta(tx.bank_name);
  const isIncome = tx.amount > 0;
  const sign     = isIncome ? "+" : "-";
  const color    = isIncome ? "#00C853" : C.textPrimary;

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: compact ? "8px 0" : "10px 0",
      borderBottom: `1px solid ${C.border}`,
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: "50%",
        background: "#fff",
        border: "1px solid #E5E7EB",
        overflow: "hidden",
        display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0,
        boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
      }}>
        {bankMeta.logo ? (
          <img
            src={bankMeta.logo}
            alt={bankMeta.name}
            style={{ width: "100%", height: "100%", objectFit: "contain", padding: 2 }}
          />
        ) : (
          <span style={{
            fontSize: 9, fontWeight: 800, color: "#fff",
            width: "100%", height: "100%",
            display: "flex", alignItems: "center", justifyContent: "center",
            background: bankMeta.color,
          }}>
            {bankMeta.shortCode}
          </span>
        )}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          title={tx.merchant || cat.label}
          style={{
            fontSize: 13, fontWeight: 600, color: C.textPrimary,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}
        >
          {tx.merchant || cat.label}
        </div>
        <div style={{ fontSize: 11, color: C.textMuted, marginTop: 1 }}>
          {cat.icon} {cat.label} · {fmtDate(tx.date ?? tx.created_at ?? "")}
          {tx.bank_name && <span> · {tx.bank_name}</span>}
        </div>
      </div>

      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color }}>
          {sign}{fmt(Math.abs(tx.amount ?? 0))}
        </div>
      </div>
    </div>
  );
}