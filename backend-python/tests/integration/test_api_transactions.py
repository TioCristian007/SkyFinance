"""Integration tests: /api/transactions — JWT guard, CRUD end-to-end."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sky.api.deps import require_user_id
from sky.api.main import app

_TEST_USER = "test-user-txn-1"

_ROW = {
    "id": "tx-1", "amount": -15_000, "category": "food",
    "description": "Jumbo", "raw_description": "JUMBO LAS CONDES",
    "date": "2026-05-01", "bank_account_id": "acc-1",
    "movement_source": "CUENTA", "categorization_status": "done",
}


def _make_engine(rows: list[dict[str, Any]], count: int | None = None) -> MagicMock:
    """Engine mock that handles COUNT + SELECT calls in list_transactions."""
    real_count = count if count is not None else len(rows)

    count_rs = MagicMock()
    count_rs.scalar.return_value = real_count

    rows_map = MagicMock()
    rows_map.all.return_value = rows
    rows_rs = MagicMock()
    rows_rs.mappings.return_value = rows_map
    rows_rs.rowcount = 1

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=[count_rs, rows_rs])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx
    mock_engine.begin.return_value = mock_ctx
    return mock_engine


def _make_update_engine(rowcount: int = 1) -> MagicMock:
    """Engine mock for UPDATE operations (single execute call)."""
    update_rs = MagicMock()
    update_rs.rowcount = rowcount
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=update_rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_ctx
    return mock_engine


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

async def test_get_transactions_no_jwt_returns_401(unauth_client: AsyncClient) -> None:
    resp = await unauth_client.get("/api/transactions")
    assert resp.status_code == 401


async def test_patch_transaction_no_jwt_returns_401(unauth_client: AsyncClient) -> None:
    resp = await unauth_client.patch("/api/transactions/tx-1", json={"category": "food"})
    assert resp.status_code == 401


async def test_delete_transaction_no_jwt_returns_401(unauth_client: AsyncClient) -> None:
    resp = await unauth_client.delete("/api/transactions/tx-1")
    assert resp.status_code == 401


# ── GET /api/transactions ─────────────────────────────────────────────────────

async def test_get_transactions_returns_list(client: AsyncClient) -> None:
    with patch("sky.api.routers.transactions.get_engine", return_value=_make_engine([_ROW])):
        resp = await client.get("/api/transactions")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["transactions"][0]["id"] == "tx-1"
    assert data["transactions"][0]["category"] == "food"


async def test_get_transactions_empty_list(client: AsyncClient) -> None:
    with patch("sky.api.routers.transactions.get_engine", return_value=_make_engine([], count=0)):
        resp = await client.get("/api/transactions")

    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["transactions"] == []


# ── PATCH /api/transactions/{id} ─────────────────────────────────────────────

async def test_patch_transaction_recategorize(client: AsyncClient) -> None:
    with patch("sky.api.routers.transactions.get_engine", return_value=_make_update_engine(1)):
        resp = await client.patch("/api/transactions/tx-1", json={"category": "transport"})

    assert resp.status_code == 200
    assert resp.json()["category"] == "transport"


async def test_patch_transaction_invalid_category_returns_422(client: AsyncClient) -> None:
    resp = await client.patch(
        "/api/transactions/tx-1",
        json={"category": "not_a_real_category"},
    )
    assert resp.status_code == 422


# ── DELETE /api/transactions/{id} ────────────────────────────────────────────

async def test_delete_transaction_soft_delete(client: AsyncClient) -> None:
    with patch("sky.api.routers.transactions.get_engine", return_value=_make_update_engine(1)):
        resp = await client.delete("/api/transactions/tx-1")

    assert resp.status_code == 204
