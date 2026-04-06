// components/AddSavingsModal.jsx
// Modal inline para actualizar el ahorro acumulado de una meta.

import { useState } from "react";
import { C } from "../data/colors.js";
import { fmt } from "../utils/format.js";

export default function AddSavingsModal({ goal, onConfirm, onCancel }) {
  const [amount, setAmount] = useState("");
  const [error,  setError]  = useState("");

  const submit = () => {
    const n = parseInt(String(amount).replace(/\D/g, ""));
    if (!n || n <= 0) { setError("Ingresa un monto válido"); return; }
    onConfirm(goal.id, goal.savedAmount + n);
  };

  return (
    <div style={{
      position:       "fixed",
      inset:          0,
      background:     "rgba(0,0,0,0.45)",
      display:        "flex",
      alignItems:     "flex-end",
      justifyContent: "center",
      zIndex:         1000,
      padding:        "0 12px 24px",
    }}>
      <div style={{
        background:   "#fff",
        borderRadius: 20,
        padding:      "20px",
        width:        "100%",
        maxWidth:     420,
        animation:    "fadeUp 0.2s ease",
      }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: C.textPrimary, marginBottom: 4 }}>
          {goal.icon} {goal.title}
        </div>
        <div style={{ fontSize: 12, color: C.textSecondary, marginBottom: 16 }}>
          Tienes ahorrado {fmt(goal.savedAmount)} de {fmt(goal.targetAmount)}
        </div>

        <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, marginBottom: 6, letterSpacing: "0.05em" }}>
          ¿CUÁNTO VAS A AGREGAR? ($)
        </div>
        <input
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          autoFocus
          placeholder="Ej: 100000"
          type="number"
          onKeyDown={(e) => e.key === "Enter" && submit()}
          style={{
            width: "100%", padding: "11px 14px", borderRadius: 12,
            border:     `1.5px solid ${C.border}`,
            background: C.bg, fontSize: 14,
            color:      C.textPrimary, outline: "none", fontFamily: "inherit",
            marginBottom: 8,
          }}
          onFocus={(e) => (e.target.style.borderColor = C.green)}
          onBlur={(e)  => (e.target.style.borderColor = C.border)}
        />

        {/* Sugerencias rápidas */}
        <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
          {[50000, 100000, 200000, 500000].map((n) => (
            <button
              key={n}
              onClick={() => setAmount(String(n))}
              style={{
                padding:      "4px 10px",
                borderRadius: 20,
                border:       `1px solid ${C.border}`,
                background:   amount == n ? C.greenLight : C.white,
                color:        amount == n ? C.greenDark  : C.textSecondary,
                fontSize:     12, fontWeight: 500,
                cursor:       "pointer", fontFamily: "inherit",
              }}
            >
              ${(n / 1000).toFixed(0)}K
            </button>
          ))}
        </div>

        {error && <div style={{ fontSize: 12, color: C.red, marginBottom: 10 }}>⚠ {error}</div>}

        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1, padding: "11px", borderRadius: 12,
              border:     `1px solid ${C.border}`,
              background: C.white, color: C.textSecondary,
              fontSize:   13, fontWeight: 600,
              cursor:     "pointer", fontFamily: "inherit",
            }}
          >
            Cancelar
          </button>
          <button
            onClick={submit}
            style={{
              flex: 2, padding: "11px", borderRadius: 12, border: "none",
              background: `linear-gradient(135deg,${C.green},${C.greenDark})`,
              color:      "#fff",
              fontSize:   13, fontWeight: 700,
              cursor:     "pointer", fontFamily: "inherit",
            }}
          >
            Agregar ahorro
          </button>
        </div>
      </div>
    </div>
  );
}
