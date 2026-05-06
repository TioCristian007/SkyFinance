"""Tests de sky.domain.mr_money — 3-level architecture."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sky.api.schemas.chat import ChatTextResponse, NavigationResponse, ProposeChallenge
from sky.domain.mr_money import MrMoney

_USER = "user-mm-1"
_CONTEXT = ("=== CONTEXTO FINANCIERO ===\nRESUMEN: ...", {"summary": MagicMock(), "goals": []})


def _make_text_response(text: str = "Todo bien con tus finanzas.") -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    resp.usage = MagicMock(
        input_tokens=100, output_tokens=50,
    )
    resp.usage.cache_read_input_tokens = 0
    resp.usage.cache_creation_input_tokens = 0
    return resp


def _make_tool_use_response(name: str, tool_id: str, tool_input: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.id = tool_id
    block.input = tool_input
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [block]
    resp.usage = MagicMock(
        input_tokens=120, output_tokens=60,
    )
    resp.usage.cache_read_input_tokens = 0
    resp.usage.cache_creation_input_tokens = 0
    return resp


# ── Detección LOCAL — sin llamadas a Anthropic ────────────────────────────────

@pytest.mark.asyncio
@patch("sky.domain.mr_money._get_client")
async def test_greeting_returns_local_no_anthropic(mock_get_client: MagicMock) -> None:
    result = await MrMoney().respond(_USER, "hola")

    assert isinstance(result, ChatTextResponse)
    assert "Mr. Money" in result.text or "Hola" in result.text
    mock_get_client.assert_not_called()


@pytest.mark.asyncio
@patch("sky.domain.mr_money._get_client")
async def test_greeting_buenos_dias(mock_get_client: MagicMock) -> None:
    result = await MrMoney().respond(_USER, "buenos días")

    assert isinstance(result, ChatTextResponse)
    mock_get_client.assert_not_called()


@pytest.mark.asyncio
@patch("sky.domain.mr_money._get_client")
async def test_nav_intent_metas(mock_get_client: MagicMock) -> None:
    result = await MrMoney().respond(_USER, "ver mis metas")

    assert isinstance(result, NavigationResponse)
    assert result.route == "/goals"
    mock_get_client.assert_not_called()


@pytest.mark.asyncio
@patch("sky.domain.mr_money._get_client")
async def test_nav_intent_movimientos(mock_get_client: MagicMock) -> None:
    result = await MrMoney().respond(_USER, "ver mis movimientos")

    assert isinstance(result, NavigationResponse)
    assert result.route == "/transactions"
    mock_get_client.assert_not_called()


@pytest.mark.asyncio
@patch("sky.domain.mr_money._get_client")
async def test_nav_intent_cuentas(mock_get_client: MagicMock) -> None:
    result = await MrMoney().respond(_USER, "ver mis cuentas")

    assert isinstance(result, NavigationResponse)
    assert result.route == "/accounts"
    mock_get_client.assert_not_called()


@pytest.mark.asyncio
@patch("sky.domain.challenges.get_challenges", new_callable=AsyncMock, return_value=[])
@patch("sky.domain.mr_money._get_client")
async def test_challenge_status_no_active(
    mock_get_client: MagicMock, mock_challenges: AsyncMock
) -> None:
    result = await MrMoney().respond(_USER, "cómo va mi desafío")

    assert isinstance(result, ChatTextResponse)
    assert "activos" in result.text.lower()
    mock_get_client.assert_not_called()


@pytest.mark.asyncio
@patch(
    "sky.domain.challenges.get_challenges",
    new_callable=AsyncMock,
    return_value=[{"title": "No Uber", "status": "active"}],
)
@patch("sky.domain.mr_money._get_client")
async def test_challenge_status_with_active(
    mock_get_client: MagicMock, mock_challenges: AsyncMock
) -> None:
    result = await MrMoney().respond(_USER, "cómo va mi desafío")

    assert isinstance(result, ChatTextResponse)
    assert "No Uber" in result.text
    mock_get_client.assert_not_called()


# ── Llamada a Anthropic ───────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("sky.domain.mr_money._build_financial_context", new_callable=AsyncMock, return_value=_CONTEXT)
@patch("sky.domain.mr_money._get_client")
async def test_financial_question_calls_anthropic(
    mock_get_client: MagicMock, mock_ctx: AsyncMock
) -> None:
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_make_text_response("Gastas $200.000 en comida."))
    mock_get_client.return_value = mock_client

    result = await MrMoney().respond(_USER, "¿cuánto gasto en comida este mes?")

    assert isinstance(result, ChatTextResponse)
    assert mock_client.messages.create.called


@pytest.mark.asyncio
@patch("sky.domain.mr_money._build_financial_context", new_callable=AsyncMock, return_value=_CONTEXT)
@patch("sky.domain.mr_money._get_client")
async def test_propose_challenge_no_db_write(
    mock_get_client: MagicMock, mock_ctx: AsyncMock
) -> None:
    mock_client = AsyncMock()

    tool_resp = _make_tool_use_response(
        name="propose_challenge",
        tool_id="tu-1",
        tool_input={
            "title": "No Uber 2 semanas",
            "description": "Evita Uber por 14 días.",
            "target_amount": 50_000,
            "duration_days": 14,
            "rationale": "Gastás mucho en transporte.",
        },
    )
    end_resp = _make_text_response("Te propongo este desafío 👆")
    mock_client.messages.create = AsyncMock(side_effect=[tool_resp, end_resp])
    mock_get_client.return_value = mock_client

    result = await MrMoney().respond(_USER, "tengo muchos gastos en Uber")

    assert isinstance(result, ProposeChallenge)
    assert result.title == "No Uber 2 semanas"
    assert result.duration_days == 14
    assert mock_client.messages.create.call_count == 2


@pytest.mark.asyncio
@patch("sky.domain.mr_money._build_financial_context", new_callable=AsyncMock, return_value=_CONTEXT)
@patch("sky.domain.mr_money._get_client")
async def test_compute_projection_tool_executes_domain(
    mock_get_client: MagicMock, mock_ctx: AsyncMock
) -> None:
    mock_client = AsyncMock()

    tool_resp = _make_tool_use_response(
        name="compute_projection",
        tool_id="tu-2",
        tool_input={"target_amount": 1_000_000, "monthly_savings": 200_000},
    )
    end_resp = _make_text_response("En 5 meses alcanzás tu meta.")
    mock_client.messages.create = AsyncMock(side_effect=[tool_resp, end_resp])
    mock_get_client.return_value = mock_client

    result = await MrMoney().respond(_USER, "¿cuándo puedo llegar a 1 millón?")

    assert isinstance(result, ChatTextResponse)
    assert mock_client.messages.create.call_count == 2

    second_call = mock_client.messages.create.call_args_list[1]
    messages_sent: list = second_call.kwargs.get("messages", [])
    tool_result_msgs = [
        m for m in messages_sent
        if m.get("role") == "user" and isinstance(m.get("content"), list)
    ]
    assert tool_result_msgs, "Second Anthropic call must include a tool_result user message"
    tool_result_content = tool_result_msgs[-1]["content"][0]
    assert tool_result_content["type"] == "tool_result"
    payload = json.loads(tool_result_content["content"])
    assert "feasible" in payload
    assert payload["months_to_goal"] == 5


@pytest.mark.asyncio
@patch("sky.domain.mr_money._build_financial_context", new_callable=AsyncMock, return_value=_CONTEXT)
@patch("sky.domain.mr_money._get_client")
async def test_anthropic_failure_returns_canned_response(
    mock_get_client: MagicMock, mock_ctx: AsyncMock
) -> None:
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("API timeout"))
    mock_get_client.return_value = mock_client

    result = await MrMoney().respond(_USER, "¿cuánto gasté en comida?")

    assert isinstance(result, ChatTextResponse)
    assert "problema" in result.text.lower() or "repetir" in result.text.lower()
