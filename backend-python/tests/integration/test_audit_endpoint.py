"""Integration tests: GET /api/audit/me."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sky.api.deps import require_user_id
from sky.api.main import app

_TEST_USER = "test-user-audit-1"

_AUDIT_ROW = (
    "sync",           # event_type
    "success",        # outcome
    "bank_account",   # resource_type
    "res-uuid-1",     # resource_id
    {"bank_id": "bchile"},  # detail
    datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC),  # occurred_at
)


def _make_engine_for_audit(rows: list, total: int | None = None) -> MagicMock:
    real_total = total if total is not None else len(rows)

    count_rs = MagicMock()
    count_rs.scalar.return_value = real_total

    data_rs = MagicMock()
    data_rs.fetchall.return_value = rows

    conn = AsyncMock()
    conn.execute = AsyncMock(side_effect=[count_rs, data_rs])
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect.return_value = ctx
    return engine


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[require_user_id] = lambda: _TEST_USER
    with (
        patch("sky.api.main.build_router", new_callable=AsyncMock) as mock_br,
        patch("arq.create_pool", new_callable=AsyncMock) as mock_pool,
    ):
        mock_br.return_value = (MagicMock(), AsyncMock())
        mock_pool.return_value = AsyncMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
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
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


async def test_get_audit_me_no_jwt_returns_401(unauth_client: AsyncClient) -> None:
    resp = await unauth_client.get("/api/audit/me")
    assert resp.status_code == 401


async def test_get_audit_me_empty_user_returns_empty_list(client: AsyncClient) -> None:
    with patch("sky.api.routers.audit.get_engine", return_value=_make_engine_for_audit([], 0)):
        resp = await client.get("/api/audit/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["events"] == []
    assert data["total"] == 0


async def test_get_audit_me_returns_events(client: AsyncClient) -> None:
    with patch(
        "sky.api.routers.audit.get_engine",
        return_value=_make_engine_for_audit([_AUDIT_ROW], 1),
    ):
        resp = await client.get("/api/audit/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["events"]) == 1
    ev = data["events"][0]
    assert ev["event_type"] == "sync"
    assert ev["outcome"] == "success"
    assert ev["resource_type"] == "bank_account"


async def test_get_audit_me_event_type_filter(client: AsyncClient) -> None:
    engine = _make_engine_for_audit([_AUDIT_ROW], 1)
    with patch("sky.api.routers.audit.get_engine", return_value=engine):
        resp = await client.get("/api/audit/me?event_type=sync")
    assert resp.status_code == 200
    # Verifica que se pasó el filtro al engine (2 llamadas a execute: count + data)
    conn = engine.connect.return_value.__aenter__.return_value
    assert conn.execute.call_count == 2
    count_call_sql = str(conn.execute.call_args_list[0][0][0])
    assert "event_type" in count_call_sql


async def test_get_audit_me_unknown_event_type_returns_empty(client: AsyncClient) -> None:
    """Filtro con event_type desconocido devuelve lista vacía sin tocar la DB."""
    engine = MagicMock()
    with patch("sky.api.routers.audit.get_engine", return_value=engine):
        resp = await client.get("/api/audit/me?event_type=unknown_xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["events"] == []
    assert data["total"] == 0
    engine.connect.assert_not_called()


async def test_get_audit_me_pagination_params(client: AsyncClient) -> None:
    engine = _make_engine_for_audit([], 0)
    with patch("sky.api.routers.audit.get_engine", return_value=engine):
        resp = await client.get("/api/audit/me?limit=10&offset=20")
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 10
    assert data["offset"] == 20
