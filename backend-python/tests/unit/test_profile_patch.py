"""Tests del endpoint PATCH /api/profile."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sky.api.deps import require_user_id
from sky.api.main import app

_TEST_USER = "test-user-profile-1"


def _make_update_engine() -> MagicMock:
    update_rs = MagicMock()
    update_rs.rowcount = 1
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=update_rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_ctx
    return mock_engine


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    app.dependency_overrides[require_user_id] = lambda: _TEST_USER
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_patch_profile_count_transfers_true(client: AsyncClient) -> None:
    engine = _make_update_engine()
    with patch("sky.api.routers.profile.get_engine", return_value=engine):
        resp = await client.patch("/api/profile", json={"count_transfers_as_income": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count_transfers_as_income"] is True
    engine.begin.assert_called_once()
    sql_call = str(engine.begin.return_value.__aenter__.return_value.execute.call_args[0][0])
    assert "count_transfers_as_income" in sql_call
    assert "profiles" in sql_call


async def test_patch_profile_count_transfers_false(client: AsyncClient) -> None:
    engine = _make_update_engine()
    with patch("sky.api.routers.profile.get_engine", return_value=engine):
        resp = await client.patch("/api/profile", json={"count_transfers_as_income": False})
    assert resp.status_code == 200
    assert resp.json()["count_transfers_as_income"] is False


async def test_patch_profile_requires_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.patch("/api/profile", json={"count_transfers_as_income": True})
    assert resp.status_code == 401


async def test_patch_profile_invalid_body(client: AsyncClient) -> None:
    resp = await client.patch("/api/profile", json={"count_transfers_as_income": "not_a_bool"})
    assert resp.status_code == 422


async def test_patch_profile_count_transfers_as_expense(client: AsyncClient) -> None:
    engine = _make_update_engine()
    with patch("sky.api.routers.profile.get_engine", return_value=engine):
        resp = await client.patch("/api/profile", json={"count_transfers_as_expense": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count_transfers_as_expense"] is False
    assert "count_transfers_as_income" not in data


async def test_patch_profile_both_flags(client: AsyncClient) -> None:
    engine = _make_update_engine()
    with patch("sky.api.routers.profile.get_engine", return_value=engine):
        resp = await client.patch(
            "/api/profile",
            json={"count_transfers_as_income": True, "count_transfers_as_expense": False},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count_transfers_as_income"] is True
    assert data["count_transfers_as_expense"] is False


async def test_patch_profile_income_only_does_not_touch_expense_key(client: AsyncClient) -> None:
    engine = _make_update_engine()
    with patch("sky.api.routers.profile.get_engine", return_value=engine):
        resp = await client.patch("/api/profile", json={"count_transfers_as_income": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count_transfers_as_income"] is True
    assert "count_transfers_as_expense" not in data
