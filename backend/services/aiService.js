// ─────────────────────────────────────────────────────────────────────────────
// services/aiService.js  —  Mr. Money copiloto activo
//
// OPTIMIZACIÓN DE TOKENS:
// Las solicitudes "deducibles" (propuestas de desafíos, acciones que el sistema
// puede resolver localmente) se resuelven sin llamar a Anthropic cuando es posible.
// Claude solo se invoca cuando el mensaje requiere comprensión o razonamiento real.
// ─────────────────────────────────────────────────────────────────────────────

import Anthropic from "@anthropic-ai/sdk";
import {
  getSummary,
  getUserChallengesState,
  getUserProfile,
  getGoals,
  computeSimulation,
} from "./financeService.js";

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

const fmt = (n) =>
  new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n);

// ── Detección local — sin tokens ──────────────────────────────────────────────
// Patrones que pueden resolverse sin invocar a Claude.
// Si el mensaje del usuario coincide con alguno, se retorna la respuesta
// directamente con la propuesta correspondiente, ahorrando tokens completos.

const LOCAL_PATTERNS = [
  // Desafíos — el usuario pide directamente uno
  {
    match: /desaf[ií]o|reto|challenge/i,
    resolve: async (userId) => {
      const state = await getUserChallengesState(userId);
      if (!state.available?.length) {
        return { reply: "Ya tienes todos los desafíos activos o completados. 🏆 Sigue así." };
      }
      // Proponer el desafío disponible más relevante (mayor pts)
      const best = state.available.sort((a, b) => b.pts - a.pts)[0];
      return {
        reply: `Tengo un desafío que encaja con tu perfil 👇`,
        proposals: [{
          type:  "propose_challenge",
          id:    `local_ch_${best.id}`,
          input: { challenge_id: best.id, reasoning: `Es el desafío disponible con mejor relación esfuerzo/recompensa (${best.pts} pts, dificultad ${best.difficulty}).` },
        }],
      };
    },
  },
  // Saludo simple
  {
    match: /^(hola|buenas|hey|ey|hi|hello|buen[oa]s?\s*(días|tardes|noches)?)[\s!.]*$/i,
    resolve: async (userId) => {
      const summary = await getSummary(userId);
      const rate = summary.savingsRate;
      const emoji = rate >= 20 ? "📈" : rate >= 5 ? "📊" : "👀";
      return {
        reply: `Hola. ${emoji} Este mes llevas ${fmt(summary.expenses)} gastados de ${fmt(summary.income)} estimados. Tasa de ahorro: ${rate}%. ¿En qué te ayudo?`,
      };
    },
  },
];

// Intenta resolver el mensaje localmente. Retorna null si no puede.
async function tryResolveLocally(message, userId) {
  for (const pattern of LOCAL_PATTERNS) {
    if (pattern.match.test(message.trim())) {
      try {
        return await pattern.resolve(userId);
      } catch {
        return null; // Si falla, deja que Claude lo maneje
      }
    }
  }
  return null;
}

// ── Herramientas de Mr. Money ─────────────────────────────────────────────────
const MR_MONEY_TOOLS = [
  {
    name: "get_financial_projection",
    description:
      "Calcula proyección financiera: cuánto puede ahorrar el usuario por mes, " +
      "en cuántos meses alcanza un objetivo, y si es realista. " +
      "Úsala para preguntas sobre plazos, 'cuándo puedo lograr X', o 'cuánto necesito'.",
    input_schema: {
      type: "object",
      properties: {
        target_amount: { type: "number", description: "Monto objetivo en CLP. 0 para resumen general." },
        goal_name:     { type: "string", description: "Nombre del objetivo." },
      },
      required: ["target_amount", "goal_name"],
    },
  },
  {
    name: "navigate_to_simulation",
    description:
      "Lleva al usuario a la pestaña de simulaciones y precarga una simulación específica. " +
      "Úsala cuando el usuario pregunta qué pasa si reduce un gasto, o quiere explorar escenarios de ahorro. " +
      "SIEMPRE úsala en lugar de run_simulation cuando el usuario quiere 'ver' o 'explorar' simulaciones.",
    input_schema: {
      type: "object",
      properties: {
        simulation_type: {
          type: "string",
          enum: ["uber", "eating", "subs", "save5", "save10", "custom"],
          description: "Simulación a precargar en la pestaña.",
        },
        custom_amount: {
          type: "number",
          description: "Monto personalizado en CLP si simulation_type es custom.",
        },
        reason: {
          type: "string",
          description: "Frase corta explicando por qué esta simulación es relevante.",
        },
      },
      required: ["simulation_type", "reason"],
    },
  },
  {
    name: "propose_goal",
    description:
      "Propone crear una nueva meta financiera. NO la crea directamente — el usuario aprueba. " +
      "Úsala cuando el usuario expresa querer ahorrar para algo concreto.",
    input_schema: {
      type: "object",
      properties: {
        title:         { type: "string",  description: "Nombre de la meta." },
        target_amount: { type: "number",  description: "Monto objetivo en CLP." },
        deadline:      { type: "string",  description: "Fecha límite YYYY-MM-DD. Opcional." },
        reasoning:     { type: "string",  description: "Por qué esta meta tiene sentido para el usuario." },
      },
      required: ["title", "target_amount", "reasoning"],
    },
  },
  {
    name: "propose_delete_goal",
    description:
      "Propone eliminar una meta existente. NO la elimina directamente — el usuario confirma. " +
      "Úsala cuando el usuario dice que quiere borrar, cancelar o eliminar una meta.",
    input_schema: {
      type: "object",
      properties: {
        goal_id:    { type: "string", description: "ID de la meta a eliminar." },
        goal_title: { type: "string", description: "Nombre de la meta para mostrar al usuario." },
        reasoning:  { type: "string", description: "Contexto breve (ej: meta alcanzada, cambio de planes)." },
      },
      required: ["goal_id", "goal_title", "reasoning"],
    },
  },
  {
    name: "propose_challenge",
    description:
      "Propone activar un desafío basado en los patrones de gasto del usuario. " +
      "NO lo activa directamente — el usuario aprueba.",
    input_schema: {
      type: "object",
      properties: {
        challenge_id: {
          type: "string",
          enum: ["no_uber", "food_budget", "no_entert", "save_60k", "no_subs", "daily_track"],
          description: "ID del desafío.",
        },
        reasoning: { type: "string", description: "Por qué este desafío es relevante ahora." },
      },
      required: ["challenge_id", "reasoning"],
    },
  },
  {
    name: "propose_goal_contribution",
    description:
      "Propone añadir una cantidad a una meta existente. NO la ejecuta — el usuario aprueba. " +
      "Úsala cuando el usuario quiere abonar a una meta o tiene balance disponible.",
    input_schema: {
      type: "object",
      properties: {
        goal_id:    { type: "string", description: "ID de la meta." },
        goal_title: { type: "string", description: "Nombre de la meta." },
        amount:     { type: "number", description: "Monto a agregar en CLP." },
        reasoning:  { type: "string", description: "Por qué este aporte tiene sentido ahora." },
      },
      required: ["goal_id", "goal_title", "amount", "reasoning"],
    },
  },
];

// ── Contexto financiero completo ──────────────────────────────────────────────
async function buildFinancialContext(userId) {
  const [summary, challengesState, profile, goals] = await Promise.all([
    getSummary(userId),
    getUserChallengesState(userId),
    getUserProfile(userId),
    getGoals(userId),
  ]);

  const breakdown =
    Object.entries(summary.categoryTotals || {})
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `  - ${CATEGORY_LABELS[k] || k}: ${fmt(v)}`)
      .join("\n") || "  sin datos";

  const goalsText = goals?.length
    ? goals.map((g) =>
        `  - id:"${g.id}" "${g.title}": ${fmt(g.saved_amount || 0)}/${fmt(g.target_amount)} ` +
        `(${g.projection?.pct || 0}%, ~${g.projection?.monthsToGoal ?? "?"} meses)`
      ).join("\n")
    : "  sin metas";

  const availableChs = challengesState.available?.length
    ? challengesState.available.map((c) => `  - id:"${c.id}" "${c.label}" (${c.pts}pts, ${c.difficulty})`).join("\n")
    : "  ninguno disponible";

  const activeChs = challengesState.active?.length
    ? challengesState.active.map((c) => `  - "${c.label}" (${c.progress?.pct || 0}%)`).join("\n")
    : "  ninguno";

  return {
    text: `=== CONTEXTO FINANCIERO DE ${profile.user.name} (${summary.period}) ===
RESUMEN: Ingreso ${fmt(summary.income)} | Gastado ${fmt(summary.expenses)} | Balance ${fmt(summary.balance)} | Ahorro ${summary.savingsRate}%
TXS: ${summary.transactionCount} | Puntos: ${profile.points} | Nivel: ${profile.level}
GASTOS:\n${breakdown}
METAS:\n${goalsText}
DESAFÍOS ACTIVOS:\n${activeChs}
DESAFÍOS DISPONIBLES:\n${availableChs}
COMPLETADOS: ${challengesState.completed?.length || 0}`,
    raw: { summary, profile, goals },
  };
}

// ── System prompt ─────────────────────────────────────────────────────────────
function buildSystemPrompt(contextText) {
  return `Eres Mr. Money, copiloto financiero de Sky.

${contextText}

HERRAMIENTAS (úsalas cuando corresponda):
READ → get_financial_projection, navigate_to_simulation
WRITE (requieren aprobación del usuario) → propose_goal, propose_delete_goal, propose_challenge, propose_goal_contribution

CUÁNDO USARLAS:
- Usuario menciona meta/objetivo → propose_goal
- Usuario quiere eliminar una meta → propose_delete_goal
- Usuario pregunta "qué pasa si..." o simulaciones → navigate_to_simulation
- Usuario pregunta plazos/proyecciones → get_financial_projection
- Ves gasto alto en categoría → propose_challenge relevante
- Usuario tiene balance y metas incompletas → propose_goal_contribution

PERSONALIDAD: Profesional, directo, cercano. Fórmula: [dato real] + [emoción mínima] + [dirección].
REGLAS: Español. Datos reales siempre. Máx 4 líneas. 1-2 emojis. Sin asesoría de inversión. Sin decisiones por el usuario.`;
}

// ── Ejecutor herramientas READ ────────────────────────────────────────────────
async function executeTool(toolName, toolInput, userId, rawContext) {
  if (toolName === "get_financial_projection") {
    const { target_amount, goal_name } = toolInput;
    const monthly = Math.max(0, rawContext.summary.balance);

    if (target_amount === 0) {
      return {
        monthly_capacity: monthly,
        annual_capacity:  monthly * 12,
        savings_rate:     rawContext.summary.savingsRate,
        message: `Capacidad de ahorro: ${fmt(monthly)}/mes → ${fmt(monthly * 12)}/año.`,
      };
    }

    const months = monthly > 0 ? Math.ceil(target_amount / monthly) : null;
    const date   = months
      ? (() => { const d = new Date(); d.setMonth(d.getMonth() + months); return d.toLocaleDateString("es-CL", { month: "long", year: "numeric" }); })()
      : null;

    return {
      goal_name, target_amount, monthly_capacity: monthly,
      months_to_goal: months, projected_date: date, feasible: monthly > 0,
      message: months
        ? `"${goal_name}" (${fmt(target_amount)}): ~${months} meses ahorrando ${fmt(monthly)}/mes → ${date}.`
        : `Sin margen de ahorro actual. Reducir gastos primero.`,
    };
  }

  // navigate_to_simulation se procesa en el frontend — aquí solo confirmamos
  if (toolName === "navigate_to_simulation") {
    return {
      action:          "navigate",
      simulation_type: toolInput.simulation_type,
      custom_amount:   toolInput.custom_amount || null,
      message:         `Navegando a simulaciones con "${toolInput.simulation_type}".`,
    };
  }

  return { error: `Tool ${toolName} no reconocida` };
}

// ── Chat principal ────────────────────────────────────────────────────────────
export async function askMrMoney(userMessage, conversationHistory = [], userId = null) {

  // 1. Intentar resolver localmente (sin tokens)
  const local = await tryResolveLocally(userMessage, userId);
  if (local) return local;

  // 2. Construir contexto y llamar a Claude
  const context      = await buildFinancialContext(userId);
  const systemPrompt = buildSystemPrompt(context.text);

  const recentHistory = conversationHistory
    .slice(-6) // reducido de 8 a 6 para ahorrar tokens de contexto
    .filter((m) => m.role === "user" || m.role === "bot")
    .map((m) => ({ role: m.role === "bot" ? "assistant" : "user", content: m.text }));

  const messages = [...recentHistory, { role: "user", content: userMessage }];

  let response = await getClient().messages.create({
    model:      "claude-haiku-4-5-20251001", // Haiku para respuestas conversacionales → ~10x menos costo
    max_tokens: 800,                          // reducido de 1024
    system:     systemPrompt,
    tools:      MR_MONEY_TOOLS,
    messages,
  });

  // 3. Agentic loop
  const proposals  = [];
  const navigations = [];
  let finalText    = "";
  let iterations   = 0;

  while (response.stop_reason === "tool_use" && iterations < 3) {
    iterations++;

    const toolUseBlocks = response.content.filter((b) => b.type === "tool_use");
    const textBlocks    = response.content.filter((b) => b.type === "text");
    if (textBlocks.length) finalText += textBlocks.map((b) => b.text).join(" ") + " ";

    const toolResults = [];

    for (const tu of toolUseBlocks) {
      if (tu.name.startsWith("propose_")) {
        proposals.push({ type: tu.name, input: tu.input, id: tu.id });
        toolResults.push({
          type: "tool_result", tool_use_id: tu.id,
          content: JSON.stringify({ status: "proposal_queued" }),
        });
      } else if (tu.name === "navigate_to_simulation") {
        navigations.push({ simulation_type: tu.input.simulation_type, custom_amount: tu.input.custom_amount || null });
        toolResults.push({
          type: "tool_result", tool_use_id: tu.id,
          content: JSON.stringify({ action: "navigate", simulation_type: tu.input.simulation_type }),
        });
      } else {
        const result = await executeTool(tu.name, tu.input, userId, context.raw);
        toolResults.push({ type: "tool_result", tool_use_id: tu.id, content: JSON.stringify(result) });
      }
    }

    messages.push({ role: "assistant", content: response.content });
    messages.push({ role: "user",      content: toolResults });

    response = await getClient().messages.create({
      model:      "claude-haiku-4-5-20251001",
      max_tokens: 600,
      system:     systemPrompt,
      tools:      MR_MONEY_TOOLS,
      messages,
    });
  }

  const lastText = response.content.filter((b) => b.type === "text").map((b) => b.text).join(" ");
  finalText = (finalText + lastText).trim();

  return {
    reply:       finalText || "No pude procesar eso.",
    proposals:   proposals.length   ? proposals   : undefined,
    navigations: navigations.length ? navigations : undefined,
  };
}