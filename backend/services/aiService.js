// ─────────────────────────────────────────────────────────────────────────────
// services/aiService.js
//
// Mr. Money — copiloto activo con Tool Use.
// Puede leer datos, proponer acciones, y ejecutarlas con aprobación del usuario.
// La API key nunca sale del servidor. El frontend no sabe que existe Anthropic.
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

// ── Herramientas de Mr. Money ─────────────────────────────────────────────────
const MR_MONEY_TOOLS = [
  {
    name: "get_financial_projection",
    description:
      "Calcula la proyección financiera del usuario: cuánto puede ahorrar por mes, " +
      "en cuántos meses alcanza una meta específica, y cómo se compara con sus metas actuales. " +
      "Úsala cuando el usuario pregunta por proyecciones, plazos, o 'cuándo puedo lograr X'.",
    input_schema: {
      type: "object",
      properties: {
        target_amount: {
          type: "number",
          description: "Monto objetivo en CLP para calcular proyección. Puede ser 0 para mostrar solo el resumen.",
        },
        goal_name: {
          type: "string",
          description: "Nombre descriptivo del objetivo a proyectar.",
        },
      },
      required: ["target_amount", "goal_name"],
    },
  },
  {
    name: "run_simulation",
    description:
      "Corre una simulación de ahorro para mostrar cuánto dinero ahorra el usuario " +
      "si reduce un tipo de gasto. Úsala cuando el usuario pregunta qué pasa si gasto menos en X " +
      "o cuando quieres mostrar el impacto de un cambio de hábito.",
    input_schema: {
      type: "object",
      properties: {
        simulation_type: {
          type: "string",
          enum: ["uber", "eating", "subs", "save5", "save10", "custom"],
          description: "Tipo de simulación a correr.",
        },
        custom_amount: {
          type: "number",
          description: "Monto mensual personalizado en CLP (solo para simulation_type=custom).",
        },
      },
      required: ["simulation_type"],
    },
  },
  {
    name: "propose_goal",
    description:
      "Propone crear una nueva meta financiera al usuario. NO la crea directamente. " +
      "Genera una propuesta que el usuario debe aprobar en la interfaz. " +
      "Úsala cuando el usuario expresa que quiere ahorrar para algo concreto, " +
      "o cuando detectas que una meta sería útil según sus datos.",
    input_schema: {
      type: "object",
      properties: {
        title: {
          type: "string",
          description: "Nombre claro de la meta (ej: Viaje a Perú, Fondo de emergencia).",
        },
        target_amount: {
          type: "number",
          description: "Monto objetivo en CLP.",
        },
        deadline: {
          type: "string",
          description: "Fecha límite en formato YYYY-MM-DD. Opcional.",
        },
        reasoning: {
          type: "string",
          description: "Explicación breve de por qué esta meta tiene sentido para el usuario según sus datos.",
        },
      },
      required: ["title", "target_amount", "reasoning"],
    },
  },
  {
    name: "propose_challenge",
    description:
      "Propone activar un desafío específico al usuario basándose en sus patrones de gasto. " +
      "NO lo activa directamente. Genera una propuesta para que el usuario apruebe. " +
      "Úsala cuando detectas un área de gasto que el usuario podría mejorar.",
    input_schema: {
      type: "object",
      properties: {
        challenge_id: {
          type: "string",
          enum: ["no_uber", "food_budget", "no_entert", "save_60k", "no_subs", "daily_track"],
          description: "ID del desafío a proponer.",
        },
        reasoning: {
          type: "string",
          description: "Por qué este desafío es relevante para el usuario ahora.",
        },
      },
      required: ["challenge_id", "reasoning"],
    },
  },
  {
    name: "propose_goal_contribution",
    description:
      "Propone añadir una cantidad a una meta existente del usuario. " +
      "Úsala cuando el usuario dice que quiere abonar a una meta o cuando detectas " +
      "que tiene balance disponible que podría asignar a una meta en progreso.",
    input_schema: {
      type: "object",
      properties: {
        goal_id: {
          type: "string",
          description: "ID de la meta existente.",
        },
        goal_title: {
          type: "string",
          description: "Nombre de la meta para mostrar al usuario.",
        },
        amount: {
          type: "number",
          description: "Monto a agregar en CLP.",
        },
        reasoning: {
          type: "string",
          description: "Por qué este aporte tiene sentido ahora.",
        },
      },
      required: ["goal_id", "goal_title", "amount", "reasoning"],
    },
  },
];

// ── Construcción del contexto financiero completo ─────────────────────────────
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
      .join("\n") || "  sin datos aún";

  const activeChsText = challengesState.active?.length
    ? challengesState.active
        .map((c) => `  - "${c.label}" (${c.progress?.pct || 0}% completado, ${c.pts} pts)`)
        .join("\n")
    : "  ninguno activo";

  const availableChsText = challengesState.available?.length
    ? challengesState.available
        .map((c) => `  - id:"${c.id}" "${c.label}" (${c.pts} pts, ${c.difficulty})`)
        .join("\n")
    : "  ninguno disponible";

  const goalsText = goals?.length
    ? goals
        .map(
          (g) =>
            `  - id:"${g.id}" "${g.title}": ${fmt(g.saved_amount || 0)} / ${fmt(g.target_amount)} ` +
            `(${g.projection?.pct || 0}%, ~${g.projection?.monthsToGoal ?? "?"} meses al ritmo actual)`
        )
        .join("\n")
    : "  sin metas definidas";

  return {
    text: `=== CONTEXTO FINANCIERO DE ${profile.user.name} (${summary.period}) ===

RESUMEN MENSUAL:
- Ingreso estimado: ${fmt(summary.income)}
- Gastado este mes: ${fmt(summary.expenses)}
- Disponible (balance): ${fmt(summary.balance)}
- Tasa de ahorro: ${summary.savingsRate}% | Tasa de gasto: ${summary.spendingRate}%
- Transacciones registradas: ${summary.transactionCount}
- Puntos: ${profile.points} | Nivel: ${profile.level}

GASTOS POR CATEGORÍA:
${breakdown}

METAS ACTUALES:
${goalsText}

DESAFÍOS ACTIVOS:
${activeChsText}

DESAFÍOS DISPONIBLES (para proponer si son relevantes):
${availableChsText}

DESAFÍOS COMPLETADOS: ${challengesState.completed?.length || 0}`,
    raw: { summary, challengesState, profile, goals },
  };
}

// ── System prompt ──────────────────────────────────────────────────────────────
function buildSystemPrompt(contextText) {
  return `Eres Mr. Money, el copiloto financiero personal de Sky.

${contextText}

=== TU ROL COMO COPILOTO ACTIVO ===

Tienes herramientas que te permiten actuar, no solo hablar.

HERRAMIENTAS READ (ejecutas directamente):
- get_financial_projection: calcula proyecciones y plazos en tiempo real
- run_simulation: muestra el impacto de reducir un tipo de gasto

HERRAMIENTAS WRITE (propones, el usuario aprueba):
- propose_goal: propones crear una meta nueva
- propose_challenge: propones activar un desafío
- propose_goal_contribution: propones abonar a una meta existente

CUÁNDO USAR HERRAMIENTAS:
- Usuario menciona algo que quiere lograr → propose_goal
- Ves gasto alto en una categoría → propose_challenge relevante
- Usuario pregunta "¿cuándo puedo...?" o "¿cuánto necesito...?" → get_financial_projection
- Usuario pregunta "¿qué pasa si...?" → run_simulation
- Usuario tiene balance libre y metas incompletas → propose_goal_contribution

REGLAS DE PROPUESTAS:
- Explica siempre el razonamiento antes de proponer
- Una propuesta por mensaje máximo
- Si el usuario rechazó una propuesta, no la repitas

PERSONALIDAD:
Profesional, directo y cercano. Fórmula: [Observación de datos] + [micro emoción] + [dirección concreta].

REGLAS ABSOLUTAS:
- Responde en español
- Usa SIEMPRE datos reales del contexto, nunca inventes cifras
- Máximo 4 líneas de texto libre (más propuesta si corresponde)
- 1-2 emojis por respuesta
- NUNCA recomiendes activos de inversión específicos
- NUNCA actúes como asesor financiero licenciado
- NUNCA decidas por el usuario — orienta, propón, informa`;
}

// ── Ejecutor de herramientas READ ─────────────────────────────────────────────
async function executeTool(toolName, toolInput, userId, rawContext) {
  if (toolName === "get_financial_projection") {
    const { target_amount, goal_name } = toolInput;
    const { summary } = rawContext;
    const monthlyBalance = Math.max(0, summary.balance);

    if (target_amount === 0) {
      return {
        monthly_savings_capacity: monthlyBalance,
        annual_savings_capacity: monthlyBalance * 12,
        current_savings_rate: summary.savingsRate,
        message: `Con el balance actual de ${fmt(monthlyBalance)}/mes, el usuario puede ahorrar ${fmt(monthlyBalance * 12)} al año.`,
      };
    }

    const monthsToGoal = monthlyBalance > 0 ? Math.ceil(target_amount / monthlyBalance) : null;
    const projectedDate = monthsToGoal
      ? (() => {
          const d = new Date();
          d.setMonth(d.getMonth() + monthsToGoal);
          return d.toLocaleDateString("es-CL", { month: "long", year: "numeric" });
        })()
      : null;

    return {
      goal_name,
      target_amount,
      monthly_savings_capacity: monthlyBalance,
      months_to_goal: monthsToGoal,
      projected_completion: projectedDate,
      is_feasible: monthlyBalance > 0,
      message: monthsToGoal
        ? `Para "${goal_name}" (${fmt(target_amount)}): ahorrando ${fmt(monthlyBalance)}/mes, se logra en ~${monthsToGoal} meses (${projectedDate}).`
        : `Con el balance actual no hay margen de ahorro. Primero hay que reducir gastos.`,
    };
  }

  if (toolName === "run_simulation") {
    const result = await computeSimulation(userId, toolInput.simulation_type, toolInput.custom_amount || null);
    if (!result) return { error: "Simulación no encontrada" };
    return {
      simulation_type: toolInput.simulation_type,
      monthly_saving: result.monthlySaving,
      in_3_months: result.months3,
      in_6_months: result.months6,
      in_12_months: result.months12,
      message: `Si aplica este cambio: ${fmt(result.monthlySaving)}/mes → ${fmt(result.months12)} en 12 meses.`,
    };
  }

  return { error: `Tool ${toolName} no es ejecutable server-side` };
}

// ── Chat principal ────────────────────────────────────────────────────────────
export async function askMrMoney(userMessage, conversationHistory = [], userId = null) {
  const context = await buildFinancialContext(userId);
  const systemPrompt = buildSystemPrompt(context.text);

  const recentHistory = conversationHistory
    .slice(-8)
    .filter((m) => m.role === "user" || m.role === "bot")
    .map((msg) => ({
      role:    msg.role === "bot" ? "assistant" : "user",
      content: msg.text,
    }));

  const messages = [
    ...recentHistory,
    { role: "user", content: userMessage },
  ];

  let response = await getClient().messages.create({
    model:      "claude-sonnet-4-5",
    max_tokens: 1024,
    system:     systemPrompt,
    tools:      MR_MONEY_TOOLS,
    messages,
  });

  // Agentic loop: ejecutar herramientas READ, capturar propuestas WRITE
  const proposals = [];
  let finalText   = "";
  let iterations  = 0;
  const MAX_ITER  = 3;

  while (response.stop_reason === "tool_use" && iterations < MAX_ITER) {
    iterations++;

    const toolUseBlocks = response.content.filter((b) => b.type === "tool_use");
    const textBlocks    = response.content.filter((b) => b.type === "text");

    if (textBlocks.length > 0) {
      finalText += textBlocks.map((b) => b.text).join(" ") + " ";
    }

    const toolResults = [];

    for (const toolUse of toolUseBlocks) {
      const isProposal = toolUse.name.startsWith("propose_");

      if (isProposal) {
        proposals.push({ type: toolUse.name, input: toolUse.input, id: toolUse.id });
        toolResults.push({
          type:        "tool_result",
          tool_use_id: toolUse.id,
          content:     JSON.stringify({ status: "proposal_queued", message: "Propuesta lista para mostrar al usuario." }),
        });
      } else {
        const result = await executeTool(toolUse.name, toolUse.input, userId, context.raw);
        toolResults.push({
          type:        "tool_result",
          tool_use_id: toolUse.id,
          content:     JSON.stringify(result),
        });
      }
    }

    messages.push({ role: "assistant", content: response.content });
    messages.push({ role: "user",      content: toolResults });

    response = await getClient().messages.create({
      model:      "claude-sonnet-4-5",
      max_tokens: 800,
      system:     systemPrompt,
      tools:      MR_MONEY_TOOLS,
      messages,
    });
  }

  const lastText = response.content
    .filter((b) => b.type === "text")
    .map((b) => b.text)
    .join(" ");

  finalText = (finalText + lastText).trim();

  return {
    reply:     finalText || "No pude procesar eso.",
    proposals: proposals.length > 0 ? proposals : undefined,
  };
}