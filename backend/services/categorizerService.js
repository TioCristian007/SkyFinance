// ─────────────────────────────────────────────────────────────────────────────
// services/categorizerService.js  (v3)
//
// FIX CRÍTICO v3:
//   El lookup de Layer 2 usaba coincidencia EXACTA de string.
//   "jumbo las condes" nunca matcheaba con "jumbo" en la cache.
//   Ahora genera variantes de prefijo: intenta ["jumbo las condes",
//   "jumbo las", "jumbo"] hasta encontrar match.
//   Esto resuelve por qué casi todo aparecía como "other" incluso
//   con merchant_categories correctamente poblada.
// ─────────────────────────────────────────────────────────────────────────────

import Anthropic          from "@anthropic-ai/sdk";
import { getAdminClient } from "./supabaseClient.js";

const db     = () => getAdminClient();
let _client = null;
const client = () => {
  if (!_client) _client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  return _client;
};

export const CATEGORIES = [
  "food", "transport", "subscriptions", "entertainment",
  "health", "education", "housing", "insurance", "utilities",
  "shopping", "debt_payment", "savings", "transfer",
  "banking_fee", "income", "other",
];

// ── CAPA 1: Reglas deterministas ──────────────────────────────────────────────

const LAYER1_RULES = [
  { test: (d, a) => a > 0 && /^traspaso\s+de:/i.test(d),                                              cat: "income"       },
  { test: (d, a) => a > 0 && /abono|remuner|sueldo|salario|honorario|liquidaci/i.test(d),             cat: "income"       },
  { test: (d, a) => a > 0 && /devoluci[oó]n\s*(imp|sii)|reintegro/i.test(d),                         cat: "income"       },
  { test: (d, a) => a < 0 && /^traspaso\s+a:/i.test(d),                                               cat: "transfer"     },
  { test: (d, a) => a < 0 && /khipu|transferencia\s+a:/i.test(d),                                     cat: "transfer"     },
  { test: (d)    => /^comisi[oó]n|iva\s+comisi[oó]n|mantenci[oó]n\s+cta|cargo\s+mantenci/i.test(d),  cat: "banking_fee"  },
  { test: (d)    => /bip[!\s]|red\s+movilidad|transantiago/i.test(d),                                 cat: "transport"    },
  { test: (d)    => /pago:metro\s|metro\s+(de\s+santiago|baquedano|universidad|plaza|santa\s+ana)/i.test(d), cat: "transport" },
  { test: (d)    => /\bcopec\b|\bshell\b|\bpetrobras\b|\benex\b|\besso\b/i.test(d),                  cat: "transport"    },
  { test: (d)    => /\bnetflix\b|\bspotify\b|\bdisney\+|\bhbo\s*max\b|\byoutube\s*premium\b|\bamazon\s*prime\b|\bcrunchyroll\b|\bstar\+/i.test(d), cat: "subscriptions" },
  { test: (d)    => /pago:(entel|movistar|claro|wom|vtr|gtd)\b/i.test(d),                            cat: "utilities"    },
  { test: (d)    => /salcobrand|cruz\s*verde|ahumada|dr\.?\s*simi/i.test(d),                         cat: "health"       },
  { test: (d)    => /pago\s+tar(jeta)?\s+cr[eé]d|pago\s+tc\b/i.test(d),                             cat: "debt_payment" },
  { test: (d)    => /dep[oó]sito\s+plazo|dap\b|fondo\s+mutuo|\bapv\b|aporte\s+afp/i.test(d),        cat: "savings"      },
  { test: (d)    => /\bjumbo\b|\blider\b|\btottus\b|\bsanta\s+isabel\b|\bunimarc\b|\bacuenta\b|\bekono\b|\bmayor[i1]sta\s*10\b/i.test(d), cat: "food" },
  { test: (d)    => /\bstarbucks\b|\bmcdonald|\bburger\s*king\b|\bsubway\b|\bdominos\b|\bpizza\s*hut\b|\btelepi[zs]za\b|\bkfc\b/i.test(d), cat: "food" },
  { test: (d)    => /\brappi\b|\bpedidos\s*ya\b|\buber\s*eats\b|\bcornershop\b/i.test(d),           cat: "food"         },
  { test: (d)    => /\boxxo\b|\baramco\b|\btake\s*[&y]?\s*go\b|\bpronto\s*copec\b/i.test(d),        cat: "food"         },
  { test: (d)    => /\buber\b(?!\s*eats)|\bcabify\b|\bindriver\b|\bdidi\b|\beasy\s*taxi\b/i.test(d), cat: "transport"    },
  { test: (d)    => /\bfalabella\b|\bripley\b|\bhites\b|\bsodimac\b|\bhomecenter\b/i.test(d),        cat: "shopping"     },
  { test: (d)    => /\bisapre\b|\bfonasa\b|\bbanmedica\b|\bconsalud\b|\bcolmena\b|\bvidaintegra\b|\bintegram[eé]dica\b/i.test(d), cat: "health" },
  { test: (d)    => /\bchilectra\b|\benel\b(?!\s*x)|\baguas\s+andinas\b|\bmetrogas\b|\bessbio\b|\besval\b/i.test(d), cat: "utilities" },
];

function applyLayer1(description, amount) {
  for (const rule of LAYER1_RULES) {
    if (rule.test(description, amount)) return rule.cat;
  }
  return null;
}

// ── Normalización ──────────────────────────────────────────────────────────────

export function normalizeMerchant(description) {
  return description
    .toLowerCase()
    .replace(/^pago\s*:\s*/i,          "")
    .replace(/^cargo\s*:\s*/i,         "")
    .replace(/^compra\s+comercio\s*/i, "")
    .replace(/^compra\s+internet\s*/i, "")
    .replace(/^pago\s+internet\s*/i,   "")
    .replace(/mercadopago\*/i,         "mercadopago ")
    .replace(/[*_\-\.]{2,}/g,         " ")
    .replace(/\s{2,}/g,               " ")
    .trim()
    .substring(0, 60);
}

// Genera variantes de prefijo:
// "jumbo las condes" → ["jumbo las condes", "jumbo las", "jumbo"]
function generateKeyVariants(merchantKey) {
  if (!merchantKey) return [];
  const words    = merchantKey.split(" ").filter(Boolean);
  const variants = [];
  for (let i = words.length; i >= 1; i--) {
    variants.push(words.slice(0, i).join(" "));
  }
  return variants;
}

// ── CAPA 2: Cache con prefix matching ─────────────────────────────────────────

async function lookupCache(merchantKeys) {
  if (!merchantKeys.length) return {};

  const allVariants = [...new Set(
    merchantKeys.flatMap(k => generateKeyVariants(k))
  )].filter(Boolean);

  if (!allVariants.length) return {};

  const { data, error } = await db()
    .from("merchant_categories")
    .select("merchant_key, category")
    .in("merchant_key", allVariants);

  if (error) {
    console.error("[categorizer] C2 lookup error:", error.message);
    return {};
  }

  const variantMap = {};
  for (const row of data || []) variantMap[row.merchant_key] = row.category;

  // Resolver cada key original usando sus variantes (de más larga a más corta)
  const result = {};
  for (const key of merchantKeys) {
    for (const v of generateKeyVariants(key)) {
      if (variantMap[v]) { result[key] = variantMap[v]; break; }
    }
  }

  return result;
}

async function saveToCache(entries) {
  if (!entries.length) return;
  await Promise.allSettled(
    entries.map(({ merchant_key, category, source, confidence }) =>
      db().rpc("upsert_merchant_category", {
        p_merchant_key: merchant_key,
        p_category:     category,
        p_source:       source ?? "ai",
        p_confidence:   confidence ?? null,
      }).catch(e => console.error("[categorizer] cache write:", e.message))
    )
  );
}

// ── CAPA 3: Claude Haiku ──────────────────────────────────────────────────────

const CATEGORIZER_SYSTEM = `Eres un clasificador de transacciones bancarias chilenas.
Recibirás nombres de comercios ya normalizados (sin "Pago:", en minúsculas).
Responde SOLO con un array JSON. Sin texto extra, sin markdown.

Categorías:
food        → supermercados, restoranes, cafeterías, delivery, kioscos, conveniencia, almacenes
transport   → metro, uber, cabify, taxi, bencina, peajes, estacionamiento, buses, vuelos
subscriptions → streaming (netflix,spotify,disney+), software SaaS, membresías digitales
entertainment → cines, juegos, eventos, bares, discotecas, libros
health      → farmacias, médicos, clínicas, ópticas, isapre, laboratorios
education   → universidades, colegios, cursos, academias, preuniversitarios
housing     → arriendo, dividendo, condominio, gastos comunes, mudanza
insurance   → seguros vida/auto/hogar
utilities   → luz, agua, gas, teléfono, internet, cable
shopping    → ropa, tecnología, muebles, mascotas, retail general
debt_payment → cuotas crédito, pago tarjeta, cuota préstamo
savings     → DAP, fondos mutuos, APV, cuenta ahorro
transfer    → traspasos entre personas
banking_fee → comisiones, mantención, IVA bancario
other       → solo si realmente no se puede clasificar

Reglas Chile:
- "aramco", "oxxo", "take go", "pronto copec" → food
- "jumbo las condes", "lider pudahuel" (ciudad al final) → food por el supermercado
- "mimar", "petco", "puppis" → shopping
- "mercadopago" + nombre → categoriza por el negocio que sigue
- confidence < 0.75 → usar "other"

Formato EXACTO (solo esto):
[{"key":"nombre","category":"food","confidence":0.95},...]`;

async function categorizeWithAI(merchantKeys) {
  if (!merchantKeys.length) return {};
  try {
    const response = await client().messages.create({
      model:      "claude-haiku-4-5-20251001",
      max_tokens: 1024,
      system:     CATEGORIZER_SYSTEM,
      messages:   [{ role: "user", content: `Clasifica:\n${JSON.stringify(merchantKeys)}` }],
    });

    const raw  = response.content[0]?.text?.trim() ?? "[]";
    // Claude a veces envuelve el JSON en markdown fences (```json ... ```)
    const cleaned = raw.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "").trim();
    const data = JSON.parse(cleaned);
    const result = {}; const toCache = [];

    for (const item of data) {
      const cat = (item.confidence >= 0.75 && CATEGORIES.includes(item.category))
        ? item.category : "other";
      result[item.key] = cat;
      toCache.push({ merchant_key: item.key, category: cat, source: "ai", confidence: item.confidence ?? null });
    }

    saveToCache(toCache).catch(() => {});
    return result;
  } catch (e) {
    console.error("[categorizer] AI error:", e.message);
    return {};
  }
}

// ── Función principal ─────────────────────────────────────────────────────────

export async function categorizeMovements(rawMovements, bankId) {
  if (!Array.isArray(rawMovements) || !rawMovements.length) return [];

  const normalized = rawMovements
    .filter(m => m && m.amount !== undefined && parseInt(m.amount) !== 0)
    .map((m, idx) => ({
      idx,
      raw:         m,
      amount:      parseInt(m.amount ?? 0),
      rawDesc:     (m.description ?? "").trim(),
      merchantKey: normalizeMerchant((m.description ?? "").trim()),
      date:        normalizeDate(m.date),
      source:      m.source ?? "account",
      externalId:  m.id ?? null,
    }));

  const results = new Map(); const needsCache = [];

  for (const mov of normalized) {
    const cat = applyLayer1(mov.rawDesc, mov.amount);
    if (cat) results.set(mov.idx, cat);
    else     needsCache.push(mov);
  }
  console.log(`[categorizer] C1: ${results.size}/${normalized.length} resueltos`);

  const uniqueKeys = [...new Set(needsCache.map(m => m.merchantKey))].filter(Boolean);
  const cacheHits  = await lookupCache(uniqueKeys);
  const needsAI    = [];

  for (const mov of needsCache) {
    if (cacheHits[mov.merchantKey]) results.set(mov.idx, cacheHits[mov.merchantKey]);
    else                            needsAI.push(mov);
  }
  console.log(`[categorizer] C2: ${needsCache.length - needsAI.length} desde cache`);

  if (needsAI.length > 0) {
    const uniqueAIKeys = [...new Set(needsAI.map(m => m.merchantKey))].filter(Boolean);
    const aiResults    = {};
    for (let i = 0; i < uniqueAIKeys.length; i += 20) {
      Object.assign(aiResults, await categorizeWithAI(uniqueAIKeys.slice(i, i + 20)));
    }
    console.log(`[categorizer] C3: ${Object.keys(aiResults).length}/${uniqueAIKeys.length} por IA`);
    for (const mov of needsAI) results.set(mov.idx, aiResults[mov.merchantKey] ?? "other");
  }

  return normalized.map(mov => {
    const category   = results.get(mov.idx) ?? "other";
    const externalId = mov.externalId ?? buildExternalId(bankId, mov.date, mov.amount, mov.rawDesc, mov.source, mov.idx);
    return {
      amount:         mov.amount,
      date:           mov.date,
      category,
      externalId,
      movementSource: mov.source,
      description:    categoryLabel(category),
      rawDescription: mov.rawDesc,  // guardado para re-categorización futura
      _bankId:        bankId,
      _balance:       parseInt(mov.raw.balance ?? 0),
    };
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function normalizeDate(raw) {
  if (!raw) return new Date().toISOString().split("T")[0];
  if (/^\d{2}-\d{2}-\d{4}$/.test(raw)) {
    const [d, mo, y] = raw.split("-");
    return `${y}-${mo}-${d}`;
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.substring(0, 10);
  return new Date().toISOString().split("T")[0];
}

export function categoryLabel(category) {
  return {
    food:         "Alimentación",
    transport:    "Transporte",
    subscriptions:"Suscripción",
    entertainment:"Entretención",
    health:       "Salud",
    education:    "Educación",
    housing:      "Vivienda",
    insurance:    "Seguro",
    utilities:    "Servicios básicos",
    shopping:     "Compras",
    debt_payment: "Cuota crédito",
    savings:      "Ahorro",
    transfer:     "Transferencia",
    banking_fee:  "Comisión bancaria",
    income:       "Ingreso",
    other:        "Gasto",
  }[category] ?? "Gasto";
}

function buildExternalId(bankId, date, amount, desc, source, idx) {
  const raw = `${bankId}:${source}:${date}:${amount}:${desc.substring(0, 30)}:${idx}`;
  let h = 0;
  for (let i = 0; i < raw.length; i++) { h = ((h << 5) - h) + raw.charCodeAt(i); h |= 0; }
  return `${bankId}_${Math.abs(h).toString(36)}_${idx}`;
}