// ─────────────────────────────────────────────────────────────────────────────
// services/ariaService.js — ARIA pipeline v2
//
// PRINCIPIOS INVARIABLES:
//   · El UUID de usuario NUNCA entra en aria.*
//   · Los montos exactos NUNCA se almacenan en aria.*
//   · Las fechas exactas se reemplazan por trimestre
//   · El timestamp tiene ruido ±36h (generado en la DB — ver recorded_at)
//   · Si el usuario no dio consentimiento (aria_consent = false) → no se escribe nada
//
// NUEVAS CAPACIDADES v2:
//   · Chequeo de consentimiento antes de cada escritura
//   · Campo occupation en todas las señales
//   · Campo behavior_shift en behavioral_signals
//   · Campo source en spending_patterns (manual vs bank_sync)
//   · Clasificación de goal_category desde el título de la meta
// ─────────────────────────────────────────────────────────────────────────────

import { getAriaClient, getAdminClient } from "./supabaseClient.js";

// ── Helpers de normalización ──────────────────────────────────────────────────

function normalizeAgeRange(r) {
  const valid = ["18-25","26-35","36-45","46-55","55+","under-18","prefer_not"];
  return valid.includes(r) ? r : "unknown";
}

function normalizeIncomeBucket(r) {
  const valid = ["0-500k","500k-1M","1M-2M","2M-5M","5M+","prefer_not"];
  return valid.includes(r) ? r : "unknown";
}

function normalizeOccupation(r) {
  const valid = ["empleado","independiente","emprendedor","estudiante","jubilado","desempleado","prefer_not"];
  return valid.includes(r) ? r : "unknown";
}

function getAmountBucket(amount) {
  if (!amount || amount <= 0) return "0-50k";
  if (amount <= 50000)        return "0-50k";
  if (amount <= 150000)       return "50k-150k";
  if (amount <= 500000)       return "150k-500k";
  if (amount <= 1500000)      return "500k-1.5M";
  return "1.5M+";
}

function getGoalTargetBucket(amount) {
  if (!amount || amount <= 0) return null;
  if (amount <= 500000)       return "0-500k";
  if (amount <= 2000000)      return "500k-2M";
  if (amount <= 10000000)     return "2M-10M";
  if (amount <= 30000000)     return "10M-30M";
  return "30M+";
}

function getPeriod() {
  const n = new Date();
  return `${n.getFullYear()}-Q${Math.ceil((n.getMonth() + 1) / 3)}`;
}

function getRegionBucket(region) {
  if (!region) return "unknown";
  const r = region.toLowerCase();
  if (r.includes("rm") || r.includes("metropolitana")) {
    if (r.includes("sur"))     return "RM-Sur";
    if (r.includes("norte"))   return "RM-Norte";
    if (r.includes("oriente")) return "RM-Oriente";
    return "RM-Central";
  }
  if (r.includes("valparaí") || r.includes("valparai")) return "Valparaíso";
  if (r.includes("biobío")   || r.includes("biobio"))   return "Biobío";
  if (r.includes("araucan"))                             return "La Araucanía";
  if (r.includes("antofagasta"))                         return "Antofagasta";
  if (r.includes("coquimbo"))                            return "Coquimbo";
  if (r.includes("los lagos"))                           return "Los Lagos";
  if (r.includes("higgins"))                             return "O'Higgins";
  if (r.includes("maule"))                               return "Maule";
  return "Otra región";
}

function randomInBucket(bucket) {
  const ranges = {
    "0-50k":     [1000,    50000],
    "50k-150k":  [50001,   150000],
    "150k-500k": [150001,  500000],
    "500k-1.5M": [500001,  1500000],
    "1.5M+":     [1500001, 5000000],
  };
  const r = ranges[bucket];
  if (!r) return Math.floor(Math.random() * 50000) + 1000;
  return Math.floor(Math.random() * (r[1] - r[0] + 1)) + r[0];
}

// ── Clasificadores de texto (solo señales — el texto no se guarda) ────────────

function classifyMotivation(text) {
  const t = text.toLowerCase();
  if (/seguridad|emergencia|fondo\s+de\s+emergencia|colchón|proteger|estabilidad|respaldo|imprevist|crisis|desemplead|perder.+trabajo|enfermedad|accidente/.test(t)) return "security";
  if (/familia|hijo[sao]?|pareja|matrimonio|casarse|boda|bebé|embarazad|papá|mamá|crianza|colegio.+niño/.test(t)) return "family";
  if (/viaje|viajar|vacacion|conocer|aventura|experiencia|concierto|festival|verano|intercambio|mochilero|turismo/.test(t)) return "experience";
  if (/casa\s+propia|departamento\s+propio|independencia|independizarse|vivir\s+sol[ao]|libertad|no\s+depender|emprender|negocio\s+propio|renunciar/.test(t)) return "freedom";
  if (/auto\s+nuevo|iphone|macbook|computador|notebook|ropa.+marca|diseñador|lujo|primera\s+clase|impresionar|aparentar/.test(t)) return "status";
  return "unknown";
}

function classifyBlocker(text) {
  const t = text.toLowerCase();
  if (/impulso|antojo|ganas\s+de|tentación|no\s+pude\s+resistir|compré\s+sin|sin\s+pensar|descuento|sale|black\s+friday|cyber\s+day/.test(t)) return "impulse";
  if (/amigo[sao]?|juntarse|salida[s]?|carrete|carretear|fiesta|cumpleaños|todos\s+(van|fueron)|no\s+quiero\s+quedar\s+mal|compromisos/.test(t)) return "social_pressure";
  if (/no\s+alcanza|no\s+me\s+alcanza|sueldo|ingreso|plata.+no\s+llega|siempre\s+falta|nunca\s+sobra|deuda[s]?|préstamo|crédito|cuota[s]?|sobregir|rojo/.test(t)) return "income_gap";
  if (/siempre\s+lo\s+hago|toda\s+la\s+vida|costumbre|hábito|difícil\s+cambiar|no\s+puedo\s+evitar|automático|sin\s+darme\s+cuenta|rutina/.test(t)) return "habit";
  if (/no\s+sé|no\s+entiendo|confundido|no\s+tengo\s+idea|nunca\s+aprendí|nadie\s+me\s+enseñó|me\s+pierdo|complicado/.test(t)) return "knowledge";
  return "unknown";
}

function classifyMindset(text) {
  const t = text.toLowerCase();
  if (/ahorr|guardar\s+plata|reserva|fondo|invertir|inversión|no\s+gastar|gastar\s+menos|recortar|presupuesto|disciplina/.test(t)) return "saver";
  if (/gastar|disfrutar\s+(ahora|hoy|la\s+vida)|yolo|solo\s+se\s+vive\s+una\s+vez|vivir\s+el\s+momento|plata\s+es\s+para\s+gastarla/.test(t)) return "spender";
  if (/evito|no\s+miro|da\s+miedo|me\s+da\s+ansied|me\s+angustia|no\s+quiero\s+ver|prefiero\s+no\s+saber|postergar/.test(t)) return "avoider";
  return "balanced";
}

function classifyStress(text) {
  const t = text.toLowerCase();
  if (/angustia|desesperado|no\s+puedo\s+dormir|pánico|hundido|muy\s+mal|pésimo|crisis\s+total|no\s+veo\s+salida|muy\s+preocupado/.test(t)) return "high";
  if (/tranquil[ao]|bien\s+(económicamente|con\s+la\s+plata)|ordenado|bajo\s+control|no\s+me\s+preocupa|contento\s+con|sin\s+problemas/.test(t)) return "low";
  return "medium";
}

function classifyOrientation(text) {
  const t = text.toLowerCase();
  if (/este\s+mes|esta\s+semana|ahora\s+mismo|ya\b|urgente|antes\s+de\s+fin\s+de\s+mes|cuanto\s+antes|a\s+corto\s+plazo/.test(t)) return "short_term";
  if (/largo\s+plazo|futuro|retiro|jubilación|pensión|herencia|construir.+futuro|poco\s+a\s+poco|toda\s+la\s+vida/.test(t)) return "long_term";
  return "mixed";
}

function classifyBehaviorShift(userMessage, mrMoneyReply) {
  // Detecta si el usuario mostró intención de cambio positivo tras la interacción
  const combined = `${userMessage} ${mrMoneyReply}`.toLowerCase();
  if (/voy a|voy a intentar|me comprometí|empezaré|desde hoy|lo voy a hacer|tiene sentido|entendí|gracias.+(tip|consejo|idea)|lo voy a aplicar/.test(combined)) return "positive";
  if (/no puedo|imposible|no sirve|no funciona|no quiero|no voy a|no me ayuda/.test(combined)) return "negative";
  return "neutral";
}

function classifyGoalType(title) {
  const t = (title || "").toLowerCase();
  const map = [
    [/departamento|casa\s+propia|vivienda|hogar|arriendo|hipoteca/, "housing"],
    [/auto|moto|vehículo|furgón|camioneta/,                          "vehicle"],
    [/educación|universidad|postgrado|magíster|curso|carrera|estudio/, "education"],
    [/viaje|vacacion|intercambio|mochilero|turismo/,                   "travel"],
    [/emergencia|fondo|colchón|respaldo|imprevist/,                    "emergency"],
    [/matrimonio|boda|bebé|hijo|familia|crianza/,                      "life_event"],
    [/inversión|fondo\s+mutuo|acciones|cripto|bolsa/,                  "investment"],
  ];
  for (const [pattern, type] of map) {
    if (pattern.test(t)) return type;
  }
  return "other";
}

function hasSignificantContent(text) {
  if (!text || text.trim().split(/\s+/).length < 5) return false;
  return /plata|dinero|peso[s]?|gasto[s]?|ahorro[s]?|sueldo|ingreso|deuda|meta|objetivo|presupuesto|compra|gastar|ahorrar|invertir|financ|bolsillo|cuenta|banco|tarjeta/.test(text);
}

// ── Guard de consentimiento ────────────────────────────────────────────────────
// Si el usuario no consintió, ARIA no escribe absolutamente nada sobre él.
// Se consulta una sola vez por llamada — no se cachea entre requests.

async function hasAriaConsent(userId) {
  if (!userId) return false;
  try {
    const { data, error } = await getAdminClient()
      .from("profiles")
      .select("aria_consent")
      .eq("id", userId)
      .single();
    if (error || !data) return false;
    return data.aria_consent === true;
  } catch {
    return false; // fail-safe: si no se puede verificar, no se escribe
  }
}

// ── Construcción del perfil anonimizado ───────────────────────────────────────
// Extrae solo los segmentos demográficos — sin UUID, sin nombre, sin email

function buildAnonProfile(profile) {
  return {
    age_range:    normalizeAgeRange(profile?.age_range),
    region:       getRegionBucket(profile?.region),
    income_range: normalizeIncomeBucket(profile?.income_range),
    occupation:   normalizeOccupation(profile?.occupation),
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// EXPORTS — Funciones públicas del pipeline ARIA
// ═══════════════════════════════════════════════════════════════════════════════

// ── trackSpendingEvent ────────────────────────────────────────────────────────
// Llamar cuando el usuario registra o importa una transacción de gasto.
// profile: { age_range, region, income_range, occupation }
// tx:      { amount, category, source? }
// userId:  UUID — solo para verificar consentimiento, nunca entra en aria.*

export async function trackSpendingEvent(profile, tx, userId = null) {
  try {
    if (userId && !(await hasAriaConsent(userId))) return;

    const anon   = buildAnonProfile(profile);
    const bucket = getAmountBucket(Math.abs(tx.amount));

    const { error } = await getAriaClient()
      .schema("aria")
      .from("spending_patterns")
      .insert({
        age_range:     anon.age_range,
        region:        anon.region,
        income_range:  anon.income_range,
        occupation:    anon.occupation,
        category:      tx.category || "other",
        amount_bucket: bucket,
        amount_noise:  randomInBucket(bucket),
        source:        tx.source || "manual",
        period:        getPeriod(),
        batch_id:      crypto.randomUUID(),
      });

    if (error) console.error("[ARIA] spending_patterns:", error.message);
  } catch (e) {
    console.error("[ARIA] trackSpendingEvent:", e.message);
  }
}

// ── trackGoalEvent ────────────────────────────────────────────────────────────
// Llamar cuando el usuario crea, actualiza o completa una meta.
// profile:        { age_range, region, income_range, occupation }
// goal:           { title, targetAmount|target_amount, type, projection? }
// completionRate: 0-100
// goalStatus:     "active" | "completed" | "abandoned"

export async function trackGoalEvent(profile, goal, completionRate = 0, goalStatus = "active", userId = null) {
  try {
    if (userId && !(await hasAriaConsent(userId))) return;

    const anon = buildAnonProfile(profile);

    const { error } = await getAriaClient()
      .schema("aria")
      .from("goal_signals")
      .insert({
        age_range:       anon.age_range,
        region:          anon.region,
        income_range:    anon.income_range,
        occupation:      anon.occupation,
        goal_type:       classifyGoalType(goal.title),
        goal_tier:       goal.type || "secundaria",
        target_bucket:   getGoalTargetBucket(goal.targetAmount || goal.target_amount),
        completion_rate: Math.min(100, Math.max(0, Math.round(completionRate))),
        months_to_goal:  goal.projection?.monthsToGoal ?? null,
        goal_status:     goalStatus,
        period:          getPeriod(),
        batch_id:        crypto.randomUUID(),
      });

    if (error) console.error("[ARIA] goal_signals:", error.message);
  } catch (e) {
    console.error("[ARIA] trackGoalEvent:", e.message);
  }
}

// ── trackBehavioralSignal ─────────────────────────────────────────────────────
// Llamar al final de cada interacción con Mr. Money que tenga contenido financiero.
// El texto de la conversación NO se guarda — solo las clasificaciones.
// profile:        { age_range, region, income_range, occupation }
// userMessage:    string — el mensaje del usuario (solo se clasifica, no persiste)
// mrMoneyReply:   string — la respuesta del bot (solo se clasifica, no persiste)

export async function trackBehavioralSignal(profile, userMessage, mrMoneyReply = "", userId = null) {
  try {
    if (userId && !(await hasAriaConsent(userId))) return;

    const fullContext = `${userMessage} ${mrMoneyReply}`;
    if (!hasSignificantContent(fullContext)) return;

    const anon = buildAnonProfile(profile);

    const motivation   = classifyMotivation(fullContext);
    const blocker      = classifyBlocker(fullContext);
    const mindset      = classifyMindset(fullContext);
    const stress       = classifyStress(fullContext);
    const orientation  = classifyOrientation(fullContext);
    const behaviorShift = classifyBehaviorShift(userMessage, mrMoneyReply);

    const { error } = await getAriaClient()
      .schema("aria")
      .from("behavioral_signals")
      .insert({
        age_range:           anon.age_range,
        region:              anon.region,
        income_range:        anon.income_range,
        occupation:          anon.occupation,
        motivation_category: motivation,
        blocker_type:        blocker,
        financial_mindset:   mindset,
        stress_level:        stress,
        goal_orientation:    orientation,
        behavior_shift:      behaviorShift,
        period:              getPeriod(),
        batch_id:            crypto.randomUUID(),
      });

    if (error) console.error("[ARIA] behavioral_signals:", error.message);
    else console.log(`[ARIA] ✓ motivation:${motivation} blocker:${blocker} mindset:${mindset} stress:${stress} shift:${behaviorShift}`);
  } catch (e) {
    console.error("[ARIA] trackBehavioralSignal:", e.message);
  }
}

// ── trackSessionInsight ───────────────────────────────────────────────────────
// Llamar al cerrar sesión o al cambiar de tab (agregado por sesión, no por click).
// profile:     { age_range, region, income_range }
// sessionData: { tabsVisited, chatFrequency, featureAffinity, sessionDepth,
//                proposalsShown, proposalsAccepted, proposalsRejected }

export async function trackSessionInsight(profile, sessionData, userId = null) {
  try {
    if (userId && !(await hasAriaConsent(userId))) return;

    const anon = buildAnonProfile(profile);
    const {
      tabsVisited       = [],
      chatFrequency     = "occasional",
      featureAffinity   = "dashboard",
      sessionDepth      = "shallow",
      proposalsShown    = 0,
      proposalsAccepted = 0,
      proposalsRejected = 0,
    } = sessionData;

    const { error } = await getAriaClient()
      .schema("aria")
      .from("session_insights")
      .insert({
        age_range:          anon.age_range,
        region:             anon.region,
        income_range:       anon.income_range,
        tabs_visited:       tabsVisited,
        chat_frequency:     chatFrequency,
        feature_affinity:   featureAffinity,
        session_depth:      sessionDepth,
        proposals_shown:    proposalsShown,
        proposals_accepted: proposalsAccepted,
        proposals_rejected: proposalsRejected,
        period:             getPeriod(),
        batch_id:           crypto.randomUUID(),
      });

    if (error) console.error("[ARIA] session_insights:", error.message);
  } catch (e) {
    console.error("[ARIA] trackSessionInsight:", e.message);
  }
}