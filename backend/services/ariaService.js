// ─────────────────────────────────────────────────────────────────────────────
// services/ariaService.js — ARIA pipeline completo
// El UUID nunca toca aria.*
// Los valores exactos nunca tocan aria.*
// ─────────────────────────────────────────────────────────────────────────────

import { getAriaClient } from "./supabaseClient.js";

function normalizeAgeRange(r) {
  return ["18-25","26-35","36-45","46-55","55+","under-18"].includes(r) ? r : "unknown";
}

function getAmountBucket(amount) {
  if (!amount || amount <= 0) return "0";
  if (amount <= 50000)        return "0-50k";
  if (amount <= 150000)       return "50k-150k";
  if (amount <= 500000)       return "150k-500k";
  if (amount <= 1500000)      return "500k-1.5M";
  return "1.5M+";
}

function getIncomeBucket(r) {
  return ["0-500k","500k-1M","1M-2M","2M+","unknown"].includes(r) ? r : "unknown";
}

function getPeriod() {
  const n = new Date();
  return `${n.getFullYear()}-Q${Math.ceil((n.getMonth()+1)/3)}`;
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
  if (r.includes("araucan"))   return "La Araucanía";
  if (r.includes("antofagasta")) return "Antofagasta";
  if (r.includes("coquimbo"))    return "Coquimbo";
  if (r.includes("los lagos"))   return "Los Lagos";
  if (r.includes("higgins"))     return "O'Higgins";
  if (r.includes("maule"))       return "Maule";
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
  if (!r) return 0;
  return Math.floor(Math.random() * (r[1] - r[0] + 1)) + r[0];
}

function newBatchId() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function classifyMotivation(text) {
  if (/seguridad|emergencia|fondo\s+de\s+emergencia|colchón|proteger|estabilidad|respaldo|imprevist|crisis|desemplead|perder.+trabajo|enfermedad|accidente/.test(text)) return "security";
  if (/familia|hijo[sao]?|pareja|matrimonio|casarse|boda|bebé|embarazad|papá|mamá|crianza|colegio.+niño/.test(text)) return "family";
  if (/viaje|viajar|vacacion|conocer|aventura|experiencia|concierto|festival|verano|intercambio|mochilero|turismo/.test(text)) return "experience";
  if (/casa\s+propia|departamento\s+propio|independencia|independizarse|vivir\s+sol[ao]|libertad|no\s+depender|emprender|negocio\s+propio|renunciar/.test(text)) return "freedom";
  if (/auto\s+nuevo|iphone|macbook|computador|notebook|ropa.+marca|diseñador|lujo|primera\s+clase|impresionar|aparentar/.test(text)) return "status";
  return "unknown";
}

function classifyBlocker(text) {
  if (/impulso|antojo|ganas\s+de|tentación|no\s+pude\s+resistir|compré\s+sin|sin\s+pensar|descuento|sale|black\s+friday|cyber\s+day/.test(text)) return "impulse";
  if (/amigo[sao]?|juntarse|salida[s]?|carrete|carretear|fiesta|cumpleaños|todos\s+(van|fueron)|no\s+quiero\s+quedar\s+mal|compromisos/.test(text)) return "social_pressure";
  if (/no\s+alcanza|no\s+me\s+alcanza|sueldo|ingreso|plata.+no\s+llega|siempre\s+falta|nunca\s+sobra|deuda[s]?|préstamo|crédito|cuota[s]?|sobregir|rojo/.test(text)) return "income_gap";
  if (/siempre\s+lo\s+hago|toda\s+la\s+vida|costumbre|hábito|difícil\s+cambiar|no\s+puedo\s+evitar|automático|sin\s+darme\s+cuenta|rutina/.test(text)) return "habit";
  if (/no\s+sé|no\s+entiendo|confundido|no\s+tengo\s+idea|nunca\s+aprendí|nadie\s+me\s+enseñó|me\s+pierdo|complicado/.test(text)) return "knowledge";
  return "unknown";
}

function classifyMindset(text) {
  if (/ahorr|guardar\s+plata|reserva|fondo|invertir|inversión|no\s+gastar|gastar\s+menos|recortar|presupuesto|disciplina/.test(text)) return "saver";
  if (/gastar|disfrutar\s+(ahora|hoy|la\s+vida)|yolo|solo\s+se\s+vive\s+una\s+vez|vivir\s+el\s+momento|plata\s+es\s+para\s+gastarla/.test(text)) return "spender";
  if (/evito|no\s+miro|da\s+miedo|me\s+da\s+ansied|me\s+angustia|no\s+quiero\s+ver|prefiero\s+no\s+saber|postergar/.test(text)) return "avoider";
  return "balanced";
}

function classifyStress(text) {
  if (/angustia|desesperado|no\s+puedo\s+dormir|pánico|hundido|muy\s+mal|pésimo|crisis\s+total|no\s+veo\s+salida|muy\s+preocupado/.test(text)) return "high";
  if (/tranquil[ao]|bien\s+(económicamente|con\s+la\s+plata)|ordenado|bajo\s+control|no\s+me\s+preocupa|contento\s+con|sin\s+problemas/.test(text)) return "low";
  return "medium";
}

function classifyOrientation(text) {
  if (/este\s+mes|esta\s+semana|ahora\s+mismo|ya\b|urgente|antes\s+de\s+fin\s+de\s+mes|cuanto\s+antes|a\s+corto\s+plazo/.test(text)) return "short_term";
  if (/largo\s+plazo|futuro|retiro|jubilación|pensión|herencia|construir.+futuro|poco\s+a\s+poco|toda\s+la\s+vida/.test(text)) return "long_term";
  return "mixed";
}

function hasSignificantContent(text) {
  if (text.trim().split(/\s+/).length < 5) return false;
  return /plata|dinero|peso[s]?|gasto[s]?|ahorro[s]?|sueldo|ingreso|deuda|meta|objetivo|presupuesto|compra|gastar|ahorrar|invertir|financ|bolsillo|cuenta|banco|tarjeta/.test(text);
}

// ── Exports ───────────────────────────────────────────────────────────────────

export async function trackSpendingEvent(profile, tx) {
  try {
    const bucket = getAmountBucket(tx.amount);
    const { error } = await getAriaClient().schema("aria").from("spending_patterns").insert({
      age_range:     normalizeAgeRange(profile.age_range),
      region:        getRegionBucket(profile.region),
      income_range:  getIncomeBucket(profile.income_range),
      category:      tx.category,
      amount_bucket: bucket,
      amount_noise:  randomInBucket(bucket),
      period:        getPeriod(),
      batch_id:      newBatchId(),
    });
    if (error) console.error("[ARIA] spending_patterns:", error.message);
  } catch (e) { console.error("[ARIA] trackSpendingEvent:", e.message); }
}

export async function trackGoalEvent(profile, goal, completionRate = 0) {
  try {
    const typeMap = {
      "departamento":"housing","casa":"housing","arriendo":"housing","vivienda":"housing",
      "auto":"vehicle","moto":"vehicle","vehículo":"vehicle",
      "viaje":"travel","vacaciones":"travel",
      "educación":"education","estudio":"education","carrera":"education",
      "emergencia":"emergency","fondo":"emergency","colchón":"emergency",
      "matrimonio":"life_event","bebé":"life_event","boda":"life_event","hijo":"life_event",
    };
    const titleLower = (goal.title || "").toLowerCase();
    let goalType = "other";
    for (const [kw, type] of Object.entries(typeMap)) {
      if (titleLower.includes(kw)) { goalType = type; break; }
    }
    const { error } = await getAriaClient().schema("aria").from("goal_signals").insert({
      age_range:       normalizeAgeRange(profile.age_range),
      region:          getRegionBucket(profile.region),
      income_range:    getIncomeBucket(profile.income_range),
      goal_type:       goalType,
      goal_tier:       goal.type || "secundaria",
      target_bucket:   getAmountBucket(goal.targetAmount || goal.target_amount),
      completion_rate: Math.min(100, Math.max(0, Math.round(completionRate))),
      months_to_goal:  goal.projection?.monthsToGoal ?? null,
      period:          getPeriod(),
      batch_id:        newBatchId(),
    });
    if (error) console.error("[ARIA] goal_signals:", error.message);
  } catch (e) { console.error("[ARIA] trackGoalEvent:", e.message); }
}

export async function trackBehavioralSignal(profile, userMessage, mrMoneyReply = "") {
  try {
    const fullContext = `${userMessage} ${mrMoneyReply}`.toLowerCase();
    if (!hasSignificantContent(fullContext)) return;

    const motivation  = classifyMotivation(fullContext);
    const blocker     = classifyBlocker(fullContext);
    const mindset     = classifyMindset(fullContext);
    const stress      = classifyStress(fullContext);
    const orientation = classifyOrientation(fullContext);

    const { error } = await getAriaClient().schema("aria").from("behavioral_signals").insert({
      age_range:           normalizeAgeRange(profile.age_range),
      region:              getRegionBucket(profile.region),
      income_range:        getIncomeBucket(profile.income_range),
      motivation_category: motivation,
      blocker_type:        blocker,
      financial_mindset:   mindset,
      stress_level:        stress,
      goal_orientation:    orientation,
      period:              getPeriod(),
      batch_id:            newBatchId(),
    });

    if (error) console.error("[ARIA] behavioral_signals:", error.message);
    else console.log(`[ARIA] ✓ motivation:${motivation} blocker:${blocker} mindset:${mindset} stress:${stress} orientation:${orientation}`);
  } catch (e) { console.error("[ARIA] trackBehavioralSignal:", e.message); }
}

export async function trackSessionInsight(profile, sessionData) {
  try {
    const { tabsVisited = [], chatFrequency, featureAffinity, sessionDepth } = sessionData;
    const { error } = await getAriaClient().schema("aria").from("session_insights").insert({
      age_range:        normalizeAgeRange(profile.age_range),
      region:           getRegionBucket(profile.region),
      tabs_visited:     tabsVisited,
      chat_frequency:   chatFrequency   || "occasional",
      feature_affinity: featureAffinity || "dashboard",
      session_depth:    sessionDepth    || "shallow",
      period:           getPeriod(),
      batch_id:         newBatchId(),
    });
    if (error) console.error("[ARIA] session_insights:", error.message);
  } catch (e) { console.error("[ARIA] trackSessionInsight:", e.message); }
}