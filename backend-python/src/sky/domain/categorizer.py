"""
sky.domain.categorizer — Categorización con feedback loop (5 niveles).

Jerarquía de resolución (sprint "categorización que aprende", 2026-06):
    0. Voto propio del usuario (`merchant_category_votes`) — override privado
       inmediato, con prefix matching. Nunca lo pisa nada.
    1. Caché global `merchant_categories` con source='user' — consenso
       crowdsourced (>= N usuarios distintos); puede corregir una regla
       equivocada PARA TODOS. La IA no puede pisar estas filas (guarda en
       `upsert_merchant_category`, migración 014).
    2. Reglas regex deterministas — sin tokens, instantáneo.
    3. Caché global con source 'rule'/'ai' (semillas + resultados IA previos)
       con prefix matching progresivo — por debajo de las reglas, igual que
       siempre.
    4. Claude Haiku batch 20 keys/call. Resultado se guarda en cache.

Los votos los escribe sky.domain.merchant_feedback cuando el usuario
recategoriza (era el "§4 votos crowdsourced" diferido desde Fase 6).

Si Claude no logra confidence >= 0.75 → "other". Si la capa IA falla
(rate limit, error de red), todas las filas restantes se marcan "fallback"
para no quedar en loop infinito.
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
    (lambda d, a: a > 0 and re.search(r"^traspaso\s+de:", d, re.I) is not None,                        "transfer"),
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


TRANSFER_PREFIX_RE = re.compile(
    r"^(?:traspaso\s+(?:de|a)|transferencia\s+a):\s*",
    re.IGNORECASE,
)


def merchant_display(raw_description: str | None) -> str | None:
    """Nombre de comercio/contraparte para mostrar en UI (Title Case)."""
    if not raw_description:
        return None
    s = raw_description.strip()
    m = TRANSFER_PREFIX_RE.match(s)
    if m:
        counterparty = s[m.end():].strip()
        return counterparty.title() or None
    key = normalize_merchant(s)
    return key.title() or None


def _key_variants(merchant_key: str) -> list[str]:
    """`'jumbo las condes' → ['jumbo las condes', 'jumbo las', 'jumbo']`."""
    if not merchant_key:
        return []
    words = [w for w in merchant_key.split(" ") if w]
    return [" ".join(words[:i]) for i in range(len(words), 0, -1)]


async def merchant_display_batch(
    user_id: str | None,
    raw_descriptions: list[str | None],
) -> list[str | None]:
    """Display de comercio para una página de transacciones, con aliases.

    Resolución por fila (sprint Fase 2): alias propio del usuario → alias
    global por consenso (`merchant_display_names`) → `merchant_display`
    (Title Case). Prefix matching progresivo en ambos niveles, igual que
    los votos. El override propio gana SIEMPRE al global, aunque el global
    sea más específico.

    Guarda de lectura (defensa en profundidad sobre la frontera de
    privacidad): keys con prefijo de transferencia jamás consultan el global
    — la contraparte es una persona y esa tabla no debe contenerlas. El
    alias PROPIO sí aplica (renombre privado de la contraparte).

    Fail-open: el display es un realce, no puede botar la lista de
    transacciones. Si el lookup de aliases falla se degrada al Title Case
    con warning en logs.
    """
    out = [merchant_display(r) for r in raw_descriptions]
    keys = [normalize_merchant(r) if r and r.strip() else "" for r in raw_descriptions]

    own_variants = (
        sorted({v for k in keys if k for v in _key_variants(k)}) if user_id else []
    )
    global_variants = sorted({
        v
        for k in keys
        if k and TRANSFER_PREFIX_RE.match(k) is None
        for v in _key_variants(k)
    })
    if not own_variants and not global_variants:
        return out

    own_map: dict[str, str] = {}
    glob_map: dict[str, str] = {}
    try:
        engine: AsyncEngine = get_engine()
        async with engine.connect() as conn:
            if own_variants:
                rs = await conn.execute(
                    text(
                        "SELECT merchant_key, display_name"
                        "  FROM public.merchant_aliases"
                        " WHERE user_id = CAST(:uid AS uuid)"
                        "   AND merchant_key = ANY(:keys)"
                    ),
                    {"uid": user_id, "keys": own_variants},
                )
                own_map = {
                    str(r.merchant_key): str(r.display_name) for r in rs.fetchall()
                }
            if global_variants:
                rs = await conn.execute(
                    text(
                        "SELECT merchant_key, display_name"
                        "  FROM public.merchant_display_names"
                        " WHERE merchant_key = ANY(:keys)"
                    ),
                    {"keys": global_variants},
                )
                glob_map = {
                    str(r.merchant_key): str(r.display_name) for r in rs.fetchall()
                }
    except Exception as exc:
        logger.warning("alias_lookup_failed", error=str(exc))
        return out

    for i, k in enumerate(keys):
        if not k:
            continue
        variants = _key_variants(k)
        hit = next((own_map[v] for v in variants if v in own_map), None)
        if hit is None and TRANSFER_PREFIX_RE.match(k) is None:
            hit = next((glob_map[v] for v in variants if v in glob_map), None)
        if hit is not None:
            out[i] = hit
    return out


# ── Caché global con prefix matching (niveles 1 y 3) ─────────────────────────

async def _lookup_cache(merchant_keys: list[str]) -> dict[str, tuple[str, str]]:
    """Devuelve {merchant_key: (category, source)} — el source decide el nivel:
    'user' (consenso crowdsourced) resuelve ANTES de las reglas; 'rule'/'ai'
    después, como siempre."""
    if not merchant_keys:
        return {}
    all_variants = sorted({v for k in merchant_keys for v in _key_variants(k)})
    if not all_variants:
        return {}

    engine: AsyncEngine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text(
                "SELECT merchant_key, category, source"
                "  FROM public.merchant_categories"
                " WHERE merchant_key = ANY(:keys)"
            ),
            {"keys": all_variants},
        )
        rows = rs.fetchall()

    variant_map = {r.merchant_key: (str(r.category), str(r.source)) for r in rows}
    out: dict[str, tuple[str, str]] = {}
    for key in merchant_keys:
        for v in _key_variants(key):
            if v in variant_map:
                out[key] = variant_map[v]
                break
    return out


# ── Nivel 0: votos propios del usuario ───────────────────────────────────────

async def _lookup_user_votes(
    pairs: list[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    """Votos propios por (user_id, merchant_key) con prefix matching progresivo.

    Devuelve {(user_id, merchant_key_original): category}. Una sola consulta
    para todo el batch (que puede mezclar usuarios); el filtrado por par
    exacto se hace acá — un voto jamás se aplica a otro usuario.
    """
    pairs = [(u, k) for u, k in pairs if u and k]
    if not pairs:
        return {}
    uids = sorted({u for u, _ in pairs})
    variants = sorted({v for _, k in pairs for v in _key_variants(k)})
    if not variants:
        return {}

    engine: AsyncEngine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text(
                "SELECT user_id, merchant_key, category"
                "  FROM public.merchant_category_votes"
                " WHERE user_id = ANY(CAST(:uids AS uuid[]))"
                "   AND merchant_key = ANY(:keys)"
            ),
            {"uids": uids, "keys": variants},
        )
        rows = rs.fetchall()

    vote_map = {(str(r.user_id), str(r.merchant_key)): str(r.category) for r in rows}
    out: dict[tuple[str, str], str] = {}
    for uid, key in pairs:
        for v in _key_variants(key):
            hit = vote_map.get((uid, v))
            if hit:
                out[(uid, key)] = hit
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
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
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
    source: str                 # "vote" | "rule" | "cache" | "ai" | "fallback"


# ── Función principal ────────────────────────────────────────────────────────

async def categorize_movements(
    movements: list[dict[str, Any]],
) -> list[CategorizedItem]:
    """
    Categoriza una lista de movimientos en 5 niveles (ver docstring del
    módulo). Devuelve un item por movimiento de entrada, en el mismo orden.

    Cada `movement` debe tener al menos `amount` (int) y `description` (str).
    `user_id` es opcional: si viene, los votos propios de ese usuario tienen
    prioridad máxima (override privado). El batch puede mezclar usuarios.
    """
    _placeholder: CategorizedItem | None = None
    out: list[CategorizedItem | None] = [_placeholder] * len(movements)

    _Pending = tuple[int, str, int, str, str | None]  # (idx, mkey, amount, raw, uid)
    pending: list[_Pending] = []
    for i, m in enumerate(movements):
        amount = int(m.get("amount", 0) or 0)
        raw = (m.get("description") or "").strip()
        if amount == 0:
            continue
        uid = m.get("user_id")
        pending.append((i, normalize_merchant(raw), amount, raw, str(uid) if uid else None))

    def _item(idx: int, mkey: str, amount: int, raw: str, cat: str, source: str) -> CategorizedItem:
        return CategorizedItem(
            idx=idx, raw_description=raw, merchant_key=mkey, amount=amount,
            category=cat, label=CATEGORY_LABELS.get(cat, "Gasto"), source=source,
        )

    # Nivel 0: votos propios del usuario (override privado inmediato)
    vote_pairs = sorted({(uid, mkey) for _, mkey, _, _, uid in pending if uid and mkey})
    vote_hits = await _lookup_user_votes(list(vote_pairs))
    after_votes: list[_Pending] = []
    for i, mkey, amount, raw, uid in pending:
        cat_hit = vote_hits.get((uid, mkey)) if uid and mkey else None
        if cat_hit:
            out[i] = _item(i, mkey, amount, raw, cat_hit, "vote")
        else:
            after_votes.append((i, mkey, amount, raw, uid))

    # Caché global: una sola consulta alimenta los niveles 1 y 3
    cache_keys = sorted({mkey for _, mkey, _, _, _ in after_votes if mkey})
    cache_hits = await _lookup_cache(cache_keys)

    # Nivel 1: consenso crowdsourced (source='user') — corrige incluso reglas
    after_crowd: list[_Pending] = []
    for i, mkey, amount, raw, uid in after_votes:
        hit = cache_hits.get(mkey)
        if hit is not None and hit[1] == "user":
            out[i] = _item(i, mkey, amount, raw, hit[0], "cache")
        else:
            after_crowd.append((i, mkey, amount, raw, uid))

    # Nivel 2: reglas deterministas
    after_rules: list[_Pending] = []
    for i, mkey, amount, raw, uid in after_crowd:
        cat = _apply_layer1(raw, amount)
        if cat:
            out[i] = _item(i, mkey, amount, raw, cat, "rule")
        else:
            after_rules.append((i, mkey, amount, raw, uid))

    # Nivel 3: caché global (semillas 'rule' + resultados 'ai' previos)
    needs_ai: list[_Pending] = []
    for i, mkey, amount, raw, uid in after_rules:
        hit = cache_hits.get(mkey)
        if hit is not None:
            out[i] = _item(i, mkey, amount, raw, hit[0], "cache")
        else:
            needs_ai.append((i, mkey, amount, raw, uid))

    # Nivel 4: IA (en batches)
    if needs_ai:
        ai_keys = sorted({mkey for _, mkey, _, _, _ in needs_ai if mkey})
        ai_results: dict[str, str] = {}
        bs = settings.categorize_max_keys_per_ai_call
        for j in range(0, len(ai_keys), bs):
            batch = ai_keys[j : j + bs]
            ai_results.update(await _categorize_with_ai(batch))

        for i, mkey, amount, raw, _uid in needs_ai:
            cat = ai_results.get(mkey, "other")
            source = "ai" if mkey in ai_results else "fallback"
            out[i] = _item(i, mkey, amount, raw, cat, source)

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
        vote=sum(1 for x in out if x and x.source == "vote"),
        rule=sum(1 for x in out if x and x.source == "rule"),
        cache=sum(1 for x in out if x and x.source == "cache"),
        ai=sum(1 for x in out if x and x.source == "ai"),
        fallback=sum(1 for x in out if x and x.source == "fallback"),
    )
    return [x for x in out if x is not None]
