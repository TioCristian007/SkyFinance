// data/challenges.js
// Templates de desafíos y definiciones de badges.
// IMPORTANTE: estos son solo los datos de presentación (labels, iconos, colores).
// La lógica de progreso y el estado (activo/completado) viven en el backend.

export const CHALLENGE_TEMPLATES = [
  { id: "no_uber",     label: "Sin Uber 7 días",         icon: "🚗", desc: "No gastes en transporte esta semana", category: "transport",     limitAmt: 0,     days: 7,  pts: 150, difficulty: "Medio"   },
  { id: "food_budget", label: "Comida bajo $80K",         icon: "🍔", desc: "Gasta menos de $80.000 en comida",   category: "food",          limitAmt: 80000, days: 30, pts: 200, difficulty: "Difícil" },
  { id: "no_entert",   label: "Sin entretención 5 días",  icon: "🎮", desc: "Pausa el gasto en ocio 5 días",      category: "entertainment", limitAmt: 0,     days: 5,  pts: 100, difficulty: "Fácil"   },
  { id: "save_60k",    label: "Ahorra $60K este mes",     icon: "💰", desc: "Reduce gastos para ahorrar $60.000", category: null,            limitAmt: 60000, days: 30, pts: 250, difficulty: "Difícil" },
  { id: "no_subs",     label: "Cancela 1 suscripción",    icon: "📺", desc: "Elimina una suscripción que no usas",category: "subscriptions", limitAmt: 0,     days: 1,  pts: 80,  difficulty: "Fácil"   },
  { id: "daily_track", label: "Registra 5 gastos",        icon: "📝", desc: "Anota 5 transacciones en la app",   category: null,            limitAmt: 5,     days: 7,  pts: 120, difficulty: "Fácil"   },
];

export const BADGES = [
  { id: "first_tx",    label: "Primera TX",   icon: "✏️" },
  { id: "saver",       label: "Ahorrador",    icon: "💰" },
  { id: "disciplined", label: "Disciplinado", icon: "🎯" },
  { id: "tracker",     label: "Rastreador",   icon: "📊" },
  { id: "century",     label: "100 puntos",   icon: "⭐" },
  { id: "elite",       label: "Elite Sky",    icon: "🏆" },
];
// Nota: las condiciones para ganar badges (pts >= X, txs >= Y) viven
// en backend/services/financeService.js → evaluateBadges()
