"""
Integration tests: POST /api/banking/sync/{id} — hard-stop B2 (sprint 2026-06-12).

Una cuenta en needs_reconnection no puede sincronizarse ni con el botón
"Actualizar": el endpoint responde 409 dirigiendo al usuario a reconectar.
Cada reintento con una clave rechazada acerca al bloqueo del banco (3er fallo).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sky.api.deps import require_user_id
from sky.api.main import app

_TEST_USER = "test-user-sync-block"


def _make_engine_with_status(row: dict[str, Any] | None) -> MagicMock:
    """Engine mock: el SELECT de status devuelve `row` (None = cuenta no existe)."""
    mock_mappings = MagicMock()
    mock_mappings.first.return_value = row
    mock_rs = MagicMock()
    mock_rs.mappings.return_value = mock_mappings

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx
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

    app.dependency_overrides.pop(require_user_id, None)


async def test_sync_needs_reconnection_devuelve_409(client: AsyncClient) -> None:
    engine = _make_engine_with_status({"status": "needs_reconnection"})
    with patch("sky.api.routers.banking.get_engine", return_value=engine):
        resp = await client.post("/api/banking/sync/acc-1")

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "Reconecta" in detail


async def test_sync_cuenta_inexistente_devuelve_404(client: AsyncClient) -> None:
    engine = _make_engine_with_status(None)
    with patch("sky.api.routers.banking.get_engine", return_value=engine):
        resp = await client.post("/api/banking/sync/acc-nope")

    assert resp.status_code == 404


async def test_sync_cuenta_activa_pasa_el_guard(client: AsyncClient) -> None:
    """Una cuenta activa pasa el guard de status y llega a encolar el job."""
    engine = _make_engine_with_status({"status": "active"})
    fake_job = MagicMock()
    fake_job.job_id = "job-123"
    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock(return_value=fake_job)
    app.state.arq_pool = fake_pool

    try:
        with patch("sky.api.routers.banking.get_engine", return_value=engine):
            resp = await client.post("/api/banking/sync/acc-1")

        assert resp.status_code == 200
        assert resp.json()["started"] is True
        fake_pool.enqueue_job.assert_awaited_once_with(
            "sync_bank_account_job", "acc-1", _TEST_USER
        )
    finally:
        app.state.arq_pool = None
