"""sky.domain.aria — ARIA pipeline v2 (paridad ariaService.js)."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from sky.core.db import get_aria_client, get_engine
from sky.core.logging import get_logger

logger = get_logger("aria")

# ── AnonProfile ───────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class AnonProfile:
    age_range: str
    region: str
    income_range: str
    occupation: str


_VALID_AGE_RANGES = frozenset(["18-25", "26-35", "36-45", "46-55", "55+", "under-18", "prefer_not"])
_VALID_INCOME_BUCKETS = frozenset(["0-500k", "500k-1M", "1M-2M", "2M-5M", "5M+", "prefer_not"])
_VALID_OCCUPATIONS = frozenset([
    "empleado", "independiente", "emprendedor",
    "estudiante", "jubilado", "desempleado", "prefer_not",
])

_AMOUNT_RANGES: dict[str, tuple[int, int]] = {
    "0-50k":     (1_000,       50_000),
    "50k-150k":  (50_001,     150_000),
    "150k-500k": (150_001,    500_000),
    "500k-1.5M": (500_001,  1_500_000),
    "1.5M+":     (1_500_001, 5_000_000),
}


def _normalize_age_range(r: str | None) -> str:
    return r if r in _VALID_AGE_RANGES else "unknown"


def _normalize_income_bucket(r: str | None) -> str:
    return r if r in _VALID_INCOME_BUCKETS else "unknown"


def _normalize_occupation(r: str | None) -> str:
    return r if r in _VALID_OCCUPATIONS else "unknown"


def _get_region_bucket(region: str | None) -> str:
    if not region:
        return "unknown"
    r = region.lower()
    if "rm" in r or "metropolitana" in r:
        if "sur" in r:
            return "RM-Sur"
        if "norte" in r:
            return "RM-Norte"
        if "oriente" in r:
            return "RM-Oriente"
        return "RM-Central"
    if "valparaí" in r or "valparai" in r:
        return "Valparaíso"
    if "biobío" in r or "biobio" in r:
        return "Biobío"
    if "araucan" in r:
        return "La Araucanía"
    if "antofagasta" in r:
        return "Antofagasta"
    if "coquimbo" in r:
        return "Coquimbo"
    if "los lagos" in r:
        return "Los Lagos"
    if "higgins" in r:
        return "O'Higgins"
    if "maule" in r:
        return "Maule"
    return "Otra región"


def _get_period() -> str:
    n = datetime.now(UTC)
    q = (n.month - 1) // 3 + 1
    return f"{n.year}-Q{q}"


def _random_in_bucket(bucket: str) -> int:
    r = _AMOUNT_RANGES.get(bucket)
    if not r:
        return random.randint(1_000, 50_000)
    return random.randint(r[0], r[1])


# ── Amount bucket helpers ─────────────────────────────────────────────────────

def get_amount_bucket(amount: int | float) -> str:
    if not amount or amount <= 0:
        return "0-50k"
    if amount <= 50_000:
        return "0-50k"
    if amount <= 150_000:
        return "50k-150k"
    if amount <= 500_000:
        return "150k-500k"
    if amount <= 1_500_000:
        return "500k-1.5M"
    return "1.5M+"


def get_goal_target_bucket(amount: int | float | None) -> str | None:
    if not amount or amount <= 0:
        return None
    if amount <= 500_000:
        return "0-500k"
    if amount <= 2_000_000:
        return "500k-2M"
    if amount <= 10_000_000:
        return "2M-10M"
    if amount <= 30_000_000:
        return "10M-30M"
    return "30M+"


# ── AnonProfile builder ───────────────────────────────────────────────────────

def build_anon_profile(profile: dict[str, Any]) -> AnonProfile:
    raw_age = profile.get("age_range")
    raw_region = profile.get("region")
    raw_income = profile.get("income_range")
    raw_occ = profile.get("occupation")
    return AnonProfile(
        age_range=_normalize_age_range(raw_age if isinstance(raw_age, str) else None),
        region=_get_region_bucket(raw_region if isinstance(raw_region, str) else None),
        income_range=_normalize_income_bucket(raw_income if isinstance(raw_income, str) else None),
        occupation=_normalize_occupation(raw_occ if isinstance(raw_occ, str) else None),
    )


# ── Clasificadores de texto (paridad exacta con ariaService.js) ───────────────

def classify_motivation(text: str) -> str:
    t = text.lower()
    if re.search(r"seguridad|emergencia|fondo\s+de\s+emergencia|colch[oó]n|proteger|estabilidad|respaldo|imprevist|crisis|desemplead|perder.+trabajo|enfermedad|accidente", t):
        return "security"
    if re.search(r"familia|hijo[sao]?|pareja|matrimonio|casarse|boda|beb[eé]|embarazad|pap[aá]|mam[aá]|crianza|colegio.+ni[nñ]o", t):
        return "family"
    if re.search(r"viaje|viajar|vacacion|conocer|aventura|experiencia|concierto|festival|verano|intercambio|mochilero|turismo", t):
        return "experience"
    if re.search(r"casa\s+propia|departamento\s+propio|independencia|independizarse|vivir\s+sol[ao]|libertad|no\s+depender|emprender|negocio\s+propio|renunciar", t):
        return "freedom"
    if re.search(r"auto\s+nuevo|iphone|macbook|computador|notebook|ropa.+marca|dise[nñ]ador|lujo|primera\s+clase|impresionar|aparentar", t):
        return "status"
    return "unknown"


def classify_blocker(text: str) -> str:
    t = text.lower()
    if re.search(r"impulso|antojo|ganas\s+de|tentaci[oó]n|no\s+pude\s+resistir|compr[eé]\s+sin|sin\s+pensar|descuento|sale|black\s+friday|cyber\s+day", t):
        return "impulse"
    if re.search(r"amigo[sao]?|juntarse|salida[s]?|carrete|carretear|fiesta|cumplea[nñ]os|todos\s+(van|fueron)|no\s+quiero\s+quedar\s+mal|compromisos", t):
        return "social_pressure"
    if re.search(r"no\s+alcanza|no\s+me\s+alcanza|sueldo|ingreso|plata.+no\s+llega|siempre\s+falta|nunca\s+sobra|deuda[s]?|pr[eé]stamo|cr[eé]dito|cuota[s]?|sobregir|rojo", t):
        return "income_gap"
    if re.search(r"siempre\s+lo\s+hago|toda\s+la\s+vida|costumbre|h[aá]bito|dif[ií]cil\s+cambiar|no\s+puedo\s+evitar|autom[aá]tico|sin\s+darme\s+cuenta|rutina", t):
        return "habit"
    if re.search(r"no\s+s[eé]|no\s+entiendo|confundido|no\s+tengo\s+idea|nunca\s+aprend[ií]|nadie\s+me\s+ense[nñ][oó]|me\s+pierdo|complicado", t):
        return "knowledge"
    return "unknown"


def classify_mindset(text: str) -> str:
    t = text.lower()
    if re.search(r"ahorr|guardar\s+plata|reserva|fondo|invertir|inversi[oó]n|no\s+gastar|gastar\s+menos|recortar|presupuesto|disciplina", t):
        return "saver"
    if re.search(r"gastar|disfrutar\s+(ahora|hoy|la\s+vida)|yolo|solo\s+se\s+vive\s+una\s+vez|vivir\s+el\s+momento|plata\s+es\s+para\s+gastarla", t):
        return "spender"
    if re.search(r"evito|no\s+miro|da\s+miedo|me\s+da\s+ansied|me\s+angustia|no\s+quiero\s+ver|prefiero\s+no\s+saber|postergar", t):
        return "avoider"
    return "balanced"


def classify_stress(text: str) -> str:
    t = text.lower()
    if re.search(r"angustia|desesperado|no\s+puedo\s+dormir|p[aá]nico|hundido|muy\s+mal|p[eé]simo|crisis\s+total|no\s+veo\s+salida|muy\s+preocupado", t):
        return "high"
    if re.search(r"tranquil[ao]|bien\s+(econ[oó]micamente|con\s+la\s+plata)|ordenado|bajo\s+control|no\s+me\s+preocupa|contento\s+con|sin\s+problemas", t):
        return "low"
    return "medium"


def classify_orientation(text: str) -> str:
    t = text.lower()
    if re.search(r"este\s+mes|esta\s+semana|ahora\s+mismo|ya\b|urgente|antes\s+de\s+fin\s+de\s+mes|cuanto\s+antes|a\s+corto\s+plazo", t):
        return "short_term"
    if re.search(r"largo\s+plazo|futuro|retiro|jubilaci[oó]n|pensi[oó]n|herencia|construir.+futuro|poco\s+a\s+poco|toda\s+la\s+vida", t):
        return "long_term"
    return "mixed"


def classify_behavior_shift(user_message: str, mr_money_reply: str) -> str:
    combined = f"{user_message} {mr_money_reply}".lower()
    if re.search(r"voy a|voy a intentar|me compromet[ií]|empezar[eé]|desde hoy|lo voy a hacer|tiene sentido|entend[ií]|gracias.+(tip|consejo|idea)|lo voy a aplicar", combined):
        return "positive"
    if re.search(r"no puedo|imposible|no sirve|no funciona|no quiero|no voy a|no me ayuda", combined):
        return "negative"
    return "neutral"


def classify_goal_type(title: str) -> str:
    t = (title or "").lower()
    mapping: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"departamento|casa\s+propia|vivienda|hogar|arriendo|hipoteca"), "housing"),
        (re.compile(r"auto|moto|veh[ií]culo|furg[oó]n|camioneta"), "vehicle"),
        (re.compile(r"educaci[oó]n|universidad|postgrado|mag[ií]ster|curso|carrera|estudio"), "education"),
        (re.compile(r"viaje|vacacion|intercambio|mochilero|turismo"), "travel"),
        (re.compile(r"emergencia|fondo|colch[oó]n|respaldo|imprevist"), "emergency"),
        (re.compile(r"matrimonio|boda|beb[eé]|hijo|familia|crianza"), "life_event"),
        (re.compile(r"inversi[oó]n|fondo\s+mutuo|acciones|cripto|bolsa"), "investment"),
    ]
    for pattern, goal_type in mapping:
        if pattern.search(t):
            return goal_type
    return "other"


def has_significant_content(content: str) -> bool:
    if not content or len(content.strip().split()) < 5:
        return False
    return bool(re.search(
        r"plata|dinero|peso[s]?|gasto[s]?|ahorro[s]?|sueldo|ingreso|deuda|meta|objetivo|presupuesto|compra|gastar|ahorrar|invertir|financ|bolsillo|cuenta|banco|tarjeta",
        content,
    ))


# ── Consent guard ─────────────────────────────────────────────────────────────

async def _has_aria_consent(user_id: str) -> bool:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            rs = await conn.execute(
                text("SELECT aria_consent FROM public.profiles WHERE id = :uid"),
                {"uid": user_id},
            )
            row = rs.mappings().first()
            if row is None:
                return False
            return bool(row["aria_consent"])
    except Exception:
        return False  # fail-safe


# ── Public pipeline functions ─────────────────────────────────────────────────

async def track_spending_event(
    profile: AnonProfile,
    tx: dict[str, Any],
    user_id: str | None = None,
) -> None:
    try:
        if not user_id or not await _has_aria_consent(user_id):
            return

        bucket = get_amount_bucket(abs(float(tx.get("amount") or 0)))

        get_aria_client().schema("aria").from_("spending_patterns").insert({
            "age_range":     profile.age_range,
            "region":        profile.region,
            "income_range":  profile.income_range,
            "occupation":    profile.occupation,
            "category":      str(tx.get("category") or "other"),
            "amount_bucket": bucket,
            "amount_noise":  _random_in_bucket(bucket),
            "source":        str(tx.get("source") or "manual"),
            "period":        _get_period(),
            "batch_id":      str(uuid4()),
        }).execute()

    except Exception as exc:
        logger.warning("aria_spending_failed", error=str(exc))


async def track_goal_event(
    profile: AnonProfile,
    goal: dict[str, Any],
    completion_rate: float = 0,
    goal_status: str = "active",
    user_id: str | None = None,
) -> None:
    try:
        if not user_id or not await _has_aria_consent(user_id):
            return

        projection = goal.get("projection")
        months_to_goal = None
        if isinstance(projection, dict):
            months_to_goal = projection.get("months_to_goal")

        target = goal.get("target_amount") or goal.get("targetAmount")

        get_aria_client().schema("aria").from_("goal_signals").insert({
            "age_range":       profile.age_range,
            "region":          profile.region,
            "income_range":    profile.income_range,
            "occupation":      profile.occupation,
            "goal_type":       classify_goal_type(str(goal.get("title") or "")),
            "goal_tier":       str(goal.get("type") or "secundaria"),
            "target_bucket":   get_goal_target_bucket(float(target) if target else None),
            "completion_rate": min(100, max(0, round(completion_rate))),
            "months_to_goal":  months_to_goal,
            "goal_status":     goal_status,
            "period":          _get_period(),
            "batch_id":        str(uuid4()),
        }).execute()

    except Exception as exc:
        logger.warning("aria_goal_failed", error=str(exc))


async def track_behavioral_signal(
    profile: AnonProfile,
    user_message: str,
    mr_money_reply: str = "",
    user_id: str | None = None,
) -> None:
    try:
        if not user_id or not await _has_aria_consent(user_id):
            return

        full_context = f"{user_message} {mr_money_reply}"
        if not has_significant_content(full_context):
            return

        get_aria_client().schema("aria").from_("behavioral_signals").insert({
            "age_range":           profile.age_range,
            "region":              profile.region,
            "income_range":        profile.income_range,
            "occupation":          profile.occupation,
            "motivation_category": classify_motivation(full_context),
            "blocker_type":        classify_blocker(full_context),
            "financial_mindset":   classify_mindset(full_context),
            "stress_level":        classify_stress(full_context),
            "goal_orientation":    classify_orientation(full_context),
            "behavior_shift":      classify_behavior_shift(user_message, mr_money_reply),
            "period":              _get_period(),
            "batch_id":            str(uuid4()),
        }).execute()

    except Exception as exc:
        logger.warning("aria_behavioral_failed", error=str(exc))
