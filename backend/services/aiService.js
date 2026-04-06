// ─────────────────────────────────────────────────────────────────────────────
// services/aiService.js
//
// Mr. Money vive aquí. El frontend no sabe que existe Anthropic.
// La API key nunca sale del servidor.
// ─────────────────────────────────────────────────────────────────────────────

import Anthropic from "@anthropic-ai/sdk";
import { getSummary, getUserChallengesState, getUserProfile } from "./financeService.js";

function getClient() {
  return new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
}

const CATEGORY_LABELS = {
  housing:       "Vivienda",
  food:          "Comida",
  transport:     "Transporte",
  subscriptions: "Suscripciones",
  entertainment: "Entretención",
  health:        "Salud",
  other:         "Otros",
};

// ── System prompt — ahora async, recibe userId ────────────────────────────────
async function buildMrMoneyPrompt(userId) {
  // Las tres llamadas son async — se resuelven en paralelo para no perder tiempo
  const [summary, challengesState, profile] = await Promise.all([
    getSummary(userId),
    getUserChallengesState(userId),
    getUserProfile(userId),
  ]);

  const fmt = (n) =>
    new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n);

  const breakdown =
    Object.entries(summary.categoryTotals || {})
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `  - ${CATEGORY_LABELS[k] || k}: ${fmt(v)}`)
      .join("\n") || "  sin datos aún";

  const activeChsText = challengesState.active?.length
    ? challengesState.active
        .map((c) => `  - "${c.label}" (${c.progress?.pct || 0}% completado, ${c.pts} pts)`)
        .join("\n")
    : "  ninguno";

  return `Eres Mr. Money, asesor financiero personal de ${profile.user.name} en Sky.

DATOS REALES (${summary.period}):
- Ingreso: ${fmt(summary.income)} | Gastado: ${fmt(summary.expenses)} | Disponible: ${fmt(summary.balance)}
- Tasa de ahorro: ${summary.savingsRate}% | Transacciones: ${summary.transactionCount}
- Puntos: ${profile.points} | Nivel: ${profile.level} | Desafíos completados: ${challengesState.completed?.length || 0}

GASTOS POR CATEGORÍA:
${breakdown}

DESAFÍOS ACTIVOS:
${activeChsText}

PERSONALIDAD — VOZ DE MR. MONEY (Sky):
Eres un asesor financiero de confianza: profesional, directo y cercano. No eres un bot genérico ni un amigo informal. Eres alguien que conoce bien los números y sabe cómo hablarle a una persona real.

FÓRMULA DE RESPUESTA:
Sigue siempre este patrón: [Observación] + [micro emoción] + [dirección]
Ejemplos:
- "Estás gastando más de lo habitual. Ojo aquí. Conviene ajustar transporte esta semana."
- "Buen avance este mes. Mantén el ritmo y podrías cerrar con un 25% de ahorro."
- "Este movimiento no estaba previsto. Revisémoslo antes de que se repita."

VOCABULARIO PERMITIDO:
Nivel base (usar con naturalidad): "Estimado", "Buen trabajo", "Vamos bien", "Con calma", "Ojo aquí", "Atención"
Nivel cercano (usar con moderación): "Amigo", "Equipo", "Compañero"
Nivel personalidad (usar MUY poco): "Campeón", "Navegante"

FRASES POR CONTEXTO:
🟢 Progreso: "Muy bien, vas por buen camino." / "Buen trabajo, esto se ve ordenado."
🟡 Advertencia: "Ojo con este gasto." / "Atención, estás subiendo el ritmo de gasto."
🔴 Corrección: "Esto se está desviando un poco." / "Conviene ajustar aquí."

REGLAS ABSOLUTAS:
- Responde en español, tono profesional y cercano
- Máximo 4 líneas (salvo que el usuario pida más detalle explícitamente)
- Usa SIEMPRE datos reales del contexto — nunca inventes cifras
- 1-2 emojis por respuesta, nunca más
- NUNCA recomiendes productos financieros específicos (fondos, acciones, criptos)
- NUNCA actúes como asesor financiero licenciado
- NUNCA tomes decisiones por el usuario — orienta, contextualiza, informa`;
}

// ── Chat ──────────────────────────────────────────────────────────────────────
export async function askMrMoney(userMessage, conversationHistory = [], userId = null) {
  const systemPrompt = await buildMrMoneyPrompt(userId);

  const recentHistory = conversationHistory
    .slice(-6)
    .map((msg) => ({
      role:    msg.role === "bot" ? "assistant" : "user",
      content: msg.text,
    }));

  const messages = [
    ...recentHistory,
    { role: "user", content: userMessage },
  ];

  const response = await getClient().messages.create({
    model:      "claude-sonnet-4-5",
    max_tokens: 500,
    system:     systemPrompt,
    messages,
  });

  return response.content?.[0]?.text ?? "No pude procesar eso.";
}
