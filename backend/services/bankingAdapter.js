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

const CATEGORY_RULES = [
  { pattern: /arriendo|renta|condominio|gastos\s+comunes|dividendo\s+hipotecario|administracion\s+edificio/i,   category: "housing"      },
  { pattern: /supermercado|lider|jumbo|tottus|santa\s+isabel|unimarc|delivery|uber.?eat|pedidos.?ya|rappi|domino|mcdonalds|burger|kfc|subway|restaurant|panaderia|almacen|walmart|acuenta/i, category: "food" },
  { pattern: /uber|cabify|didi|taxi|bip|transantiago|red\s+movilidad|copec|shell|petrobras|esso|estacion.?servicio|peaje|autopista|enex/i, category: "transport" },
  { pattern: /netflix|spotify|amazon.?prime|hbo|disney|youtube.?premium|apple|microsoft|google.?one|adobe|dropbox|icloud|suscripcion|subscripcion/i, category: "subscriptions" },
  { pattern: /steam|playstation|xbox|nintendo|cine|cinema|hoyts|cinemark|ticketmaster|puntoticket|concierto|teatro|evento/i, category: "entertainment" },
  { pattern: /farmacia|salcobrand|cruz.?verde|ahumada|medico|clinica|hospital|consulta|isapre|fonasa|dental|optica/i, category: "health" },
  { pattern: /universidad|colegio|instituto|academia|curso|escuela|educacion|matri[ck]ula/i,                    category: "education"    },
  { pattern: /seguro|insurance|metlife|sura\s+seguros/i,                                                        category: "insurance"    },
  { pattern: /cuota|credito|prestamo|dividendo|financiamiento/i,                                                 category: "debt_payment" },
  { pattern: /deposito\s+plazo|fondo\s+mutuo|inversiones/i,                                                     category: "savings"      },
];

export function inferCategory(description, amount) {
  if (!description) return amount > 0 ? "income" : "other";
  const text = description.toUpperCase();
  if (amount > 0 && /transferencia\s+recibida|abono|remuneracion|sueldo|salario|honorario/i.test(text)) return "income";
  for (const rule of CATEGORY_RULES) {
    if (rule.pattern.test(text)) return rule.category;
  }
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
    housing: "Vivienda", food: "Alimentación", transport: "Transporte",
    subscriptions: "Suscripción", entertainment: "Entretención", health: "Salud",
    education: "Educación", insurance: "Seguro", debt_payment: "Cuota crédito",
    savings: "Ahorro", income: "Ingreso", other: "Gasto",
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