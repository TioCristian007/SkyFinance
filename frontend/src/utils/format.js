// utils/format.js
// Helpers de formato y fechas. Puro JavaScript, sin React.
// Se importan donde se necesiten — no viven dentro de ningún componente.

import { CATEGORIES } from "../data/categories.js";

/** Formato moneda CLP: $1.200.000 */
export const fmt = (n) =>
  new Intl.NumberFormat("es-CL", {
    style: "currency",
    currency: "CLP",
    maximumFractionDigits: 0,
  }).format(n);

/** Formato compacto: $1.2M, $850K, etc. */
export const fmtK = (n) =>
  n >= 1_000_000
    ? `$${(n / 1_000_000).toFixed(1)}M`
    : n >= 1_000
    ? `$${Math.round(n / 1_000)}K`
    : fmt(n);

/** Fecha YYYY-MM-DD → "12 mar" */
export const fmtDate = (d) => {
  const [, m, day] = d.split("-");
  const meses = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];
  return `${parseInt(day)} ${meses[parseInt(m) - 1]}`;
};

/** Fecha de hoy en YYYY-MM-DD */
export const today = () => new Date().toISOString().split("T")[0];

/** Hora actual en HH:MM */
export const nowTime = () =>
  new Date().toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" });

/** Devuelve la categoría por key, fallback a "Otros" */
export const catOf = (key) =>
  CATEGORIES.find((c) => c.key === key) ?? CATEGORIES.at(-1);
