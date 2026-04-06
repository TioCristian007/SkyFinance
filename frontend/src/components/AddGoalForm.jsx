// components/AddGoalForm.jsx
import { useState } from "react";
import { C } from "../data/colors.js";

const GOAL_ICONS = ["🏠", "🚗", "✈️", "💻", "📱", "🎓", "💍", "👶", "🏋️", "🎯", "💰", "🌎"];

const inputStyle = {
  width: "100%", padding: "10px 13px", borderRadius: 10,
  border: `1.5px solid ${C.border}`, background: C.bg,
  fontSize: 13.5, color: C.textPrimary, outline: "none", fontFamily: "inherit",
};

export default function AddGoalForm({ onAdd, onCancel, disabled }) {
  const [title,        setTitle]        = useState("");
  const [targetAmount, setTargetAmount] = useState("");
  const [savedAmount,  setSavedAmount]  = useState("");
  const [deadline,     setDeadline]     = useState("");
  const [icon,         setIcon]         = useState("🎯");
  const [type,         setType]         = useState("secundaria");
  const [error,        setError]        = useState("");

  const submit = () => {
    if (!title.trim()) { setError("Ponle un nombre a la meta"); return; }
    if (!targetAmount || parseInt(targetAmount) <= 0) {
      setError("Ingresa un monto objetivo válido"); return;
    }
    setError("");
    onAdd({
      title:        title.trim(),
      targetAmount: parseInt(String(targetAmount).replace(/\D/g, "")),
      savedAmount:  parseInt(String(savedAmount).replace(/\D/g, "")) || 0,
      deadline:     deadline || null,
      icon,
      type,
    });
  };

  return (
    <div style={{ background: C.white, borderRadius: 18, padding: "16px 18px", border: `1.5px solid ${C.green}` }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: C.textPrimary, marginBottom: 14 }}>
        Nueva meta
      </div>

      {/* Tipo */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, marginBottom: 7, letterSpacing: "0.05em" }}>TIPO</div>
        <div style={{ display: "flex", gap: 8 }}>
          {[["principal", "⭐ Misión principal"], ["secundaria", "🎯 Misión secundaria"]].map(([val, lbl]) => (
            <button
              key={val}
              type="button"
              onClick={() => setType(val)}
              style={{
                flex: 1, padding: "8px", borderRadius: 10, cursor: "pointer", fontFamily: "inherit",
                border:      `1.5px solid ${type === val ? (val === "principal" ? "#F9A825" : C.green) : C.border}`,
                background:  type === val ? (val === "principal" ? "#FFFDE7" : C.greenLight) : C.white,
                color:       type === val ? (val === "principal" ? "#7A5000" : C.greenDark) : C.textSecondary,
                fontSize: 12, fontWeight: 600,
              }}
            >
              {lbl}
            </button>
          ))}
        </div>
      </div>

      {/* Ícono */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, marginBottom: 7, letterSpacing: "0.05em" }}>ÍCONO</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {GOAL_ICONS.map((ic) => (
            <button
              key={ic}
              type="button"
              onClick={() => setIcon(ic)}
              style={{
                width: 36, height: 36, borderRadius: 10, cursor: "pointer",
                border:     `1.5px solid ${icon === ic ? C.green : C.border}`,
                background: icon === ic ? C.greenLight : C.white,
                fontSize: 18, display: "flex", alignItems: "center", justifyContent: "center",
              }}
            >
              {ic}
            </button>
          ))}
        </div>
      </div>

      {/* Nombre */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, marginBottom: 5, letterSpacing: "0.05em" }}>NOMBRE</div>
        <input
          value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder="Ej: Departamento propio"
          style={inputStyle}
          onFocus={(e) => (e.target.style.borderColor = C.green)}
          onBlur={(e)  => (e.target.style.borderColor = C.border)}
        />
      </div>

      {/* Monto objetivo */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, marginBottom: 5, letterSpacing: "0.05em" }}>MONTO OBJETIVO ($)</div>
        <input
          value={targetAmount} onChange={(e) => setTargetAmount(e.target.value)}
          placeholder="Ej: 5000000" type="number"
          style={inputStyle}
          onFocus={(e) => (e.target.style.borderColor = C.green)}
          onBlur={(e)  => (e.target.style.borderColor = C.border)}
        />
      </div>

      {/* Ya tengo ahorrado */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, marginBottom: 5, letterSpacing: "0.05em" }}>YA TENGO AHORRADO ($) — opcional</div>
        <input
          value={savedAmount} onChange={(e) => setSavedAmount(e.target.value)}
          placeholder="Ej: 500000" type="number"
          style={inputStyle}
          onFocus={(e) => (e.target.style.borderColor = C.green)}
          onBlur={(e)  => (e.target.style.borderColor = C.border)}
        />
      </div>

      {/* Fecha límite */}
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, marginBottom: 5, letterSpacing: "0.05em" }}>FECHA LÍMITE — opcional</div>
        <input
          value={deadline} onChange={(e) => setDeadline(e.target.value)}
          type="date" style={inputStyle}
          onFocus={(e) => (e.target.style.borderColor = C.green)}
          onBlur={(e)  => (e.target.style.borderColor = C.border)}
        />
      </div>

      {error && (
        <div style={{ fontSize: 12, color: C.red, marginBottom: 10 }}>⚠ {error}</div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button
          type="button"
          onClick={onCancel}
          style={{
            flex: 1, padding: "11px", borderRadius: 12, cursor: "pointer", fontFamily: "inherit",
            border: `1px solid ${C.border}`, background: C.white,
            color: C.textSecondary, fontSize: 13, fontWeight: 600,
          }}
        >
          Cancelar
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={disabled}
          style={{
            flex: 2, padding: "11px", borderRadius: 12, border: "none", fontFamily: "inherit",
            background: disabled ? C.border : `linear-gradient(135deg,${C.green},${C.greenDark})`,
            color: C.white, fontSize: 13, fontWeight: 700,
            cursor: disabled ? "not-allowed" : "pointer",
          }}
        >
          {disabled ? "Guardando..." : "Crear meta"}
        </button>
      </div>
    </div>
  );
}
