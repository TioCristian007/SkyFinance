"""sky.domain.mr_money — Copiloto financiero Mr. Money (paridad aiService.js)."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

import anthropic
from sqlalchemy import text

from sky.api.schemas.chat import (
    ChatTextResponse,
    ChatTurn,
    NavigationResponse,
    ProposeChallenge,
)
from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.core.metrics import sky_mr_money_tokens
from sky.domain.challenges import MOCK_CHALLENGES
from sky.domain.finance import CATEGORY_LABELS, compute_summary, top_categories
from sky.domain.simulations import compute_projection

logger = get_logger("mr_money")

# ── Emotion detection constants ───────────────────────────────────────────────

_VALID_EMOTIONS = frozenset({
    "alivio", "ansiedad", "frustración", "orgullo",
    "vergüenza", "esperanza", "tristeza", "neutro", "otro",
})

_VALID_SIGNAL_KINDS = frozenset({
    "disclosure", "venting", "progress", "regression", "inquiry",
})

# ── Anthropic client (singleton) ──────────────────────────────────────────────

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_clp(n: int) -> str:
    return f"${n:,}".replace(",", ".")


def _get_period() -> str:
    n = datetime.now(UTC)
    q = (n.month - 1) // 3 + 1
    return f"{n.year}-Q{q}"


# ── Tools ─────────────────────────────────────────────────────────────────────

MR_MONEY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "compute_projection",
        "description": (
            "Calcula proyección de ahorro con interés compuesto. "
            "Úsala para preguntas sobre plazos, 'cuándo puedo lograr X', o 'cuánto necesito ahorrar'. "
            "Devuelve meses para la meta y si es factible."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_amount":    {"type": "integer", "description": "Monto objetivo en CLP."},
                "monthly_savings":  {"type": "integer", "description": "Ahorro mensual en CLP."},
                "current_savings":  {"type": "integer", "description": "Ahorro acumulado actual en CLP. Default 0."},
                "annual_return_pct": {"type": "number",  "description": "Retorno anual esperado en %. Default 0."},
            },
            "required": ["target_amount", "monthly_savings"],
        },
    },
    {
        "name": "propose_challenge",
        "description": (
            "Propone activar uno de los desafíos del catálogo fijo de Sky. "
            "NO lo activa directamente — el usuario debe confirmar. "
            "Úsala cuando detectas un gasto alto en una categoría o el usuario pide un desafío. "
            "Elige el challenge_id más relevante del catálogo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "challenge_id": {
                    "type": "string",
                    "enum": [c["id"] for c in MOCK_CHALLENGES],
                    "description": "ID del desafío del catálogo a proponer.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Por qué este desafío es relevante ahora (1-2 frases).",
                },
            },
            "required": ["challenge_id", "reasoning"],
        },
        "cache_control": {"type": "ephemeral"},  # cache all tools up to this point
    },
    {
        "name": "read_profile",
        "description": (
            "Lee el perfil cualitativo aprendido del usuario. "
            "Úsala cuando necesites recordar la mentalidad, estrés o motivaciones ya detectadas."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "update_profile_dimension",
        "description": (
            "Actualiza una dimensión del perfil cualitativo del usuario cuando detectas evidencia FUERTE "
            "(patrón claro, no especulación). Úsala con moderación — solo cuando el usuario revela algo "
            "consistente y concreto sobre su mentalidad, motivación o actitud financiera. "
            "Dimensiones válidas: savings_mindset, risk_tolerance, goal_orientation, motivation_primary, "
            "stress_baseline, recurring_blockers, protective_behaviors."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dimension": {
                    "type": "string",
                    "description": "Nombre de la dimensión a actualizar.",
                },
                "value": {
                    "description": "Nuevo valor (string, int o lista según la dimensión).",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confianza 0.0–1.0 basada en la evidencia del mensaje.",
                },
                "evidence": {
                    "type": "string",
                    "description": "Texto libre que justifica la actualización (va a logs, NO al perfil).",
                },
            },
            "required": ["dimension", "value", "confidence", "evidence"],
        },
    },
]

# Tools solo para usuarios premium (infer_emotional_state).
# Se agregan dinámicamente en _build_tools_for_user().
_EMOTION_TOOL: dict[str, Any] = {
    "name": "infer_emotional_state",
    "description": (
        "Infiere el estado emocional del usuario a partir de su mensaje. "
        "Úsala al cerrar cada turno cuando detectes una emoción clara. "
        "No la menciones al usuario — es transparente."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "emotion": {
                "type": "string",
                "enum": sorted(_VALID_EMOTIONS),
                "description": "Emoción principal detectada.",
            },
            "intensity": {
                "type": "integer",
                "description": "Intensidad 0 (mínima) a 10 (máxima).",
            },
            "signal_kind": {
                "type": "string",
                "enum": sorted(_VALID_SIGNAL_KINDS),
                "description": "Tipo de señal: disclosure, venting, progress, regression, inquiry.",
            },
        },
        "required": ["emotion", "intensity", "signal_kind"],
    },
}

# ── Premium gate ─────────────────────────────────────────────────────────────

async def _is_premium_user(user_id: str) -> bool:
    """Devuelve True si el usuario tiene tier premium.

    profiles.tier no existe aún (deuda documentada en 08_ESTADO_Y_DEUDA.md).
    Mientras, todos los usuarios son tratados como free → retorna False.
    Cuando se agregue la columna tier, reemplazar esta implementación.
    """
    # TODO: leer profiles.tier cuando exista la columna
    return not settings.emotion_inference_premium_only


def _build_tools_for_user(is_premium: bool) -> list[dict[str, Any]]:
    """Construye la lista de tools según el tier del usuario."""
    if is_premium:
        return [*MR_MONEY_TOOLS, _EMOTION_TOOL]
    return MR_MONEY_TOOLS


# ── Local patterns (resolved without Anthropic) ───────────────────────────────

_GREETING_RE = re.compile(
    r"^(hola|buenos\s+(d[ií]as|tardes|noches)|hey|qu[eé]\s+tal)\s*[!?]?$",
    re.IGNORECASE,
)

_NAV_RE = re.compile(
    r"ver\s+mis\s+(metas|desaf[ií]os|cuentas|movimientos)",
    re.IGNORECASE,
)
_NAV_ROUTES: dict[str, tuple[str, str]] = {
    "metas":       ("/goals",        "Mis metas"),
    "desafíos":    ("/challenges",   "Mis desafíos"),
    "desafios":    ("/challenges",   "Mis desafíos"),
    "cuentas":     ("/accounts",     "Mis cuentas"),
    "movimientos": ("/transactions", "Mis movimientos"),
}

_CHALLENGE_STATUS_RE = re.compile(
    r"c[oó]mo\s+va\s+mi\s+desaf[ií]o|estado\s+de\s+mi\s+desaf[ií]o",
    re.IGNORECASE,
)

# ── Financial context builder ─────────────────────────────────────────────────

async def _fetch_profile_flags(user_id: str) -> tuple[bool, bool]:
    """Devuelve (count_transfers_as_income, count_transfers_as_expense)."""
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT COALESCE(count_transfers_as_income,  true),
                       COALESCE(count_transfers_as_expense, true)
                  FROM public.profiles
                 WHERE id = :uid
                 LIMIT 1
            """),
            {"uid": user_id},
        )
        row = rs.fetchone()
    if row:
        return bool(row[0]), bool(row[1])
    return True, True


async def _fetch_transactions(user_id: str) -> list[dict[str, Any]]:
    now_cl = datetime.now(ZoneInfo("America/Santiago"))
    since = now_cl.date().replace(day=1)
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT amount, category, description, date
                  FROM public.transactions
                 WHERE user_id = :uid
                   AND date >= :since
                   AND deleted_at IS NULL
            """),
            {"uid": user_id, "since": since},
        )
        return [dict(r) for r in rs.mappings().all()]


async def _build_financial_context(user_id: str) -> tuple[str, dict[str, Any]]:
    from sky.domain.challenges import get_challenges
    from sky.domain.financial_profile import get_profile
    from sky.domain.goals import get_goals

    txs, goals, challenges, profile_flags, fin_profile = await asyncio.gather(
        _fetch_transactions(user_id),
        get_goals(user_id),
        get_challenges(user_id),
        _fetch_profile_flags(user_id),
        get_profile(user_id),
    )
    count_income, count_expense = profile_flags

    summary = compute_summary(
        txs,
        count_transfers_as_income=count_income,
        count_transfers_as_expense=count_expense,
    )
    cats = top_categories(summary.by_category, limit=5)
    active_chs = challenges.get("active", [])

    cat_text = "\n".join(
        f"  - {CATEGORY_LABELS.get(c['category'], c['category'])}: {_fmt_clp(c['amount'])}"
        for c in cats
    ) or "  sin datos"

    goals_text = "\n".join(
        f"  - id:\"{g['id']}\" \"{g['name']}\": {g.get('progress_pct', 0):.0f}%"
        for g in goals
    ) or "  sin metas"

    chs_text = "\n".join(
        f"  - \"{c['label']}\""
        for c in active_chs
    ) or "  ninguno"

    context_text = (
        f"=== CONTEXTO FINANCIERO ({_get_period()}) ===\n"
        f"RESUMEN: Ingreso {_fmt_clp(summary.income)} | Gastado {_fmt_clp(summary.expenses)} "
        f"| Balance {_fmt_clp(summary.balance)} | Ahorro {summary.savings_rate:.0%}\n"
        f"GASTOS:\n{cat_text}\n"
        f"METAS:\n{goals_text}\n"
        f"DESAFÍOS ACTIVOS:\n{chs_text}"
    )

    if fin_profile:
        profile_lines: list[str] = []
        if fin_profile.savings_mindset and (fin_profile.savings_mindset_conf or 0) >= 0.5:
            profile_lines.append(f"  Mentalidad: {fin_profile.savings_mindset} (conf {fin_profile.savings_mindset_conf:.1f})")
        if fin_profile.motivation_primary and (fin_profile.motivation_primary_conf or 0) >= 0.5:
            profile_lines.append(f"  Motivación: {fin_profile.motivation_primary} (conf {fin_profile.motivation_primary_conf:.1f})")
        if fin_profile.goal_orientation and (fin_profile.goal_orientation_conf or 0) >= 0.5:
            profile_lines.append(f"  Horizonte: {fin_profile.goal_orientation}")
        if fin_profile.risk_tolerance is not None:
            profile_lines.append(f"  Tolerancia al riesgo: {fin_profile.risk_tolerance}/10")
        if fin_profile.stress_baseline is not None:
            profile_lines.append(f"  Estrés base: {fin_profile.stress_baseline}/10")
        if fin_profile.stress_current is not None:
            profile_lines.append(f"  Estrés actual: {fin_profile.stress_current}/10")
        if fin_profile.last_emotion:
            profile_lines.append(f"  Última emoción detectada: {fin_profile.last_emotion}")
        if profile_lines:
            context_text += "\nPERFIL APRENDIDO:\n" + "\n".join(profile_lines)

    return context_text, {"summary": summary, "goals": goals}


def _build_system_prompt(context_text: str, is_premium: bool = False) -> str:
    catalog = "\n".join(f"  - {c['id']}: {c['label']} — {c['desc']}" for c in MOCK_CHALLENGES)
    emotion_instructions = (
        "\nEMOCIÓN (solo premium): Al cerrar cada turno, usa infer_emotional_state si detectas "
        "una emoción clara. No lo menciones al usuario. Es transparente."
        if is_premium else ""
    )
    return f"""Eres Mr. Money, copiloto financiero de Sky.

{context_text}

HERRAMIENTAS (úsalas cuando corresponda):
READ → compute_projection, read_profile
WRITE (requieren aprobación del usuario) → propose_challenge
PERFIL (solo con evidencia fuerte) → update_profile_dimension{emotion_instructions}

CATÁLOGO DE DESAFÍOS (usa el challenge_id EXACTO en propose_challenge):
{catalog}

CUÁNDO USARLAS:
- Usuario pregunta plazos/proyecciones → compute_projection
- Usuario tiene gasto alto en categoría o pide un desafío → propose_challenge relevante
- Necesitas ver el perfil aprendido → read_profile
- Usuario revela patrón claro sobre su mentalidad/motivación (no especular) → update_profile_dimension

PERFIL: Actualiza solo cuando hay evidencia fuerte y consistente. No especules con una sola frase.
PERSONALIDAD: Profesional, directo, cercano. Fórmula: [dato real] + [emoción mínima] + [dirección].
REGLAS: Español de Chile, tuteo (usa 'tienes', 'puedes', 'quieres'; NUNCA voseo como 'tenés', 'podés', 'querés'). Datos reales siempre. Máx 4 líneas. 1-2 emojis. Sin asesoría de inversión. Sin decisiones por el usuario."""


# ── Tool executors ────────────────────────────────────────────────────────────

def _execute_compute_projection(tool_input: dict[str, Any]) -> str:
    result = compute_projection(
        target_amount=int(tool_input.get("target_amount", 0)),
        monthly_savings=int(tool_input.get("monthly_savings", 0)),
        current_savings=int(tool_input.get("current_savings", 0)),
        annual_return_pct=float(tool_input.get("annual_return_pct", 0.0)),
    )
    return json.dumps({
        "feasible":      result.feasible,
        "months_to_goal": result.months_to_goal,
        "final_amount":  result.final_amount,
        "rationale":     result.rationale,
    })


async def _execute_read_profile(user_id: str) -> str:
    from sky.domain.financial_profile import get_profile
    profile = await get_profile(user_id)
    if profile is None:
        return json.dumps({"status": "no_profile_yet"})
    return json.dumps(profile.model_dump(exclude_none=True), default=str)


async def _execute_update_profile(user_id: str, inp: dict[str, Any]) -> str:
    from sky.domain.financial_profile import upsert_profile_dimension
    dimension = str(inp.get("dimension", ""))
    value = inp.get("value")
    confidence = float(inp.get("confidence", 0.5))
    evidence = str(inp.get("evidence", ""))
    logger.info(
        "mr_money_profile_update",
        user_id=user_id,
        dimension=dimension,
        confidence=confidence,
        evidence=evidence[:200],
    )
    try:
        await upsert_profile_dimension(user_id, dimension, value, confidence)
        return json.dumps({"status": "updated", "dimension": dimension})
    except ValueError as e:
        return json.dumps({"error": str(e)})


async def _execute_infer_emotion(user_id: str, inp: dict[str, Any]) -> str:
    from sky.domain.financial_profile import apply_emotion_inference
    emotion = str(inp.get("emotion", "neutro"))
    intensity = min(10, max(0, int(inp.get("intensity", 5))))
    signal_kind = str(inp.get("signal_kind", "inquiry"))
    if emotion not in _VALID_EMOTIONS:
        emotion = "otro"
    if signal_kind not in _VALID_SIGNAL_KINDS:
        signal_kind = "inquiry"
    await apply_emotion_inference(user_id, emotion, intensity, signal_kind)
    return json.dumps({"status": "recorded"})


# ── History helpers ───────────────────────────────────────────────────────────

_MAX_HISTORY_TURNS  = 20
_MAX_HISTORY_TOKENS = 6000   # estimado a 4 chars/token
_CHARS_PER_TOKEN    = 4


def _trim_history(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trunca la lista FIFO hasta _MAX_HISTORY_TURNS y ~_MAX_HISTORY_TOKENS estimados."""
    trimmed = turns[-_MAX_HISTORY_TURNS:]
    total_chars = sum(len(t.get("content", "")) for t in trimmed)
    while trimmed and total_chars > _MAX_HISTORY_TOKENS * _CHARS_PER_TOKEN:
        removed = trimmed.pop(0)
        total_chars -= len(removed.get("content", ""))
    return trimmed


async def _fetch_history_from_db(user_id: str) -> list[dict[str, Any]]:
    """Lee los últimos _MAX_HISTORY_TURNS turnos de mr_money_messages para el usuario."""
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT role, content
                  FROM public.mr_money_messages
                 WHERE user_id = :uid
                 ORDER BY created_at ASC
                 LIMIT :lim
            """),
            {"uid": user_id, "lim": _MAX_HISTORY_TURNS},
        )
        return [{"role": r["role"], "content": r["content"]} for r in rs.mappings().all()]


# ── MrMoney class ─────────────────────────────────────────────────────────────

class MrMoney:
    async def respond(
        self,
        user_id: str,
        message: str,
        history: list[ChatTurn] | None = None,
    ) -> ChatTextResponse | ProposeChallenge | NavigationResponse:
        local = await self._try_local(user_id, message)
        if local is not None:
            return local

        try:
            is_premium = await _is_premium_user(user_id)
            return await self._call_anthropic(user_id, message, history, is_premium=is_premium)
        except Exception as exc:
            if isinstance(exc, (anthropic.AuthenticationError, anthropic.APIStatusError)):
                logger.error(
                    "mr_money_credentials_error",
                    error=str(exc),
                    exc_info=True,
                    note="Verificar ANTHROPIC_API_KEY — credencial inválida o servicio caído",
                )
            else:
                logger.error("mr_money_anthropic_failed", error=str(exc), exc_info=True)
            return ChatTextResponse(
                text="Tuve un problema procesando tu consulta. ¿Puedes repetir?"
            )

    async def _try_local(
        self,
        user_id: str,
        message: str,
    ) -> ChatTextResponse | NavigationResponse | None:
        msg = message.strip()

        if _GREETING_RE.match(msg):
            return ChatTextResponse(
                text="Hola 👋 Soy Mr. Money, tu copiloto financiero. ¿En qué te puedo ayudar hoy?"
            )

        nav_match = _NAV_RE.search(msg)
        if nav_match:
            keyword = nav_match.group(1).lower()
            route, label = _NAV_ROUTES.get(keyword, ("/dashboard", "Inicio"))
            return NavigationResponse(type="navigation", route=route, label=label)

        if _CHALLENGE_STATUS_RE.search(msg):
            from sky.domain.challenges import get_challenges
            challenges = await get_challenges(user_id)
            active = challenges.get("active", [])
            if not active:
                return ChatTextResponse(text="No tienes desafíos activos por el momento.")
            lines = [f"- {c['label']}" for c in active]
            return ChatTextResponse(text="Tus desafíos activos:\n" + "\n".join(lines))

        return None

    async def _call_anthropic(
        self,
        user_id: str,
        message: str,
        history: list[ChatTurn] | None = None,
        is_premium: bool = False,
    ) -> ChatTextResponse | ProposeChallenge | NavigationResponse:
        context_text, raw = await _build_financial_context(user_id)
        system_prompt = _build_system_prompt(context_text, is_premium=is_premium)
        tools = _build_tools_for_user(is_premium)

        # Si el cliente envía history explícito, lo usamos tal cual (sin consulta DB).
        # Si envía None, cargamos desde DB para garantizar continuidad entre sesiones.
        if history is not None:
            prior_turns = [{"role": t.role, "content": t.content} for t in history]
        else:
            prior_turns = await _fetch_history_from_db(user_id)

        prior_turns = _trim_history(prior_turns)
        messages: list[dict[str, Any]] = [*prior_turns, {"role": "user", "content": message}]

        resp = await _get_client().messages.create(
            model=settings.mr_money_model,
            max_tokens=settings.mr_money_max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=tools,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
        )

        logger.info(
            "mr_money_tokens",
            input=resp.usage.input_tokens,
            output=resp.usage.output_tokens,
            cache_read=getattr(resp.usage, "cache_read_input_tokens", 0),
            cache_creation=getattr(resp.usage, "cache_creation_input_tokens", 0),
        )
        sky_mr_money_tokens.labels(type="input").inc(resp.usage.input_tokens)
        sky_mr_money_tokens.labels(type="output").inc(resp.usage.output_tokens)
        if cr := getattr(resp.usage, "cache_read_input_tokens", 0):
            sky_mr_money_tokens.labels(type="cache_read").inc(cr)
        if cc := getattr(resp.usage, "cache_creation_input_tokens", 0):
            sky_mr_money_tokens.labels(type="cache_creation").inc(cc)

        proposals: list[ProposeChallenge] = []
        result_text = ""
        max_iter = 3
        iteration = 0

        while resp.stop_reason == "tool_use" and iteration < max_iter:
            iteration += 1
            tool_results: list[dict[str, Any]] = []

            for block in resp.content:
                if block.type == "text":
                    result_text += block.text + " "

                elif block.type == "tool_use":
                    inp_raw: dict[str, Any] = cast(dict[str, Any], block.input) if isinstance(block.input, dict) else {}

                    if block.name == "compute_projection":
                        tool_output = _execute_compute_projection(inp_raw)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": tool_output,
                        })

                    elif block.name == "propose_challenge":
                        cid = str(inp_raw.get("challenge_id", ""))
                        if any(c["id"] == cid for c in MOCK_CHALLENGES):
                            proposals.append(ProposeChallenge(
                                challenge_id=cid,
                                reasoning=str(inp_raw.get("reasoning", "")),
                            ))
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({"status": "proposal_queued"}),
                            })
                        else:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({"error": f"challenge_id inválido: {cid}"}),
                            })

                    elif block.name == "read_profile":
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": await _execute_read_profile(user_id),
                        })

                    elif block.name == "update_profile_dimension":
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": await _execute_update_profile(user_id, inp_raw),
                        })

                    elif block.name == "infer_emotional_state":
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": await _execute_infer_emotion(user_id, inp_raw),
                        })

                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({"error": f"tool {block.name} not recognized"}),
                        })

            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user",      "content": tool_results})

            resp = await _get_client().messages.create(
                model=settings.mr_money_model,
                max_tokens=settings.mr_money_max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=tools,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
            )
            logger.info(
                "mr_money_tokens",
                input=resp.usage.input_tokens,
                output=resp.usage.output_tokens,
                cache_read=getattr(resp.usage, "cache_read_input_tokens", 0),
                cache_creation=getattr(resp.usage, "cache_creation_input_tokens", 0),
            )
            sky_mr_money_tokens.labels(type="input").inc(resp.usage.input_tokens)
            sky_mr_money_tokens.labels(type="output").inc(resp.usage.output_tokens)
            if cr := getattr(resp.usage, "cache_read_input_tokens", 0):
                sky_mr_money_tokens.labels(type="cache_read").inc(cr)
            if cc := getattr(resp.usage, "cache_creation_input_tokens", 0):
                sky_mr_money_tokens.labels(type="cache_creation").inc(cc)

        last_text = " ".join(
            block.text for block in resp.content if block.type == "text"
        )
        result_text = (result_text + last_text).strip()

        if proposals:
            return proposals[0]

        return ChatTextResponse(text=result_text or "No pude procesar eso. ¿Puedes reformularlo?")
