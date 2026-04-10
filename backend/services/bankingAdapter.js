// ─────────────────────────────────────────────────────────────────────────────
// services/bankingAdapter.js
//
// Capa de abstracción entre proveedores bancarios y Sky.
// Cambiar de open-banking-chile a Fintoc = cambiar este archivo únicamente.
//
// BANCOS DISPONIBLES:
//   · falabella — Banco Falabella  (scraper Puppeteer)
//   · bchile    — Banco de Chile   (scraper Puppeteer + 2FA via app)
//
// CHROME EN DISTINTOS ENTORNOS:
//   · macOS dev   → auto-detecta /Applications/Google Chrome.app/...
//   · Railway     → usa CHROME_PATH=/usr/bin/google-chrome (var de entorno)
//   · Otro Linux  → CHROME_PATH explícito o puppeteer lo busca en PATH
// ─────────────────────────────────────────────────────────────────────────────

import { existsSync } from "fs";

// ── Bancos disponibles ────────────────────────────────────────────────────────

export const SUPPORTED_BANKS = [
  { id: "falabella", name: "Banco Falabella", icon: "💳", available: true  },
  { id: "bchile",    name: "Banco de Chile",  icon: "🏦", available: true  },
  { id: "santander", name: "Santander Chile", icon: "🔴", available: false },
  { id: "bci",       name: "BCI",             icon: "🔵", available: false },
  { id: "estado",    name: "Banco Estado",    icon: "🟡", available: false },
];

export function getSupportedBanks() { return SUPPORTED_BANKS; }

export function isBankSupported(bankId) {
  return SUPPORTED_BANKS.some((b) => b.id === bankId && b.available);
}

// ── Chrome path — auto-detection ──────────────────────────────────────────────
// Orden de prioridad:
// 1. CHROME_PATH en .env (Railway, producción, o ruta manual)
// 2. Rutas estándar por sistema operativo (macOS, Windows)
// 3. undefined → puppeteer-core busca en PATH del sistema (Linux)

function getChromePath() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;

  switch (process.platform) {
    case "darwin":
      return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

    case "win32": {
      const candidates = [
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        process.env.LOCALAPPDATA
          ? `${process.env.LOCALAPPDATA}\\Google\\Chrome\\Application\\chrome.exe`
          : null,
      ].filter(Boolean);

      for (const p of candidates) {
        try { if (existsSync(p)) return p; } catch {}
      }
      // Fallback a la ruta más común si no encontró ninguna
      return "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
    }

    default:
      return undefined; // Linux/Railway: puppeteer busca en PATH
  }
}

// ── Categorizador de transacciones ───────────────────────────────────────────

// ── Reglas de categorización — optimizadas para bancos chilenos ──────────────
// Banco de Chile usa descripciones como:
//   "COMPRA LIDER EXPRESS", "PAG CUENTA ENTEL", "TRF A CTA VIA TEF",
//   "CARGO NETFLIX", "COMPRA FARMACIA SALCOBRAND", "PAG TAR CRED"
// Los patrones cubren tanto texto libre como códigos de transacción internos.

const CATEGORY_RULES = [
  // ── Vivienda ────────────────────────────────────────────────────────────────
  {
    category: "housing",
    pattern: /arriendo|renta|condominio|gastos\s*comunes|dividendo\s*hipot|adm\s*edificio|administracion\s*edif|mantenci[oó]n\s*edif/i,
  },
  // ── Alimentación ────────────────────────────────────────────────────────────
  {
    category: "food",
    // bchile usa "Pago:NOMBRE" — cubrimos tanto nombre directo como prefijado
    pattern: /pago:.*?(lider|jumbo|tottus|santa.*isabel|unimarc|unimark|acuenta|mayorista|super\s*10|ekono|cafeter|take.?go|restaurant|sushi|pizza|burger|mcdonalds|kfc|subway|dominos|wendys|telepizza|starbucks|cafe|coffee|fuente|rotiser|comedor|panaderi|pasteleri|carnicer|verdurer)|lider|jumbo|tottus|santa\s*isabel|unimarc|unimark|acuenta|mayorista|ekono|listo|bigbox|rappi|uber\s*eat|pedidos\s*ya|delivery|junaeb|mercadopago/i,
  },
  // ── Transporte ──────────────────────────────────────────────────────────────
  {
    category: "transport",
    // "Pago:metro Los Leones" es el patrón real de bchile para Metro
    pattern: /pago:.*?(metro|uber|cabify|didi|taxi|copec|shell|petrobras|esso|enex|peaje|autopista|parking|estacion|bus\s*tur|turbus|pullman|jac\s*bus)|metro(?!\s*cuadrado)|bip[!\s]|red\s*movilidad|transantiago|uber(?!\s*eat)|cabify|didi|autopass|costanera|vespucio/i,
  },
  // ── Suscripciones y streaming ────────────────────────────────────────────────
  {
    category: "subscriptions",
    // bchile: "Cargo Netflix", "Pago:spotify", "Cargo:apple", etc.
    pattern: /(?:cargo|pago):?\s*(?:netflix|spotify|amazon|hbo|disney|paramount|apple|youtube|google|microsoft|adobe|dropbox|icloud|canva|notion|chatgpt|openai|twitch|deezer|tidal|crunchyroll)|netflix|spotify|amazon\s*prime|prime\s*video|hbo\s*max|disney\+?|youtube\s*premium|google\s*one|microsoft\s*365|adobe|icloud|suscripci[oó]n|subscripci[oó]n|membresia|cargo\s*mensual/i,
  },
  // ── Entretenimiento ──────────────────────────────────────────────────────────
  {
    category: "entertainment",
    pattern: /steam|playstation|xbox|nintendo|cine|hoyts|cinemark|cinemundo|ticketmaster|puntoticket|ticketek|concierto|teatro|espect[aá]culo|evento|parque\s*arauco|mall|costanera\s*center|paseo|librerias|fnac|gaming/i,
  },
  // ── Salud ────────────────────────────────────────────────────────────────────
  {
    category: "health",
    pattern: /farmacia|salcobrand|cruz\s*verde|ahumada|dr\s*simi|knop|medico|cl[ií]nica|hospital|consultorio|isapre|fonasa|dental|odontolog|optica|laboratorio|policl[ií]nico|urgencia|maternidad|medilab|bupa|colmena|consalud|banmedica|vidaintegra/i,
  },
  // ── Educación ────────────────────────────────────────────────────────────────
  {
    category: "education",
    pattern: /universidad|u\.\s*de|uc\s+|puc\s+|usach|uchile|udp|uai|uandes|duoc|inacap|colegio|liceo|instituto|academia|curso|escuela|matr[ií]cula|arancel|cae|credito\s*universitario|becas\s*chile/i,
  },
  // ── Seguros ──────────────────────────────────────────────────────────────────
  {
    category: "insurance",
    pattern: /seguro|insurance|metlife|sura|mapfre|zurich|liberty\s*seg|bci\s*seg|penta\s*seg|cargo\s*seg|prima\s*seg|cia\s*seg|compania\s*seg/i,
  },
  // ── Deudas y créditos ────────────────────────────────────────────────────────
  {
    category: "debt_payment",
    // bchile: "Pago Tarjeta Credito", "Cuota Credito Consumo", "Cargo Cred"
    pattern: /pago?\s*tar(?:jeta)?(?:\s*cr[eé]d)?|cuota|cr[eé]dito\s*cons|pr[eé]stamo|dividendo\s*hip|financiamiento|pag\s*cred|cargo\s*cred|abono\s*cred|cred(?:ito)?\s*hip|avance\s*efect|linea\s*de\s*cr[eé]d/i,
  },
  // ── Ahorro e inversión ───────────────────────────────────────────────────────
  {
    category: "savings",
    pattern: /dep[oó]sito\s*plazo|dap\s|fondo\s*mutuo|inversion|ahorro|cuenta\s*ahorro|cta\s*ahorro|aporte\s*afp|cotizacion\s*afp|comisi[oó]n\s*afp|retiro\s*afp|apv/i,
  },
  // ── Servicios básicos ────────────────────────────────────────────────────────
  {
    category: "utilities",
    // bchile: "Pago:entel", "Pago:movistar cuenta", "Cargo:enel"
    pattern: /(?:pago|cargo):?\s*(?:entel|movistar|claro|wom|vtr|gtd|enel|chilectra|cge|esval|essbio|smapa|metrogas|aguas)|enel|chilectra|cge(?:\s|$)|electricidad|esval|essbio|metrogas|entel|movistar|claro(?:\s|$)|wom(?:\s|$)|vtr(?:\s|$)|gtd(?:\s|$)|agua\s*potable|servicio\s*bas/i,
  },
  // ── Retail y tiendas ─────────────────────────────────────────────────────────
  {
    category: "shopping",
    // bchile: "Pago:falabella", "Compra Comercio Ripley"
    pattern: /(?:pago|compra\s*comercio):?\s*(?:falabella|ripley|paris|abcdin|hites|polar|johnson|corona|zara|adidas|nike|decathlon|easy|sodimac)|falabella|ripley|abcdin|hites|la\s*polar|johnson\s|tricot|zara|h&m|forever\s*21|adidas|nike|decathlon|easy(?:\s|$)|sodimac|homecenter|ferreter|muebles(?:\s|$)|compra\s*comercio/i,
  },
];

export function inferCategory(description, amount) {
  if (!description) return amount > 0 ? "income" : "other";
  const text = description.trim();

  // ── Ingresos — detección prioritaria ──────────────────────────────────────
  if (amount > 0) {
    // bchile ingresos: "Traspaso De:NOMBRE", "Abono Remuneracion", "Deposito De:"
    if (/traspaso\s*de:|abono|remuner|sueldo|salario|honorario|dep[oó]sito\s*de|deposito\s*de|liquidaci[oó]n|finiquito|bono\s|gratificaci[oó]n|devoluci[oó]n\s*impu|transferencia\s*recib/i.test(text)) {
      return "income";
    }
  }

  // ── Aplicar reglas en orden ────────────────────────────────────────────────
  for (const rule of CATEGORY_RULES) {
    if (rule.pattern.test(text)) return rule.category;
  }

  // ── Transferencias salientes → "other" con subcategorización futura ───────
  // bchile transferencias salientes: "Traspaso A:NOMBRE", "Transferencia A:"
  if (amount < 0 && /traspaso\s*a:|transferencia\s*a:|trf|tef|env[ií]o|giro|khipu/i.test(text)) return "transfer";
  // Comisiones bancarias
  if (/comision|comisión|cargo\s*mantenci|mantenci[oó]n\s*cuenta|iva\s*comis/i.test(text)) return "banking_fee";

  return amount > 0 ? "income" : "other";
}

// ── Adaptador canónico ────────────────────────────────────────────────────────

export function adaptMovements(rawMovements, bankId) {
  if (!Array.isArray(rawMovements)) return [];
  return rawMovements
    .filter((m) => m && m.amount !== undefined)
    .map((m, idx) => {
      const amount     = parseInt(m.amount ?? 0);
      const rawDesc    = (m.description ?? "").trim();
      const date       = normalizeDate(m.date);
      const category   = inferCategory(rawDesc, amount);
      const movSource  = m.source ?? "account";
      const externalId = m.id ?? buildExternalId(bankId, date, amount, rawDesc, movSource, idx);
      return {
        amount, date, category, externalId,
        movementSource: movSource,
        description:    sanitizeDescription(rawDesc, category),
        _rawDescription: rawDesc,
        _bankId:         bankId,
        _balance:        parseInt(m.balance ?? 0),
      };
    })
    .filter((m) => m.amount !== 0);
}

function normalizeDate(raw) {
  if (!raw) return new Date().toISOString().split("T")[0];
  if (/^\d{2}-\d{2}-\d{4}$/.test(raw)) {
    const [d, mo, y] = raw.split("-");
    return `${y}-${mo}-${d}`;
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.substring(0, 10);
  return new Date().toISOString().split("T")[0];
}

function sanitizeDescription(raw, category) {
  const labels = {
    housing:      "Vivienda",
    food:         "Alimentación",
    transport:    "Transporte",
    subscriptions:"Suscripción",
    entertainment:"Entretención",
    health:       "Salud",
    education:    "Educación",
    insurance:    "Seguro",
    debt_payment: "Cuota crédito",
    savings:      "Ahorro",
    utilities:    "Servicios básicos",
    shopping:     "Compras",
    transfer:     "Transferencia",
    banking_fee:  "Comisión bancaria",
    income:       "Ingreso",
    other:        "Gasto",
  };
  return labels[category] ?? "Gasto";
}

function buildExternalId(bankId, date, amount, desc, source, idx) {
  const raw = `${bankId}:${source}:${date}:${amount}:${desc.substring(0, 30)}:${idx}`;
  let h = 0;
  for (let i = 0; i < raw.length; i++) { h = ((h << 5) - h) + raw.charCodeAt(i); h |= 0; }
  return `${bankId}_${Math.abs(h).toString(36)}_${idx}`;
}

// ── Proveedores ───────────────────────────────────────────────────────────────

export async function getProviderForBank(bankId) {
  const { getBank } = await import("open-banking-chile");
  const chromePath  = getChromePath();

  switch (bankId) {

    // ── Banco Falabella ──────────────────────────────────────────────────────
    case "falabella": {
      const bank = getBank("falabella");
      if (!bank) throw new Error('[banking] "falabella" no encontrado en open-banking-chile');
      return {
        type: "scraper",
        async fetchData({ rut, password, onProgress }) {
          const opts = { rut, password };
          if (chromePath) opts.chromePath = chromePath;
          if (process.platform === 'win32') opts.headful = true;
          if (onProgress)  opts.onProgress  = onProgress;

          const result = await bank.scrape(opts);
          if (!result.success) throw new Error(result.error ?? "Scrape falló sin detalle");
          return { balance: result.balance ?? 0, movements: result.movements ?? [] };
        },
      };
    }

    // ── Banco de Chile ───────────────────────────────────────────────────────
    // El scraper maneja 2FA automáticamente:
    //   · Si el usuario tiene Banco de Chile Pass, el scraper detecta la pantalla
    //     de 2FA y espera hasta BCHILE_2FA_TIMEOUT_SEC (default 120s).
    //   · Cuando el usuario aprueba en su app, el scraper continúa solo.
    //   · Si no aprueba a tiempo → error "2FA_TIMEOUT".
    case "bchile": {
      const bank = getBank("bchile");
      if (!bank) throw new Error('[banking] "bchile" no encontrado en open-banking-chile');
      return {
        type: "scraper",
        async fetchData({ rut, password, onProgress }) {
          const opts = { rut, password };
          if (chromePath)  opts.chromePath  = chromePath;
          if (onProgress)  opts.onProgress  = onProgress;

          // Timeout 2FA: cuántos segundos espera la aprobación en la app
          // Configurable por .env — default 120s para dar tiempo cómodo al usuario
          if (!process.env.BCHILE_2FA_TIMEOUT_SEC) {
            process.env.BCHILE_2FA_TIMEOUT_SEC = "120";
          }

          const result = await bank.scrape(opts);

          if (!result.success) {
            const err = result.error ?? "Scrape falló sin detalle";
            // Errores conocidos con mensajes claros para el usuario
            if (/timeout|aprobaci[oó]n|2FA/i.test(err)) {
              throw new Error("2FA_TIMEOUT: No se recibió aprobación a tiempo. Abre tu app Banco de Chile y vuelve a intentar.");
            }
            if (/login failed|p[áa]gina de login|clave incorrecta|rut inv[áa]lido/i.test(err)) {
              throw new Error("AUTH_FAILED: RUT o clave incorrectos.");
            }
            throw new Error(err);
          }

          return { balance: result.balance ?? 0, movements: result.movements ?? [] };
        },
      };
    }

    // ── Fintoc (futuro — cuando haya financiación) ────────────────────────────
    // case "fintoc": {
    //   return {
    //     type: "api",
    //     async fetchData({ linkToken, onProgress }) {
    //       const fintoc = new Fintoc(process.env.FINTOC_SECRET_KEY);
    //       // ... implementar con Fintoc SDK
    //     },
    //   };
    // }

    default:
      throw new Error(`[banking] proveedor para "${bankId}" no implementado aún`);
  }
}