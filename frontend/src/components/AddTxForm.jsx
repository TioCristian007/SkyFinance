// components/AddTxForm.jsx
// Formulario para agregar un gasto. Captura y valida input.
// Al confirmar llama a onAdd(tx) — la lógica de guardar está en Sky.jsx → api.js

import { useState } from "react";
import { C } from "../data/colors.js";
import { CATEGORIES } from "../data/categories.js";
import { today } from "../utils/format.js";

const inputStyle = {
  width: "100%", padding: "10px 13px", borderRadius: 12,
  border: `1.5px solid ${C.border}`, background: C.bg,
  fontSize: 13.5, color: C.textPrimary, outline: "none", fontFamily: "inherit",
};

export default function AddTxForm({ onAdd, disabled }) {
  const [amount,   setAmount]   = useState("");
  const [category, setCategory] = useState("food");
  const [desc,     setDesc]     = useState("");
  const [error,    setError]    = useState("");

  const submit = () => {
    const n = parseInt(String(amount).replace(/\D/g, ""));
    if (!n || n <= 0) { setError("Ingresa un monto válido"); return; }
    if (!desc.trim())  { setError("Agrega una descripción"); return; }
    onAdd({ amount: n, category, desc: desc.trim(), date: today() });
    setAmount(""); setDesc(""); setError("");
  };

  return (
    <div style={{ background: C.white, borderRadius: 18, padding: "16px 18px", border: `1px solid ${C.border}` }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: C.textPrimary, marginBottom: 13 }}>➕ Nuevo gasto</div>

      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, marginBottom: 5, letterSpacing: "0.05em" }}>MONTO ($)</div>
        <input
          value={amount} onChange={(e) => setAmount(e.target.value)}
          placeholder="Ej: 15000" type="number" style={inputStyle}
          onFocus={(e) => (e.target.style.borderColor = C.green)}
          onBlur={(e)  => (e.target.style.borderColor = C.border)}
        />
      </div>

      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, marginBottom: 7, letterSpacing: "0.05em" }}>CATEGORÍA</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {CATEGORIES.map((cat) => (
            <button
              key={cat.key} onClick={() => setCategory(cat.key)}
              style={{
                padding: "5px 11px", borderRadius: 20, fontSize: 12, fontWeight: 500,
                cursor: "pointer", fontFamily: "inherit",
                border: `1.5px solid ${category === cat.key ? cat.color : C.border}`,
                background: category === cat.key ? cat.bg : C.white,
                color: category === cat.key ? cat.color : C.textSecondary,
                transition: "all 0.15s",
              }}
            >
              {cat.icon} {cat.label}
            </button>
          ))}
        </div>
      </div>

      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, marginBottom: 5, letterSpacing: "0.05em" }}>DESCRIPCIÓN</div>
        <input
          value={desc} onChange={(e) => setDesc(e.target.value)}
          placeholder="Ej: Uber al trabajo" style={inputStyle}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          onFocus={(e) => (e.target.style.borderColor = C.green)}
          onBlur={(e)  => (e.target.style.borderColor = C.border)}
        />
      </div>

      {error && <div style={{ fontSize: 12, color: C.red, marginBottom: 8 }}>⚠ {error}</div>}

      <button
        onClick={submit} disabled={disabled}
        style={{
          width: "100%", padding: "12px", borderRadius: 13, border: "none",
          cursor: disabled ? "not-allowed" : "pointer",
          background: disabled ? C.border : `linear-gradient(135deg,${C.green},${C.greenDark})`,
          color: C.white, fontSize: 14, fontWeight: 700, fontFamily: "inherit",
        }}
      >
        {disabled ? "Guardando..." : "Agregar gasto"}
      </button>
    </div>
  );
}
