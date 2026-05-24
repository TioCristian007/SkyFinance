"""Integration test: GET /api/banking/banks — catálogo expuesto por la API."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sky.api.main import app
from sky.ingestion.sources import SUPPORTED_BANKS


@pytest_asyncio.fixture
async def client():
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


async def test_list_banks_returns_supported_banks(client: AsyncClient) -> None:
    resp = await client.get("/api/banking/banks")
    assert resp.status_code == 200

    data = resp.json()
    assert "banks" in data
    banks = data["banks"]
    assert len(banks) == len(SUPPORTED_BANKS)


async def test_list_banks_shape(client: AsyncClient) -> None:
    resp = await client.get("/api/banking/banks")
    assert resp.status_code == 200

    for bank in resp.json()["banks"]:
        for field in ("id", "name", "icon", "status", "has_2fa", "account_type"):
            assert field in bank, (
                f"Campo '{field}' falta en la respuesta del banco {bank.get('id')}"
            )


async def test_list_banks_bchile_active(client: AsyncClient) -> None:
    resp = await client.get("/api/banking/banks")
    banks_by_id = {b["id"]: b for b in resp.json()["banks"]}

    assert "bchile" in banks_by_id
    assert banks_by_id["bchile"]["status"] == "active"
    assert banks_by_id["bchile"]["account_type"] == "Cta. Corriente"


async def test_list_banks_no_auth_required(client: AsyncClient) -> None:
    """GET /banks es público — no requiere JWT."""
    resp = await client.get("/api/banking/banks")
    assert resp.status_code == 200
