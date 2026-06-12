"""
Integration tests: POST /api/internal/cron/sync-due — exclusiones del cron HTTP.

El cron HTTP está deprecated (reemplazado por el cron ARQ nativo) pero sigue
montado por compatibilidad. Mientras exista es un camino de encolado real y
debe respetar el hard-stop B2 (sprint 2026-06-12): una cuenta en
needs_reconnection jamás se encola desde aquí — cada reintento con la clave
rechazada acerca al bloqueo del banco. Tampoco las que esperan 2FA.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sky.api.main import app

_SECRET = "test-cron-secret"


def _make_engine(rows: list[tuple[Any, ...]]) -> MagicMock:
    """Engine mock: el SELECT de cuentas due devuelve `rows` via fetchall()."""
    mock_rs = MagicMock()
    mock_rs.fetchall.return_value = rows

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx
    return mock_engine


@pytest_asyncio.fixture
async def client(monkeypatch):
    from sky.api.routers import internal as internal_module

    monkeypatch.setattr(internal_module.settings, "cron_secret", _SECRET)

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


async def test_sin_secret_devuelve_401(client: AsyncClient) -> None:
    resp = await client.post("/api/internal/cron/sync-due")
    assert resp.status_code == 401


async def test_secret_incorrecto_devuelve_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/internal/cron/sync-due", headers={"x-cron-secret": "wrong"}
    )
    assert resp.status_code == 401


async def test_sql_excluye_needs_reconnection_y_waiting_2fa(client: AsyncClient) -> None:
    """B2: el SELECT de cuentas due excluye needs_reconnection (clave rechazada
    = cero reintentos automáticos), waiting_2fa (sync en curso esperando al
    usuario) y disconnected. Pin del guard mientras el endpoint exista."""
    engine = _make_engine([("acc-1", "user-1")])
    fake_job = MagicMock()
    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock(return_value=fake_job)
    app.state.arq_pool = fake_pool

    try:
        with patch("sky.api.routers.internal.get_engine", return_value=engine):
            resp = await client.post(
                "/api/internal/cron/sync-due", headers={"x-cron-secret": _SECRET}
            )

        assert resp.status_code == 200
        assert resp.json() == {"enqueued": 1}
        fake_pool.enqueue_job.assert_awaited_once_with(
            "sync_bank_account_job", "acc-1", "user-1"
        )

        conn = engine.connect.return_value.__aenter__.return_value
        sql = str(conn.execute.call_args[0][0])
        assert "needs_reconnection" in sql
        assert "waiting_2fa" in sql
        assert "disconnected" in sql
    finally:
        app.state.arq_pool = None
