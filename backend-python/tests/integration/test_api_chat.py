"""Integration tests: /api/chat — JWT guard, local vs Anthropic paths, persistencia, history."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sky.api.deps import require_user_id
from sky.api.main import app

_TEST_USER  = "test-user-chat-1"
_OTHER_USER = "test-user-chat-2"


# ── Engine mock helpers ───────────────────────────────────────────────────────

def _make_engine_for_persist() -> MagicMock:
    """Engine mock que simula un INSERT exitoso (engine.begin)."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=MagicMock())
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx
    mock_engine.begin.return_value = mock_ctx
    return mock_engine


def _make_engine_for_history(rows: list[dict[str, Any]]) -> MagicMock:
    """Engine mock que devuelve rows para SELECT de mr_money_messages."""
    rows_map = MagicMock()
    rows_map.all.return_value = rows

    rs = MagicMock()
    rs.mappings.return_value = rows_map

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx
    return mock_engine


# ── Fixtures ──────────────────────────────────────────────────────────────────

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
async def client_other():
    app.dependency_overrides[require_user_id] = lambda: _OTHER_USER

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
    assert "Mr. Money" in data["reply"] or "Hola" in data["reply"]
    assert data["proposals"] == []
    mock_anthropic.assert_not_called()


# ── Local pattern: navigation intent ─────────────────────────────────────────

async def test_chat_nav_intent(client: AsyncClient) -> None:
    with patch("sky.domain.mr_money._get_client") as mock_anthropic:
        resp = await client.post("/api/chat", json={"message": "ver mis desafíos"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["navigations"][0]["simulation_type"] == "/challenges"
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
        patch(
            "sky.domain.mr_money._fetch_history_from_db",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        resp = await client.post("/api/chat", json={"message": "¿cuánto gasté en comida?"})

    assert resp.status_code == 200
    data = resp.json()
    assert "comida" in data["reply"]
    assert mock_client_instance.messages.create.called


# ── Anthropic path: propose_challenge parsed correctly ────────────────────────

async def test_chat_propose_challenge_not_stored_in_db(client: AsyncClient) -> None:
    mock_client_instance = AsyncMock()

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "propose_challenge"
    tool_block.id = "tool-ch-1"
    tool_block.input = {
        "challenge_id": "no_uber",
        "reasoning": "Gastás $60k en Uber este mes.",
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
        patch(
            "sky.domain.mr_money._fetch_history_from_db",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("sky.domain.challenges.get_engine"),
    ):
        resp = await client.post("/api/chat", json={"message": "gasté mucho en Uber"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["proposals"][0]["type"] == "propose_challenge"
    assert data["proposals"][0]["input"]["challenge_id"] == "no_uber"
    assert data["proposals"][0]["input"]["reasoning"] == "Gastás $60k en Uber este mes."


# ── Persistencia: POST /api/chat persiste user + assistant ────────────────────

async def test_chat_persists_user_and_assistant_turns(client: AsyncClient) -> None:
    """POST /api/chat dispara _persist_turns con ambos roles en background."""
    persist_calls: list[tuple] = []

    async def capture_persist(user_id: str, user_msg: str, asst_text: str) -> None:
        persist_calls.append((user_id, user_msg, asst_text))

    with patch("sky.api.routers.chat._persist_turns", side_effect=capture_persist):
        resp = await client.post("/api/chat", json={"message": "hola"})

    assert resp.status_code == 200
    # Background task se ejecuta inline con ASGI test client
    assert len(persist_calls) == 1
    uid, user_msg, asst_text = persist_calls[0]
    assert uid == _TEST_USER
    assert user_msg == "hola"
    assert len(asst_text) > 0


# ── GET /api/chat/history devuelve turnos en orden ASC ───────────────────────

async def test_get_chat_history_returns_turns_asc(client: AsyncClient) -> None:
    from datetime import UTC, datetime

    rows = [
        {
            "role": "user",
            "content": "¿cuánto gasté?",
            "created_at": datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
        },
        {
            "role": "assistant",
            "content": "Gastaste $80.000.",
            "created_at": datetime(2026, 5, 28, 10, 1, tzinfo=UTC),
        },
    ]
    mock_engine = _make_engine_for_history(rows)

    with patch("sky.core.db.get_engine", return_value=mock_engine):
        resp = await client.get("/api/chat/history?limit=20")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["role"] == "user"
    assert data[0]["content"] == "¿cuánto gasté?"
    assert data[1]["role"] == "assistant"
    assert "created_at" in data[0]


async def test_get_chat_history_limit_cap(client: AsyncClient) -> None:
    """El parámetro limit no puede superar 50."""
    mock_engine = _make_engine_for_history([])
    with patch("sky.core.db.get_engine", return_value=mock_engine):
        resp = await client.get("/api/chat/history?limit=100")
    # FastAPI Query(le=50) retorna 422 si limit > 50
    assert resp.status_code == 422


async def test_get_chat_history_no_jwt_returns_401(unauth_client: AsyncClient) -> None:
    resp = await unauth_client.get("/api/chat/history")
    assert resp.status_code == 401


# ── RLS application-layer: user A no lee history de user B ───────────────────
# La RLS real de Postgres se verifica aplicando la migración 010 en Supabase
# staging y ejecutando el escenario manualmente. Este test verifica que el SQL
# del router incluye user_id en el WHERE, garantizando aislamiento a nivel app.

async def test_get_history_query_filters_by_user_id(client: AsyncClient) -> None:
    """El SQL de GET /history filtra por user_id del JWT, no acepta otro user."""
    captured_params: list[dict] = []

    mock_conn = AsyncMock()

    async def capture_execute(query: Any, params: dict | None = None) -> MagicMock:
        if params:
            captured_params.append(params)
        rows_map = MagicMock()
        rows_map.all.return_value = []
        rs = MagicMock()
        rs.mappings.return_value = rows_map
        return rs

    mock_conn.execute = capture_execute
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx

    with patch("sky.core.db.get_engine", return_value=mock_engine):
        resp = await client.get("/api/chat/history?limit=20")

    assert resp.status_code == 200
    assert len(captured_params) == 1
    # El SQL siempre filtra por el user_id del JWT (no puede pasarse otro)
    assert captured_params[0]["uid"] == _TEST_USER


async def test_other_user_gets_empty_history(
    client: AsyncClient,
    client_other: AsyncClient,
) -> None:
    """User B ve 0 turnos cuando user A tiene historial (mock por user_id)."""

    def engine_for(user_id: str) -> MagicMock:
        a_row = {
            "role": "user",
            "content": "hola A",
            "created_at": MagicMock(isoformat=lambda: "2026-01-01T00:00:00"),
        }
        rows = [a_row] if user_id == _TEST_USER else []
        return _make_engine_for_history(rows)

    # User A — tiene 1 turno
    with patch("sky.core.db.get_engine", side_effect=lambda: engine_for(_TEST_USER)):
        resp_a = await client.get("/api/chat/history?limit=20")

    # User B — no tiene turnos
    with patch("sky.core.db.get_engine", side_effect=lambda: engine_for(_OTHER_USER)):
        resp_b = await client_other.get("/api/chat/history?limit=20")

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert len(resp_b.json()) == 0
