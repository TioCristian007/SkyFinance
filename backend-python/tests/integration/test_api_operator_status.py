"""
Integration tests: GET /api/internal/operator/sync-status (C2, sprint 2026-06-12).

Panel mínimo de operador: estado + último error real por cuenta sin scripts
ad-hoc. Auth por x-cron-secret; sin PII en la respuesta.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sky.api.main import app

_SECRET = "test-operator-secret"

_ACCOUNT_ROW = {
    "id": "acc-1", "bank_id": "bchile", "status": "needs_reconnection",
    "consecutive_errors": 2, "sync_count": 14,
    "last_sync_at": datetime(2026, 6, 12, 10, 0, tzinfo=UTC),
    "last_sync_error": "Tu clave cambió o el banco la rechazó.",
    "updated_at": datetime(2026, 6, 12, 10, 1, tzinfo=UTC),
}

_AUDIT_ROW = {
    "resource_id": "acc-1", "outcome": "failure",
    "detail": '{"failure_kind": "wrong_credentials", "bank_id": "bchile"}',
    "occurred_at": datetime(2026, 6, 12, 10, 1, tzinfo=UTC),
}


def _make_engine(accounts: list[dict[str, Any]], events: list[dict[str, Any]]) -> MagicMock:
    acc_map = MagicMock()
    acc_map.all.return_value = accounts
    acc_rs = MagicMock()
    acc_rs.mappings.return_value = acc_map

    ev_map = MagicMock()
    ev_map.all.return_value = events
    ev_rs = MagicMock()
    ev_rs.mappings.return_value = ev_map

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=[acc_rs, ev_rs])
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
    resp = await client.get("/api/internal/operator/sync-status")
    assert resp.status_code == 401


async def test_secret_incorrecto_devuelve_401(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/internal/operator/sync-status",
        headers={"x-cron-secret": "wrong"},
    )
    assert resp.status_code == 401


async def test_devuelve_estado_y_ultimo_evento(client: AsyncClient) -> None:
    engine = _make_engine([_ACCOUNT_ROW], [_AUDIT_ROW])
    with patch("sky.api.routers.internal.get_engine", return_value=engine):
        resp = await client.get(
            "/api/internal/operator/sync-status",
            headers={"x-cron-secret": _SECRET},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    # Resumen por status: triage multi-tester sin abrir cada fila
    assert data["by_status"] == {"needs_reconnection": 1}
    acc = data["accounts"][0]
    assert acc["status"] == "needs_reconnection"
    assert acc["last_sync_error"].startswith("Tu clave cambió")
    # El detail jsonb (str de asyncpg) se parsea: failure_kind visible
    assert acc["last_sync_event"]["outcome"] == "failure"
    assert acc["last_sync_event"]["detail"]["failure_kind"] == "wrong_credentials"
    # Sin PII: nunca user_id/user_hash en la respuesta del panel
    assert "user_id" not in acc
    assert "user_hash" not in acc


async def test_cuenta_sin_eventos_audit(client: AsyncClient) -> None:
    engine = _make_engine([_ACCOUNT_ROW], [])
    with patch("sky.api.routers.internal.get_engine", return_value=engine):
        resp = await client.get(
            "/api/internal/operator/sync-status",
            headers={"x-cron-secret": _SECRET},
        )

    assert resp.status_code == 200
    assert resp.json()["accounts"][0]["last_sync_event"] is None
