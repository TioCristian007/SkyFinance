// data/categories.js
// Definición de categorías de gasto.
// El frontend las usa para mostrar iconos, colores y labels.
// El backend las usa en financeService para calcular totales.

export const CATEGORIES = [
  { key: "food",          label: "Comida",        icon: "🍔", color: "#7B1FA2", bg: "#F3E5F5" },
  { key: "transport",     label: "Transporte",     icon: "🚌", color: "#F57C00", bg: "#FFF3E0" },
  { key: "entertainment", label: "Entretención",   icon: "🎮", color: "#AD1457", bg: "#FCE4EC" },
  { key: "subscriptions", label: "Suscripciones",  icon: "📱", color: "#00838F", bg: "#E0F7FA" },
  { key: "housing",       label: "Vivienda",       icon: "🏠", color: "#1565C0", bg: "#E3F2FD" },
  { key: "health",        label: "Salud",          icon: "💊", color: "#2E7D32", bg: "#E8F5E9" },
  { key: "other",         label: "Otros",          icon: "📦", color: "#6B7A8D", bg: "#F0F2F5" },
];
