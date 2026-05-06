"""Integration tests: /api/chat — JWT guard, local vs Anthropic paths."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sky.api.deps import require_user_id
from sky.api.main import app

_TEST_USER = "test-user-chat-1"


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[require_user_id] = lambda: _TEST_USER

    with (
        patch("sky.api.main.build_router", new_callable=AsyncMock) as mock_br,
        patch("arq.create_pool", new_callable=AsyncMock) as mock_pool,
    ):
        mock_br.return_value = (MagicMock(), AsyncMock())
        mock_pool.return_value = AsyncMock()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c

    app.dependency_overrides = {}


@pytest_asyncio.fixture
async def unauth_client():
    with (
        patch("sky.api.main.build_router", new_callable=AsyncMock) as mock_br,
        patch("arq.create_pool", new_callable=AsyncMock) as mock_pool,
    ):
        mock_br.return_value = (MagicMock(), AsyncMock())
        mock_pool.return_value = AsyncMock()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c


# ── 401 without JWT ───────────────────────────────────────────────────────────

async def test_chat_no_jwt_returns_401(unauth_client: AsyncClient) -> None:
    resp = await unauth_client.post("/api/chat", json={"message": "hola"})
    assert resp.status_code == 401


# ── Local pattern: greeting → no Anthropic call ───────────────────────────────

async def test_chat_greeting_local_response(client: AsyncClient) -> None:
    with patch("sky.domain.mr_money._get_client") as mock_anthropic:
        resp = await client.post("/api/chat", json={"message": "hola"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "text"
    assert "Mr. Money" in data["text"] or "Hola" in data["text"]
    mock_anthropic.assert_not_called()


# ── Local pattern: navigation intent ─────────────────────────────────────────

async def test_chat_nav_intent(client: AsyncClient) -> None:
    with patch("sky.domain.mr_money._get_client") as mock_anthropic:
        resp = await client.post("/api/chat", json={"message": "ver mis desafíos"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "navigation"
    assert data["route"] == "/challenges"
    mock_anthropic.assert_not_called()


# ── Anthropic path: financial question ───────────────────────────────────────

async def test_chat_financial_question_calls_anthropic(client: AsyncClient) -> None:
    mock_client_instance = AsyncMock()
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Gastás $180.000 en comida este mes."
    mock_resp = MagicMock()
    mock_resp.stop_reason = "end_turn"
    mock_resp.content = [text_block]
    mock_resp.usage = MagicMock(input_tokens=200, output_tokens=80)
    mock_resp.usage.cache_read_input_tokens = 0
    mock_resp.usage.cache_creation_input_tokens = 0
    mock_client_instance.messages.create = AsyncMock(return_value=mock_resp)

    with (
        patch("sky.domain.mr_money._get_client", return_value=mock_client_instance),
        patch(
            "sky.domain.mr_money._build_financial_context",
            new_callable=AsyncMock,
            return_value=("=== CONTEXTO ===\nRESUMEN: ...", {"summary": MagicMock(), "goals": []}),
        ),
    ):
        resp = await client.post("/api/chat", json={"message": "¿cuánto gasté en comida?"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "text"
    assert mock_client_instance.messages.create.called


# ── Anthropic path: propose_challenge parsed correctly ────────────────────────

async def test_chat_propose_challenge_not_stored_in_db(client: AsyncClient) -> None:
    mock_client_instance = AsyncMock()

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "propose_challenge"
    tool_block.id = "tool-ch-1"
    tool_block.input = {
        "title": "No Uber 2 semanas",
        "description": "Evita Uber 14 días.",
        "target_amount": 60_000,
        "duration_days": 14,
        "rationale": "Gastás $60k en Uber este mes.",
    }
    first_resp = MagicMock()
    first_resp.stop_reason = "tool_use"
    first_resp.content = [tool_block]
    first_resp.usage = MagicMock(input_tokens=150, output_tokens=70)
    first_resp.usage.cache_read_input_tokens = 0
    first_resp.usage.cache_creation_input_tokens = 0

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Te propongo este desafío."
    end_resp = MagicMock()
    end_resp.stop_reason = "end_turn"
    end_resp.content = [text_block]
    end_resp.usage = MagicMock(input_tokens=100, output_tokens=40)
    end_resp.usage.cache_read_input_tokens = 0
    end_resp.usage.cache_creation_input_tokens = 0

    mock_client_instance.messages.create = AsyncMock(side_effect=[first_resp, end_resp])

    with (
        patch("sky.domain.mr_money._get_client", return_value=mock_client_instance),
        patch(
            "sky.domain.mr_money._build_financial_context",
            new_callable=AsyncMock,
            return_value=("=== CONTEXTO ===\nRESUMEN: ...", {"summary": MagicMock(), "goals": []}),
        ),
        patch("sky.domain.challenges.get_engine"),  # no DB write for challenges
    ):
        resp = await client.post("/api/chat", json={"message": "gasté mucho en Uber"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "propose_challenge"
    assert data["title"] == "No Uber 2 semanas"
    assert data["duration_days"] == 14
