// ─────────────────────────────────────────────────────────────────────────────
// services/bankingAdapter.js
//
// Capa de abstracción entre proveedores bancarios y el modelo interno de Sky.
//
// PROPÓSITO:
//   Hoy usamos open-banking-chile (scraper). Mañana usaremos Fintoc.
//   Esta capa garantiza que cambiar de proveedor = cambiar UN adaptador,
//   no reescribir financeService, dbService ni la app.
//
// MODELO CANÓNICO (SkyTransaction):
//   { date, amount, description, rawDescription, category, externalId, bankId }
//
// PRIVACIDAD:
//   - rawDescription se descarta ANTES de persistir en Supabase
//   - Solo se guarda la categoría inferida — nunca el texto original del banco
//   - El balance exacto va a last_balance en bank_accounts (tabla del usuario, RLS)
//   - ARIA recibe solo buckets, nunca montos reales
// ─────────────────────────────────────────────────────────────────────────────

// ── Registro de bancos disponibles ───────────────────────────────────────────

export const SUPPORTED_BANKS = [
  { id: "falabella", name: "Banco Falabella", icon: "💳", available: true  },
  { id: "bchile",    name: "Banco de Chile",  icon: "🏦", available: false },
  { id: "santander", name: "Santander Chile", icon: "🔴", available: false },
  { id: "bci",       name: "BCI",             icon: "🔵", available: false },
  { id: "estado",    name: "Banco Estado",    icon: "🟡", available: false },
];

export function getSupportedBanks() {
  return SUPPORTED_BANKS;
}

export function isBankSupported(bankId) {
  return SUPPORTED_BANKS.find((b) => b.id === bankId && b.available) !== undefined;
}

// ── Categorizador de transacciones ───────────────────────────────────────────
// Infiere categoría desde la descripción del banco.
// La descripción original se descarta después — solo la categoría persiste.

const CATEGORY_RULES = [
  // Housing
  { pattern: /arriendo|renta|condominio|gastos comunes|dividendo hipotecario/i, category: "housing" },
  // Food
  { pattern: /supermercado|lider|jumbo|tottus|santa isabel|unimarc|delivery|uber.?eat|pedidos.?ya|rappi|domino|mcdonalds|burger|kfc|subway|restaurant|panaderia|almacen/i, category: "food" },
  // Transport
  { pattern: /uber|cabify|didi|taxi|bip|transantiago|red movilidad|copec|shell|petrobras|esso|estacion.?servicio|peaje|autopista/i, category: "transport" },
  // Subscriptions
  { pattern: /netflix|spotify|amazon.?prime|hbo|disney|youtube.?premium|apple|microsoft|google.?one|adobe|dropbox|icloud|suscripcion/i, category: "subscriptions" },
  // Entertainment
  { pattern: /steam|playstation|xbox|nintendo|cine|cinema|hoyts|cinemark|ticketmaster|puntoticket|concierto|teatro|evento/i, category: "entertainment" },
  // Health
  { pattern: /farmacia|salcobrand|cruz.?verde|ahumada|medico|clinica|hospital|consulta|isapre|fonasa|dental|optica/i, category: "health" },
  // Positive amounts = income (transfers received, salary)
];

export function inferCategory(description, amount) {
  if (!description) return amount > 0 ? "income" : "other";

  const text = description.toUpperCase();

  // Transferencias entrantes → income
  if (amount > 0 && /transferencia recibida|abono|deposito|remuneracion|sueldo|salario/i.test(text)) {
    return "income";
  }

  for (const rule of CATEGORY_RULES) {
    if (rule.pattern.test(text)) return rule.category;
  }

  return amount > 0 ? "income" : "other";
}

// ── Adaptador canónico ────────────────────────────────────────────────────────
// Convierte el output crudo de cualquier proveedor al formato interno de Sky.

export function adaptMovements(rawMovements, bankId) {
  if (!Array.isArray(rawMovements)) return [];

  return rawMovements
    .filter((m) => m && (m.amount !== undefined || m.monto !== undefined))
    .map((m, idx) => {
      // Normalizar campos — open-banking-chile usa: date, description, amount, balance
      const amount      = parseInt(m.amount ?? m.monto ?? 0);
      const rawDesc     = (m.description ?? m.descripcion ?? "").trim();
      const date        = normalizeDate(m.date ?? m.fecha);
      const category    = inferCategory(rawDesc, amount);

      // externalId para deduplicación — si el banco no da ID, construimos uno determinístico
      const externalId  = m.id ?? m.externalId ?? buildExternalId(bankId, date, amount, rawDesc, idx);

      return {
        // Campos que SÍ se guardan en Supabase
        amount,
        date,
        category,
        externalId,
        // description almacena una versión limpia — no el raw del banco
        description: sanitizeDescription(rawDesc, category),

        // Campos que NO se guardan — solo se usan en memoria para ARIA
        _rawDescription: rawDesc,
        _bankId:         bankId,
        _balance:        parseInt(m.balance ?? m.saldo ?? 0),
      };
    })
    .filter((m) => m.amount !== 0); // descartar movimientos $0
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function normalizeDate(raw) {
  if (!raw) return new Date().toISOString().split("T")[0];

  // open-banking-chile retorna "DD-MM-YYYY"
  if (/^\d{2}-\d{2}-\d{4}$/.test(raw)) {
    const [d, mo, y] = raw.split("-");
    return `${y}-${mo}-${d}`;
  }

  // ISO o YYYY-MM-DD
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.substring(0, 10);

  return new Date().toISOString().split("T")[0];
}

function sanitizeDescription(raw, category) {
  // Guarda una etiqueta limpia de la categoría, no el texto bancario original.
  // El texto bancario puede contener datos sensibles (nombre del comercio exacto,
  // ciudad, número de terminal) — no necesitamos ese detalle para la app.
  const labels = {
    housing:       "Vivienda",
    food:          "Alimentación",
    transport:     "Transporte",
    subscriptions: "Suscripción",
    entertainment: "Entretención",
    health:        "Salud",
    income:        "Ingreso",
    other:         "Gasto",
  };
  return labels[category] ?? "Gasto";
}

function buildExternalId(bankId, date, amount, desc, idx) {
  // ID determinístico para deduplicación cuando el banco no provee ID propio
  const raw = `${bankId}:${date}:${amount}:${desc.substring(0, 30)}:${idx}`;
  // Hash simple — no criptográfico, solo para unicidad
  let h = 0;
  for (let i = 0; i < raw.length; i++) {
    h = ((h << 5) - h) + raw.charCodeAt(i);
    h |= 0;
  }
  return `${bankId}_${Math.abs(h).toString(36)}_${idx}`;
}

// ── Proveedor activo ──────────────────────────────────────────────────────────
// Carga el scraper correspondiente al banco.
// Cuando migremos a Fintoc: agregar case "fintoc" aquí. Nada más cambia.

export async function getProviderForBank(bankId) {
  switch (bankId) {
    case "falabella": {
      // open-banking-chile — scraper Puppeteer
      // Requiere Chrome instalado en el servidor
      const { getBank } = await import("open-banking-chile");
      const bank = getBank(bankId);
      if (!bank) throw new Error(`[banking] banco "${bankId}" no encontrado en open-banking-chile`);
      return {
        type: "scraper",
        async fetchData({ rut, password }) {
          const result = await bank.scrape({ rut, password });
          if (!result.success) throw new Error(result.error ?? "Scrape falló sin detalle");
          return {
            balance:   result.balance ?? 0,
            movements: result.movements ?? [],
          };
        },
      };
    }

    // ── FINTOC (futuro) ───────────────────────────────────────────────────────
    // case "fintoc": {
    //   return {
    //     type: "api",
    //     async fetchData({ linkToken }) {
    //       const fintoc = new Fintoc(process.env.FINTOC_API_KEY);
    //       const link   = fintoc.getLink(linkToken);
    //       const account = await link.accounts.get("...");
    //       return {
    //         balance:   account.balance.available,
    //         movements: await account.movements.list(),
    //       };
    //     },
    //   };
    // }

    default:
      throw new Error(`[banking] proveedor para "${bankId}" no implementado aún`);
  }
}