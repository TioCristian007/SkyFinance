"""
Integration tests: POST /api/banking/accounts — alta y RECONEXIÓN.

La reconexión es la salida del ciclo needs_reconnection (B1/B2, sprint
2026-06-12): cuando el usuario vuelve a ingresar su clave, el upsert debe
resetear status a 'active', consecutive_errors a 0 y limpiar last_sync_error.
Si ese reset se pierde, la cuenta queda en hard-stop CON la clave nueva —
el peor estado posible para un tester.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sky.api.deps import require_user_id
from sky.api.main import app

_TEST_USER = "test-user-connect"


def _make_engine_returning_id(account_id: str) -> MagicMock:
    """Engine mock: el upsert devuelve RETURNING id via mappings().first()."""
    mock_mappings = MagicMock()
    mock_mappings.first.return_value = {"id": account_id}
    mock_rs = MagicMock()
    mock_rs.mappings.return_value = mock_mappings

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)
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

    app.dependency_overrides.pop(require_user_id, None)


async def test_reconectar_resetea_el_ciclo_needs_reconnection(client: AsyncClient) -> None:
    """El upsert de conexión resetea status/errores: una cuenta que estaba en
    needs_reconnection vuelve a 'active' con contador limpio y sin error."""
    engine = _make_engine_returning_id("acc-new")
    fake_job = MagicMock()
    fake_job.job_id = "job-9"
    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock(return_value=fake_job)
    app.state.arq_pool = fake_pool

    try:
        with (
            patch("sky.api.routers.banking.get_engine", return_value=engine),
            patch("sky.api.routers.banking.log_event", new_callable=AsyncMock),
        ):
            resp = await client.post(
                "/api/banking/accounts",
                json={"bank_id": "bchile", "rut": "22141522-1", "password": "Abc_123$"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "acc-new"
        assert data["status"] == "active"

        conn = engine.begin.return_value.__aenter__.return_value
        call = conn.execute.call_args
        sql = " ".join(str(call[0][0]).split())  # colapsar whitespace del SQL
        assert "ON CONFLICT (user_id, bank_id) DO UPDATE" in sql
        assert "status = 'active'" in sql
        assert "consecutive_errors = 0" in sql
        assert "last_sync_error = NULL" in sql

        # Las credenciales viajan cifradas al upsert — jamás en texto plano.
        params: dict[str, Any] = call[0][1]
        assert params["enc_rut"] != "22141522-1"
        assert params["enc_pass"] != "Abc_123$"
        assert "Abc_123$" not in str(params)

        # La reconexión dispara el primer sync de inmediato.
        fake_pool.enqueue_job.assert_awaited_once_with(
            "sync_bank_account_job", "acc-new", _TEST_USER
        )
    finally:
        app.state.arq_pool = None


async def test_banco_no_soportado_devuelve_422(client: AsyncClient) -> None:
    engine = _make_engine_returning_id("acc-x")
    with patch("sky.api.routers.banking.get_engine", return_value=engine):
        resp = await client.post(
            "/api/banking/accounts",
            json={"bank_id": "santander", "rut": "22141522-1", "password": "clave123"},
        )

    assert resp.status_code == 422
    assert "no soportado" in resp.json()["detail"].lower()
