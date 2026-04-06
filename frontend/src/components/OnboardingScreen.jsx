// components/OnboardingScreen.jsx
// Se muestra solo una vez — cuando el usuario se registra por primera vez.
// Captura nombre, edad, región e ingreso.
// Después de completarlo, nunca vuelve a aparecer.

import { useState } from "react";
import { C } from "../data/colors.js";
import { upsertProfile } from "../services/supabase.js";

const AGE_RANGES    = ["18-25", "26-35", "36-45", "46-55", "55+"];
const INCOME_RANGES = ["0-500k", "500k-1M", "1M-2M", "2M+"];
const INCOME_LABELS = {
  "0-500k":  "Menos de $500.000",
  "500k-1M": "$500.000 – $1.000.000",
  "1M-2M":   "$1.000.000 – $2.000.000",
  "2M+":     "Más de $2.000.000",
};
const REGIONS = [
  "RM-Central", "RM-Sur", "RM-Norte", "RM-Oriente",
  "Valparaíso", "Biobío", "La Araucanía", "Antofagasta",
  "Coquimbo", "O'Higgins", "Maule", "Los Lagos", "Otra región",
];

const STEPS = ["Bienvenido", "¿Quién eres?", "¿Dónde estás?", "¿Cuánto ganas?"];

export default function OnboardingScreen({ userId, onComplete }) {
  const [step,        setStep]        = useState(0);
  const [displayName, setDisplayName] = useState("");
  const [ageRange,    setAgeRange]    = useState("");
  const [region,      setRegion]      = useState("");
  const [incomeRange, setIncomeRange] = useState("");
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState("");

  const canNext = () => {
    if (step === 1) return displayName.trim().length > 0 && ageRange !== "";
    if (step === 2) return region !== "";
    if (step === 3) return incomeRange !== "";
    return true;
  };

  const handleNext = async () => {
    if (step < 3) { setStep(step + 1); return; }

    // Último paso — guardar perfil
    setLoading(true);
    setError("");
    try {
      await upsertProfile(userId, {
        display_name:  displayName.trim(),
        age_range:     ageRange,
        region:        region,
        income_range:  incomeRange,
      });
      onComplete();
    } catch (e) {
      setError("Error al guardar. Intenta de nuevo.");
    } finally {
      setLoading(false);
    }
  };

  const pillStyle = (selected) => ({
    padding:      "10px 16px",
    borderRadius: 24,
    border:       `1.5px solid ${selected ? C.green : C.border}`,
    background:   selected ? C.greenLight : C.white,
    color:        selected ? C.greenDark  : C.textSecondary,
    fontSize:     13,
    fontWeight:   selected ? 700 : 500,
    cursor:       "pointer",
    fontFamily:   "inherit",
    transition:   "all 0.15s",
  });

  return (
    <div style={{
      minHeight:      "100vh",
      background:     C.bg,
      display:        "flex",
      alignItems:     "center",
      justifyContent: "center",
      padding:        20,
      fontFamily:     "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    }}>
      <div style={{
        width:        "100%",
        maxWidth:     400,
        background:   C.white,
        borderRadius: 28,
        padding:      "36px 32px",
        boxShadow:    "0 20px 60px rgba(0,0,0,0.12)",
      }}>

        {/* Progress dots */}
        <div style={{ display: "flex", gap: 8, marginBottom: 32, justifyContent: "center" }}>
          {STEPS.map((_, i) => (
            <div key={i} style={{
              height:       4,
              width:        step >= i ? 32 : 16,
              borderRadius: 99,
              background:   step >= i ? C.green : C.border,
              transition:   "all 0.3s",
            }} />
          ))}
        </div>

        {/* Step 0 — Bienvenida */}
        {step === 0 && (
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 52, marginBottom: 16 }}>💸</div>
            <div style={{ fontSize: 24, fontWeight: 800, color: C.navy, marginBottom: 12 }}>
              Bienvenido a Sky
            </div>
            <div style={{ fontSize: 15, color: C.textSecondary, lineHeight: 1.6, marginBottom: 32 }}>
              Tu asesor financiero personal. En 3 preguntas rápidas personalizamos tu experiencia.
            </div>
            <div style={{
              background:   C.bg,
              borderRadius: 14,
              padding:      "14px 18px",
              textAlign:    "left",
              marginBottom: 8,
            }}>
              {["Tus datos son privados y tuyos", "Sky nunca vende tu información personal", "Puedes modificar esto cuando quieras"].map((t) => (
                <div key={t} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, fontSize: 13, color: C.textSecondary }}>
                  <span style={{ color: C.green, fontWeight: 700 }}>✓</span> {t}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Step 1 — Nombre + edad */}
        {step === 1 && (
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: C.textPrimary, marginBottom: 6 }}>
              ¿Cómo te llamamos?
            </div>
            <div style={{ fontSize: 13, color: C.textSecondary, marginBottom: 20 }}>
              Solo el nombre que quieres ver en la app
            </div>
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Ej: Juan, Ana, Cristóbal..."
              autoFocus
              style={{
                width: "100%", padding: "13px 16px", borderRadius: 14,
                border: `1.5px solid ${C.border}`, background: C.bg,
                fontSize: 15, color: C.textPrimary, outline: "none",
                fontFamily: "inherit", marginBottom: 24,
              }}
              onFocus={(e) => (e.target.style.borderColor = C.green)}
              onBlur={(e)  => (e.target.style.borderColor = C.border)}
            />

            <div style={{ fontSize: 13, fontWeight: 600, color: C.textMuted, marginBottom: 12, letterSpacing: "0.05em" }}>
              RANGO DE EDAD
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {AGE_RANGES.map((r) => (
                <button key={r} onClick={() => setAgeRange(r)} style={pillStyle(ageRange === r)}>
                  {r} años
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Step 2 — Región */}
        {step === 2 && (
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: C.textPrimary, marginBottom: 6 }}>
              ¿En qué región vives?
            </div>
            <div style={{ fontSize: 13, color: C.textSecondary, marginBottom: 20 }}>
              Solo la región general
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, maxHeight: 280, overflowY: "auto" }}>
              {REGIONS.map((r) => (
                <button key={r} onClick={() => setRegion(r)} style={pillStyle(region === r)}>
                  {r}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Step 3 — Ingreso */}
        {step === 3 && (
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: C.textPrimary, marginBottom: 6 }}>
              ¿Cuánto ganas al mes?
            </div>
            <div style={{ fontSize: 13, color: C.textSecondary, marginBottom: 20 }}>
              Un rango aproximado — para que Sky te ayude mejor
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {INCOME_RANGES.map((r) => (
                <button
                  key={r}
                  onClick={() => setIncomeRange(r)}
                  style={{
                    padding:        "14px 18px",
                    borderRadius:   14,
                    border:         `1.5px solid ${incomeRange === r ? C.green : C.border}`,
                    background:     incomeRange === r ? C.greenLight : C.white,
                    color:          incomeRange === r ? C.greenDark  : C.textPrimary,
                    fontSize:       14,
                    fontWeight:     incomeRange === r ? 700 : 400,
                    cursor:         "pointer",
                    fontFamily:     "inherit",
                    textAlign:      "left",
                    transition:     "all 0.15s",
                  }}
                >
                  {INCOME_LABELS[r]}
                </button>
              ))}
            </div>
          </div>
        )}

        {error && (
          <div style={{ fontSize: 13, color: "#C62828", background: "#FFEBEE", borderRadius: 10, padding: "10px 14px", marginTop: 16 }}>
            ⚠ {error}
          </div>
        )}

        {/* Navigation */}
        <div style={{ display: "flex", gap: 10, marginTop: 28 }}>
          {step > 0 && (
            <button
              onClick={() => setStep(step - 1)}
              style={{
                flex: 1, padding: "13px", borderRadius: 14,
                border: `1px solid ${C.border}`, background: C.white,
                color: C.textSecondary, fontSize: 14, fontWeight: 600,
                cursor: "pointer", fontFamily: "inherit",
              }}
            >
              ← Atrás
            </button>
          )}
          <button
            onClick={handleNext}
            disabled={!canNext() || loading}
            style={{
              flex: step === 0 ? 1 : 2,
              padding: "13px", borderRadius: 14, border: "none",
              background: canNext() && !loading
                ? `linear-gradient(135deg, ${C.green}, ${C.greenDark})`
                : C.border,
              color: C.white, fontSize: 14, fontWeight: 700,
              cursor: canNext() && !loading ? "pointer" : "not-allowed",
              fontFamily: "inherit",
            }}
          >
            {loading ? "Guardando..." : step === 3 ? "Empezar →" : step === 0 ? "Comenzar →" : "Continuar →"}
          </button>
        </div>

      </div>
    </div>
  );
}
