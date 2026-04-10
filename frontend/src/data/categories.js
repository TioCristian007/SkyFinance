// data/categories.js
//
// Definición COMPLETA de categorías del sistema.
// Cubre las 16 categorías que el backend puede asignar (categorizerService.js).
//
// ANTES: solo 7 categorías → categorías como shopping, utilities, housing
//        caían sin icono/color y el frontend las mostraba como "Otros".
//
// AHORA: 16 categorías con icono, color, y label en español.
//        Las 7 categorías originales mantienen keys idénticas (no rompe datos).
//
// Orden: de mayor a menor frecuencia esperada en usuario promedio chileno.

export const CATEGORIES = [
  // ── Alta frecuencia ────────────────────────────────────────────────────────
  { key: "food",          label: "Comida",           icon: "🍔", color: "#7B1FA2", bg: "#F3E5F5" },
  { key: "transport",     label: "Transporte",        icon: "🚌", color: "#F57C00", bg: "#FFF3E0" },
  { key: "shopping",      label: "Compras",           icon: "🛍️", color: "#C62828", bg: "#FFEBEE" },
  { key: "subscriptions", label: "Suscripciones",     icon: "📱", color: "#00838F", bg: "#E0F7FA" },
  { key: "entertainment", label: "Entretención",      icon: "🎮", color: "#AD1457", bg: "#FCE4EC" },

  // ── Servicios esenciales ───────────────────────────────────────────────────
  { key: "utilities",     label: "Servicios básicos", icon: "💡", color: "#F9A825", bg: "#FFFDE7" },
  { key: "housing",       label: "Vivienda",          icon: "🏠", color: "#1565C0", bg: "#E3F2FD" },
  { key: "health",        label: "Salud",             icon: "💊", color: "#2E7D32", bg: "#E8F5E9" },

  // ── Finanzas personales ────────────────────────────────────────────────────
  { key: "debt_payment",  label: "Cuotas y créditos", icon: "💳", color: "#4527A0", bg: "#EDE7F6" },
  { key: "savings",       label: "Ahorro",            icon: "🏦", color: "#00695C", bg: "#E0F2F1" },
  { key: "insurance",     label: "Seguros",           icon: "🛡️", color: "#37474F", bg: "#ECEFF1" },
  { key: "transfer",      label: "Transferencia",     icon: "↔️",  color: "#5D4037", bg: "#EFEBE9" },
  { key: "banking_fee",   label: "Comisión bancaria", icon: "🏛️", color: "#78909C", bg: "#F5F5F5" },

  // ── Inversión y desarrollo ─────────────────────────────────────────────────
  { key: "education",     label: "Educación",         icon: "📚", color: "#1B5E20", bg: "#F1F8E9" },
  { key: "income",        label: "Ingreso",           icon: "💰", color: "#33691E", bg: "#F9FBE7" },

  // ── Fallback ───────────────────────────────────────────────────────────────
  { key: "other",         label: "Otros",             icon: "📦", color: "#6B7A8D", bg: "#F0F2F5" },
];

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Mapa key → objeto categoría para lookup O(1) */
export const CATEGORY_MAP = Object.fromEntries(
  CATEGORIES.map((c) => [c.key, c])
);

/**
 * Devuelve la categoría por key.
 * Si la key no existe (ej: dato legacy o error backend) → retorna "other".
 * Nunca retorna undefined.
 */
export function getCategory(key) {
  return CATEGORY_MAP[key] ?? CATEGORY_MAP["other"];
}

/**
 * Categorías que representan gastos (para cálculo de totales y gráficos).
 * Excluye income, transfer (neutral), savings (realmente es movimiento de dinero).
 */
export const EXPENSE_CATEGORIES = CATEGORIES.filter(
  (c) => !["income", "transfer", "savings"].includes(c.key)
);

/**
 * Categorías que el usuario puede seleccionar al agregar una transacción manual.
 * Excluye banking_fee e income (se asignan automáticamente por el sistema).
 */
export const MANUAL_CATEGORIES = CATEGORIES.filter(
  (c) => !["banking_fee", "income"].includes(c.key)
);