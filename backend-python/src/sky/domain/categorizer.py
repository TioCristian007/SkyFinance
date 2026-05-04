"""
sky.domain.categorizer — Categorización 3 capas (paridad con Node v3).

Jerarquía:
    1. Reglas regex deterministas — sin tokens, instantáneo.
    2. Cache en `merchant_categories` con prefix matching progresivo.
    3. Claude Haiku batch 20 keys/call. Resultado se guarda en cache.

Si Claude no logra confidence >= 0.75 → "other". Si la 3ra capa falla
(rate limit, error de red), todas las filas restantes se marcan "fallback"
para no quedar en loop infinito.

Categoría "other" + source="fallback" significa: el sistema no pudo
clasificar y el usuario tendrá la oportunidad de declarar manualmente
(ver §4 — sistema de votos crowdsourced, fuera de scope Fase 6).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import anthropic
from anthropic.types import TextBlock
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("categorizer")

# ── Categorías canónicas ──────────────────────────────────────────────────────

CATEGORIES = (
    "food", "transport", "subscriptions", "entertainment",
    "health", "education", "housing", "insurance", "utilities",
    "shopping", "debt_payment", "savings", "transfer",
    "banking_fee", "income", "other",
)

CATEGORY_LABELS: dict[str, str] = {
    "food":          "Alimentación",
    "transport":     "Transporte",
    "subscriptions": "Suscripción",
    "entertainment": "Entretención",
    "health":        "Salud",
    "education":     "Educación",
    "housing":       "Vivienda",
    "insurance":     "Seguro",
    "utilities":     "Servicios básicos",
    "shopping":      "Compras",
    "debt_payment":  "Cuota crédito",
    "savings":       "Ahorro",
    "transfer":      "Transferencia",
    "banking_fee":   "Comisión bancaria",
    "income":        "Ingreso",
    "other":         "Gasto",
}

# ── CAPA 1: Reglas deterministas ──────────────────────────────────────────────
# Paridad estricta con LAYER1_RULES de Node. Orden importa: la primera regla
# que matchea gana.

_RuleEntry = tuple[Any, str]

_RULES: list[_RuleEntry] = [
    (lambda d, a: a > 0 and re.search(r"^traspaso\s+de:", d, re.I) is not None,                        "income"),
    (lambda d, a: a > 0 and re.search(r"abono|remuner|sueldo|salario|honorario|liquidaci", d, re.I) is not None, "income"),
    (lambda d, a: a > 0 and re.search(r"devoluci[oó]n\s*(imp|sii)|reintegro", d, re.I) is not None,    "income"),
    (lambda d, a: a < 0 and re.search(r"^traspaso\s+a:", d, re.I) is not None,                         "transfer"),
    (lambda d, a: a < 0 and re.search(r"khipu|transferencia\s+a:", d, re.I) is not None,               "transfer"),
    (lambda d, a: re.search(r"^comisi[oó]n|iva\s+comisi[oó]n|mantenci[oó]n\s+cta|cargo\s+mantenci", d, re.I) is not None, "banking_fee"),
    (lambda d, a: re.search(r"bip[!\s]|red\s+movilidad|transantiago", d, re.I) is not None,            "transport"),
    (lambda d, a: re.search(r"pago:metro\s|metro\s+(de\s+santiago|baquedano|universidad|plaza|santa\s+ana)", d, re.I) is not None, "transport"),
    (lambda d, a: re.search(r"\bcopec\b|\bshell\b|\bpetrobras\b|\benex\b|\besso\b", d, re.I) is not None, "transport"),
    (lambda d, a: re.search(r"\bnetflix\b|\bspotify\b|\bdisney\+|\bhbo\s*max\b|\byoutube\s*premium\b|\bamazon\s*prime\b|\bcrunchyroll\b|\bstar\+", d, re.I) is not None, "subscriptions"),
    (lambda d, a: re.search(r"pago:\s*(entel|movistar|claro|wom|vtr|gtd)\b", d, re.I) is not None,       "utilities"),
    (lambda d, a: re.search(r"salcobrand|cruz\s*verde|ahumada|dr\.?\s*simi", d, re.I) is not None,     "health"),
    (lambda d, a: re.search(r"pago\s+tar(jeta)?\s+cr[eé]d|pago\s+tc\b", d, re.I) is not None,          "debt_payment"),
    (lambda d, a: re.search(r"dep[oó]sito\s+plazo|dap\b|fondo\s+mutuo|\bapv\b|aporte\s+afp", d, re.I) is not None, "savings"),
    (lambda d, a: re.search(r"\bjumbo\b|\blider\b|\btottus\b|\bsanta\s+isabel\b|\bunimarc\b|\bacuenta\b|\bekono\b", d, re.I) is not None, "food"),
    (lambda d, a: re.search(r"\bstarbucks\b|\bmcdonald|\bburger\s*king\b|\bsubway\b|\bdominos\b|\bpizza\s*hut\b|\bkfc\b", d, re.I) is not None, "food"),
    (lambda d, a: re.search(r"\brappi\b|\bpedidos\s*ya\b|\buber\s*eats\b|\bcornershop\b", d, re.I) is not None, "food"),
    (lambda d, a: re.search(r"\boxxo\b|\baramco\b|\btake\s*[&y]?\s*go\b|\bpronto\s*copec\b", d, re.I) is not None, "food"),
    (lambda d, a: re.search(r"\buber\b(?!\s*eats)|\bcabify\b|\bindriver\b|\bdidi\b|\beasy\s*taxi\b", d, re.I) is not None, "transport"),
    (lambda d, a: re.search(r"\bfalabella\b|\bripley\b|\bhites\b|\bsodimac\b|\bhomecenter\b", d, re.I) is not None, "shopping"),
    (lambda d, a: re.search(r"\bisapre\b|\bfonasa\b|\bbanmedica\b|\bconsalud\b|\bcolmena\b|\bvidaintegra\b", d, re.I) is not None, "health"),
    (lambda d, a: re.search(r"\bchilectra\b|\benel\b(?!\s*x)|\baguas\s+andinas\b|\bmetrogas\b|\bessbio\b|\besval\b", d, re.I) is not None, "utilities"),
]


def _apply_layer1(description: str, amount: int) -> str | None:
    desc_l = description.lower() if description else ""
    for predicate, cat in _RULES:
        if predicate(desc_l, amount):
            return cat
    return None


# ── Normalización ─────────────────────────────────────────────────────────────

def normalize_merchant(description: str) -> str:
    """Limpia descripciones bancarias para usar como key de cache."""
    s = description.lower()
    s = re.sub(r"^pago\s*:\s*", "", s)
    s = re.sub(r"^cargo\s*:\s*", "", s)
    s = re.sub(r"^compra\s+comercio\s*", "", s)
    s = re.sub(r"^compra\s+internet\s*", "", s)
    s = re.sub(r"^pago\s+internet\s*", "", s)
    s = re.sub(r"mercadopago\*", "mercadopago ", s)
    s = re.sub(r"[*_\-.]{2,}", " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()[:60]


def _key_variants(merchant_key: str) -> list[str]:
    """`'jumbo las condes' → ['jumbo las condes', 'jumbo las', 'jumbo']`."""
    if not merchant_key:
        return []
    words = [w for w in merchant_key.split(" ") if w]
    return [" ".join(words[:i]) for i in range(len(words), 0, -1)]


# ── CAPA 2: Cache con prefix matching ────────────────────────────────────────

async def _lookup_cache(merchant_keys: list[str]) -> dict[str, str]:
    if not merchant_keys:
        return {}
    all_variants = sorted({v for k in merchant_keys for v in _key_variants(k)})
    if not all_variants:
        return {}

    engine: AsyncEngine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text(
                "SELECT merchant_key, category FROM public.merchant_categories"
                " WHERE merchant_key = ANY(:keys)"
            ),
            {"keys": all_variants},
        )
        rows = rs.fetchall()

    variant_map = {r.merchant_key: r.category for r in rows}
    out: dict[str, str] = {}
    for key in merchant_keys:
        for v in _key_variants(key):
            if v in variant_map:
                out[key] = variant_map[v]
                break
    return out


async def _save_to_cache(entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    engine: AsyncEngine = get_engine()
    async with engine.begin() as conn:
        for e in entries:
            try:
                await conn.execute(
                    text("""
                        SELECT public.upsert_merchant_category(
                            :p_merchant_key, :p_category, :p_source, :p_confidence
                        )
                    """),
                    {
                        "p_merchant_key": e["merchant_key"],
                        "p_category":     e["category"],
                        "p_source":       e.get("source", "ai"),
                        "p_confidence":   e.get("confidence"),
                    },
                )
            except Exception as exc:
                logger.warning("cache_write_failed", merchant=e["merchant_key"], error=str(exc))


# ── CAPA 3: Claude Haiku ──────────────────────────────────────────────────────

_CATEGORIZER_SYSTEM = """Eres un clasificador de transacciones bancarias chilenas.
Recibirás nombres de comercios ya normalizados (sin "Pago:", en minúsculas).
Responde SOLO con un array JSON. Sin texto extra, sin markdown.

Categorías:
food         → supermercados, restoranes, cafeterías, delivery, kioscos, conveniencia, almacenes
transport    → metro, uber, cabify, taxi, bencina, peajes, estacionamiento, buses, vuelos
subscriptions → streaming (netflix,spotify,disney+), software SaaS, membresías digitales
entertainment → cines, juegos, eventos, bares, discotecas, libros
health       → farmacias, médicos, clínicas, ópticas, isapre, laboratorios
education    → universidades, colegios, cursos, academias, preuniversitarios
housing      → arriendo, dividendo, condominio, gastos comunes, mudanza
insurance    → seguros vida/auto/hogar
utilities    → luz, agua, gas, teléfono, internet, cable
shopping     → ropa, tecnología, muebles, mascotas, retail general
debt_payment → cuotas crédito, pago tarjeta, cuota préstamo
savings      → DAP, fondos mutuos, APV, cuenta ahorro
transfer     → traspasos entre personas
banking_fee  → comisiones, mantención, IVA bancario
other        → solo si realmente no se puede clasificar

Reglas Chile:
- "aramco", "oxxo", "take go", "pronto copec" → food
- "jumbo las condes", "lider pudahuel" (ciudad al final) → food por el supermercado
- "mercadopago" + nombre → categoriza por el negocio que sigue
- confidence < 0.75 → usar "other"

Formato EXACTO (solo esto):
[{"key":"nombre","category":"food","confidence":0.95},...]"""


async def _categorize_with_ai(merchant_keys: list[str]) -> dict[str, str]:
    if not merchant_keys:
        return {}
    client = anthropic.AsyncAnthropic()
    try:
        resp = await client.messages.create(
            model=settings.categorize_anthropic_model,
            max_tokens=1024,
            system=_CATEGORIZER_SYSTEM,
            messages=[{"role": "user", "content": f"Clasifica:\n{json.dumps(merchant_keys)}"}],
        )
        first_text = next((b for b in resp.content if isinstance(b, TextBlock)), None)
        raw = first_text.text.strip() if first_text else "[]"
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.I).strip()
        items = json.loads(cleaned)

        result: dict[str, str] = {}
        to_cache: list[dict[str, Any]] = []
        thr = settings.categorize_confidence_threshold
        for item in items:
            cat = item.get("category", "other")
            conf = float(item.get("confidence", 0.0) or 0.0)
            if conf < thr or cat not in CATEGORIES:
                cat = "other"
            key = item.get("key")
            if key:
                result[key] = cat
                to_cache.append({"merchant_key": key, "category": cat, "source": "ai", "confidence": conf})

        if to_cache:
            await _save_to_cache(to_cache)
        return result
    except Exception as exc:
        logger.error("ai_categorize_failed", error=str(exc))
        return {}


# ── Resultado de categorización ───────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class CategorizedItem:
    idx: int                    # índice original en la lista de entrada
    raw_description: str
    merchant_key: str
    amount: int
    category: str               # categoría final
    label: str                  # etiqueta es-CL para UI
    source: str                 # "rule" | "cache" | "ai" | "fallback"


# ── Función principal ────────────────────────────────────────────────────────

async def categorize_movements(
    movements: list[dict[str, Any]],
) -> list[CategorizedItem]:
    """
    Categoriza una lista de movimientos en 3 capas. Devuelve un item por
    movimiento de entrada, en el mismo orden.

    Cada `movement` debe tener al menos `amount` (int) y `description` (str).
    """
    _placeholder: CategorizedItem | None = None
    out: list[CategorizedItem | None] = [_placeholder] * len(movements)
    needs_cache: list[tuple[int, str, int, str]] = []  # (idx, mkey, amount, raw)

    # Capa 1
    for i, m in enumerate(movements):
        amount = int(m.get("amount", 0) or 0)
        raw = (m.get("description") or "").strip()
        if amount == 0:
            continue
        cat = _apply_layer1(raw, amount)
        if cat:
            out[i] = CategorizedItem(
                idx=i, raw_description=raw, merchant_key=normalize_merchant(raw),
                amount=amount, category=cat, label=CATEGORY_LABELS[cat], source="rule",
            )
        else:
            needs_cache.append((i, normalize_merchant(raw), amount, raw))

    # Capa 2
    cache_keys = sorted({mkey for _, mkey, _, _ in needs_cache if mkey})
    cache_hits = await _lookup_cache(cache_keys)
    needs_ai: list[tuple[int, str, int, str]] = []
    for i, mkey, amount, raw in needs_cache:
        if mkey in cache_hits:
            cat = cache_hits[mkey]
            out[i] = CategorizedItem(
                idx=i, raw_description=raw, merchant_key=mkey,
                amount=amount, category=cat, label=CATEGORY_LABELS.get(cat, "Gasto"), source="cache",
            )
        else:
            needs_ai.append((i, mkey, amount, raw))

    # Capa 3 (en batches)
    if needs_ai:
        ai_keys = sorted({mkey for _, mkey, _, _ in needs_ai if mkey})
        ai_results: dict[str, str] = {}
        bs = settings.categorize_max_keys_per_ai_call
        for j in range(0, len(ai_keys), bs):
            batch = ai_keys[j : j + bs]
            ai_results.update(await _categorize_with_ai(batch))

        for i, mkey, amount, raw in needs_ai:
            cat = ai_results.get(mkey, "other")
            source = "ai" if mkey in ai_results else "fallback"
            out[i] = CategorizedItem(
                idx=i, raw_description=raw, merchant_key=mkey,
                amount=amount, category=cat, label=CATEGORY_LABELS.get(cat, "Gasto"), source=source,
            )

    # Rellenar huecos (movimientos con amount=0 saltados arriba)
    for i, m in enumerate(movements):
        if out[i] is None:
            raw = (m.get("description") or "").strip()
            out[i] = CategorizedItem(
                idx=i, raw_description=raw, merchant_key=normalize_merchant(raw),
                amount=int(m.get("amount", 0) or 0),
                category="other", label=CATEGORY_LABELS["other"], source="fallback",
            )

    logger.info(
        "categorize_done",
        total=len(movements),
        rule=sum(1 for x in out if x and x.source == "rule"),
        cache=sum(1 for x in out if x and x.source == "cache"),
        ai=sum(1 for x in out if x and x.source == "ai"),
        fallback=sum(1 for x in out if x and x.source == "fallback"),
    )
    return [x for x in out if x is not None]
