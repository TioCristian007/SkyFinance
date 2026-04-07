// components/SimulationChart.jsx
import { useState, useMemo } from "react";
import { C } from "../data/colors.js";

const fmt  = (n) => new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n);
const fmtK = (n) => n >= 1000000 ? `$${(n/1000000).toFixed(1)}M` : n >= 1000 ? `$${Math.round(n/1000)}K` : `$${n}`;

// Estimaciones como % del ingreso cuando no hay datos reales
const FALLBACK_PCT = { food: 0.18, transport: 0.12, entertainment: 0.08, subscriptions: 0.06, other: 0.10 };

const SLIDERS = [
  { id: "food",          label: "🍕 Delivery / Comida",  color: "#FF6B6B" },
  { id: "transport",     label: "🚗 Transporte (Uber)",  color: "#4ECDC4" },
  { id: "entertainment", label: "🎮 Entretención",        color: "#A78BFA" },
  { id: "subscriptions", label: "📺 Suscripciones",       color: "#F59E0B" },
  { id: "other",         label: "💳 Otros gastos",        color: "#6B7A8D" },
];

export default function SimulationChart({ summary, goals = [], initialSimType = null }) {
  const [cuts, setCuts] = useState(() => {
    const base = { food: 0, transport: 0, entertainment: 0, subscriptions: 0, other: 0 };
    if (initialSimType === "uber")   base.transport = 60;
    if (initialSimType === "eating") base.food = 40;
    if (initialSimType === "subs")   base.subscriptions = 50;
    return base;
  });

  const income          = summary?.income   || 0;
  const currentExpenses = summary?.expenses || 0;
  const currentBalance  = Math.max(0, income - currentExpenses);
  const catTotals       = summary?.categoryTotals || {};
  const hasRealData     = Object.values(catTotals).some((v) => v > 0);

  // Si no hay datos reales, usar estimaciones basadas en el income
  const spentByCategory = useMemo(() => {
    const result = {};
    SLIDERS.forEach((s) => {
      result[s.id] = catTotals[s.id] > 0
        ? catTotals[s.id]
        : Math.round(income * FALLBACK_PCT[s.id]);
    });
    return result;
  }, [catTotals, income]);

  const totalMonthlySaving = useMemo(() =>
    SLIDERS.reduce((sum, s) =>
      sum + Math.round(spentByCategory[s.id] * (cuts[s.id] / 100)), 0),
  [cuts, spentByCategory]);

  const newBalance  = currentBalance + totalMonthlySaving;
  const savingsRate = income > 0 ? Math.round((newBalance / income) * 100) : 0;

  const goalProjections = useMemo(() =>
    goals.slice(0, 3).map((g) => {
      const remaining    = Math.max(0, (g.target_amount || 0) - (g.saved_amount || 0));
      const oldMonths    = currentBalance > 0 ? Math.ceil(remaining / currentBalance) : null;
      const newMonths    = newBalance > 0      ? Math.ceil(remaining / newBalance)     : null;
      const improvement  = (oldMonths && newMonths) ? oldMonths - newMonths : 0;
      return { ...g, remaining, oldMonths, newMonths, improvement };
    }),
  [goals, currentBalance, newBalance]);

  const setCut   = (id, val) => setCuts((prev) => ({ ...prev, [id]: val }));
  const resetAll = () => setCuts({ food: 0, transport: 0, entertainment: 0, subscriptions: 0, other: 0 });
  const hasAnyCut = Object.values(cuts).some((v) => v > 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

      {/* Resumen antes / después */}
      <div style={{ background: C.white, borderRadius: 18, padding: "16px 18px", border: `1px solid ${C.border}` }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>Simulador de recortes</div>
            <div style={{ fontSize: 11.5, color: C.textSecondary, marginTop: 2 }}>
              {hasRealData ? "Basado en tus gastos reales" : "Estimación basada en tu ingreso"}
            </div>
          </div>
          {hasAnyCut && (
            <button onClick={resetAll} style={{
              padding: "4px 10px", borderRadius: 20, border: `1px solid ${C.border}`,
              background: "transparent", fontSize: 11, color: C.textSecondary, cursor: "pointer",
            }}>Resetear</button>
          )}
        </div>

        <div style={{ display: "flex", gap: 12, marginBottom: totalMonthlySaving > 0 ? 12 : 0 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 10, color: C.textMuted, marginBottom: 4, fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase" }}>
              Ahorro actual / mes
            </div>
            <div style={{ fontSize: 22, fontWeight: 800, color: currentBalance > 0 ? C.textPrimary : C.red }}>
              {fmtK(currentBalance)}
            </div>
          </div>
          {totalMonthlySaving > 0 && (
            <>
              <div style={{ display: "flex", alignItems: "center", fontSize: 20, color: C.green, fontWeight: 700 }}>→</div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 10, color: C.green, marginBottom: 4, fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase" }}>
                  Con recortes / mes
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color: C.green }}>{fmtK(newBalance)}</div>
              </div>
            </>
          )}
        </div>

        {totalMonthlySaving > 0 && (
          <div>
            <div style={{ height: 8, background: C.border, borderRadius: 99, overflow: "hidden" }}>
              <div style={{
                height: "100%", borderRadius: 99,
                width: `${Math.min(100, income > 0 ? (newBalance / income) * 100 : 0)}%`,
                background: `linear-gradient(90deg,${C.green},${C.greenDark})`,
                transition: "width 0.25s ease",
              }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
              <span style={{ fontSize: 11, color: C.textMuted }}>Tasa de ahorro: {savingsRate}%</span>
              <span style={{ fontSize: 11, color: C.green, fontWeight: 700 }}>+{fmtK(totalMonthlySaving)}/mes</span>
            </div>
          </div>
        )}
      </div>

      {/* Sliders — siempre habilitados */}
      <div style={{ background: C.white, borderRadius: 18, padding: "16px 18px", border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: C.textSecondary, marginBottom: 14, letterSpacing: "0.04em", textTransform: "uppercase" }}>
          ¿Cuánto recortarías?
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {SLIDERS.map((s) => {
            const spent  = spentByCategory[s.id];
            const pct    = cuts[s.id];
            const saving = Math.round(spent * (pct / 100));
            const isEst  = !catTotals[s.id];

            return (
              <div key={s.id}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <span style={{ fontSize: 13, color: C.textPrimary }}>{s.label}</span>
                  <div style={{ textAlign: "right" }}>
                    <span style={{ fontSize: 11.5, color: C.textSecondary }}>
                      {fmt(spent)}{isEst ? <span style={{ color: C.textMuted, fontSize: 10 }}> est.</span> : null}
                    </span>
                    {saving > 0 && (
                      <span style={{ fontSize: 12, color: s.color, fontWeight: 700, marginLeft: 8 }}>
                        −{fmtK(saving)}
                      </span>
                    )}
                  </div>
                </div>

                <input
                  type="range"
                  min="0"
                  max="100"
                  step="5"
                  value={pct}
                  onChange={(e) => setCut(s.id, parseInt(e.target.value))}
                  style={{ width: "100%", cursor: "pointer", accentColor: s.color }}
                />

                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 3 }}>
                  <span style={{ fontSize: 10, color: C.textMuted }}>0%</span>
                  {pct > 0 && (
                    <span style={{ fontSize: 11, color: s.color, fontWeight: 600 }}>
                      Recortando {pct}%
                    </span>
                  )}
                  <span style={{ fontSize: 10, color: C.textMuted }}>100%</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Impacto en metas */}
      {goalProjections.length > 0 && totalMonthlySaving > 0 && (
        <div style={{ background: C.white, borderRadius: 18, padding: "16px 18px", border: `1.5px solid ${C.green}` }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: C.green, marginBottom: 12, letterSpacing: "0.04em", textTransform: "uppercase" }}>
            Impacto en tus metas
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {goalProjections.map((g) => (
              <div key={g.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px", background: C.bg, borderRadius: 12 }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>{g.title}</div>
                  <div style={{ fontSize: 11.5, color: C.textSecondary }}>
                    {g.oldMonths ? `Antes: ${g.oldMonths} meses` : "Sin proyección base"}
                    {g.improvement > 0 && (
                      <span style={{ color: C.green, fontWeight: 700, marginLeft: 6 }}>
                        → {g.newMonths} meses
                      </span>
                    )}
                  </div>
                </div>
                {g.improvement > 0 && (
                  <div style={{ background: C.greenLight, borderRadius: 10, padding: "6px 10px", textAlign: "center" }}>
                    <div style={{ fontSize: 15, fontWeight: 800, color: C.greenDark }}>−{g.improvement}</div>
                    <div style={{ fontSize: 9, color: C.greenDark }}>meses</div>
                  </div>
                )}
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12, padding: "10px 12px", background: C.greenLight, borderRadius: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 12, color: C.greenDark, fontWeight: 600 }}>Ahorro extra en 12 meses</span>
            <span style={{ fontSize: 16, fontWeight: 800, color: C.greenDark }}>{fmtK(totalMonthlySaving * 12)}</span>
          </div>
        </div>
      )}

    </div>
  );
}