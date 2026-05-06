"""sky.domain.mr_money — Copiloto financiero Mr. Money (paridad aiService.js)."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import anthropic
from sqlalchemy import text

from sky.api.schemas.chat import ChatTextResponse, NavigationResponse, ProposeChallenge
from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.domain.finance import CATEGORY_LABELS, compute_summary, top_categories
from sky.domain.simulations import compute_projection

logger = get_logger("mr_money")

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
            "Propone activar un desafío de ahorro. "
            "NO lo activa directamente — el usuario debe confirmar. "
            "Úsala cuando detectas un gasto alto en una categoría o el usuario pide un desafío."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title":         {"type": "string",  "description": "Nombre corto del desafío."},
                "description":   {"type": "string",  "description": "Descripción del desafío en 1-2 frases."},
                "target_amount": {"type": "integer", "description": "Monto a ahorrar en CLP."},
                "duration_days": {"type": "integer", "description": "Duración en días."},
                "rationale":     {"type": "string",  "description": "Por qué este desafío es relevante ahora."},
            },
            "required": ["title", "description", "target_amount", "duration_days", "rationale"],
        },
        "cache_control": {"type": "ephemeral"},  # cache all tools up to this point
    },
]

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

async def _fetch_transactions(user_id: str, days: int = 30) -> list[dict[str, Any]]:
    since = date.today() - timedelta(days=days)
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
    from sky.domain.goals import get_goals

    txs, goals, challenges = await asyncio.gather(
        _fetch_transactions(user_id),
        get_goals(user_id),
        get_challenges(user_id),
    )

    summary = compute_summary(txs)
    cats = top_categories(summary.by_category, limit=5)
    active_chs = [c for c in challenges if c.get("status") == "active"]

    cat_text = "\n".join(
        f"  - {CATEGORY_LABELS.get(c['category'], c['category'])}: {_fmt_clp(c['amount'])}"
        for c in cats
    ) or "  sin datos"

    goals_text = "\n".join(
        f"  - id:\"{g['id']}\" \"{g['name']}\": {g.get('progress_pct', 0):.0f}%"
        for g in goals
    ) or "  sin metas"

    chs_text = "\n".join(
        f"  - \"{c['title']}\""
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

    return context_text, {"summary": summary, "goals": goals}


def _build_system_prompt(context_text: str) -> str:
    return f"""Eres Mr. Money, copiloto financiero de Sky.

{context_text}

HERRAMIENTAS (úsalas cuando corresponda):
READ → compute_projection
WRITE (requieren aprobación del usuario) → propose_challenge

CUÁNDO USARLAS:
- Usuario pregunta plazos/proyecciones → compute_projection
- Usuario tiene gasto alto en categoría o pide un desafío → propose_challenge relevante

PERSONALIDAD: Profesional, directo, cercano. Fórmula: [dato real] + [emoción mínima] + [dirección].
REGLAS: Español. Datos reales siempre. Máx 4 líneas. 1-2 emojis. Sin asesoría de inversión. Sin decisiones por el usuario."""


# ── Tool executor ─────────────────────────────────────────────────────────────

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


# ── MrMoney class ─────────────────────────────────────────────────────────────

class MrMoney:
    async def respond(
        self,
        user_id: str,
        message: str,
    ) -> ChatTextResponse | ProposeChallenge | NavigationResponse:
        local = await self._try_local(user_id, message)
        if local is not None:
            return local

        try:
            return await self._call_anthropic(user_id, message)
        except Exception as exc:
            logger.warning("mr_money_anthropic_failed", error=str(exc))
            return ChatTextResponse(
                text="Tuve un problema procesando tu consulta. ¿Podés repetir?"
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
            active = [c for c in challenges if c.get("status") == "active"]
            if not active:
                return ChatTextResponse(text="No tenés desafíos activos por el momento.")
            lines = [f"- {c['title']}" for c in active]
            return ChatTextResponse(text="Tus desafíos activos:\n" + "\n".join(lines))

        return None

    async def _call_anthropic(
        self,
        user_id: str,
        message: str,
    ) -> ChatTextResponse | ProposeChallenge | NavigationResponse:
        context_text, raw = await _build_financial_context(user_id)
        system_prompt = _build_system_prompt(context_text)

        messages: list[dict[str, Any]] = [{"role": "user", "content": message}]

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
            tools=MR_MONEY_TOOLS,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
        )

        logger.info(
            "mr_money_tokens",
            input=resp.usage.input_tokens,
            output=resp.usage.output_tokens,
            cache_read=getattr(resp.usage, "cache_read_input_tokens", 0),
            cache_creation=getattr(resp.usage, "cache_creation_input_tokens", 0),
        )

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
                    if block.name == "compute_projection":
                        tool_output = _execute_compute_projection(
                            cast(dict[str, Any], block.input) if isinstance(block.input, dict) else {}
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": tool_output,
                        })

                    elif block.name == "propose_challenge":
                        inp: dict[str, Any] = cast(dict[str, Any], block.input) if isinstance(block.input, dict) else {}
                        proposals.append(ProposeChallenge(
                            title=str(inp.get("title", "")),
                            description=str(inp.get("description", "")),
                            target_amount=int(inp.get("target_amount", 0)),
                            duration_days=int(inp.get("duration_days", 0)),
                            rationale=str(inp.get("rationale", "")),
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
                tools=MR_MONEY_TOOLS,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
            )
            logger.info(
                "mr_money_tokens",
                input=resp.usage.input_tokens,
                output=resp.usage.output_tokens,
                cache_read=getattr(resp.usage, "cache_read_input_tokens", 0),
                cache_creation=getattr(resp.usage, "cache_creation_input_tokens", 0),
            )

        last_text = " ".join(
            block.text for block in resp.content if block.type == "text"
        )
        result_text = (result_text + last_text).strip()

        if proposals:
            return proposals[0]

        return ChatTextResponse(text=result_text or "No pude procesar eso. ¿Podés reformular?")
