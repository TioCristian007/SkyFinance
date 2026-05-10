"""Tests del rate limiter Redis-backed (Fase 11 — P2-3)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sky.api.middleware.rate_limit import _get_rate_limit_key, on_rate_limit_exceeded


def _make_request(user_id: str | None = None, ip: str = "127.0.0.1") -> MagicMock:
    req = MagicMock()
    req.state = MagicMock()
    req.state.user_id = user_id
    req.client = MagicMock()
    req.client.host = ip
    # slowapi's get_remote_address checks headers then client.host
    req.headers = {}
    return req


def test_key_with_user_id_on_state() -> None:
    """user_id verificado en state → key = 'user:{id}'."""
    req = _make_request(user_id="abc-123")
    assert _get_rate_limit_key(req) == "user:abc-123"


def test_key_without_user_id_fallback_to_ip() -> None:
    """user_id = None → fallback a IP del cliente."""
    req = _make_request(user_id=None, ip="1.2.3.4")
    key = _get_rate_limit_key(req)
    assert key == "ip:1.2.3.4"


def test_key_no_state_attribute() -> None:
    """request.state sin atributo user_id → fallback IP sin crash."""
    req = MagicMock()
    req.state = object()  # state sin user_id
    req.client = MagicMock()
    req.client.host = "5.6.7.8"
    req.headers = {}
    key = _get_rate_limit_key(req)
    assert key.startswith("ip:")


def test_on_rate_limit_exceeded_returns_429() -> None:
    """handler de RateLimitExceeded → JSONResponse 429."""
    from fastapi.responses import JSONResponse
    from slowapi.errors import RateLimitExceeded

    req = _make_request()
    exc = RateLimitExceeded(limit=MagicMock())

    resp = on_rate_limit_exceeded(req, exc)

    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 429


def test_limiter_uses_redis_storage() -> None:
    """Limiter configurado con Redis URI (no in-memory) → seguro para autoescala."""
    from sky.api.middleware.rate_limit import limiter

    storage_uri = getattr(limiter, "_storage_uri", None)
    assert storage_uri is not None, (
        "Limiter debe usar almacenamiento externo (Redis), no in-memory. "
        "Sin Redis-backed, el rate limit falla en multi-instancia."
    )
    assert "redis" in str(storage_uri).lower(), (
        f"storage_uri debe ser una URL de Redis, got: {storage_uri}"
    )


@pytest.mark.asyncio
async def test_key_uuid_user_id() -> None:
    """UUID completo como user_id → key correctamente formada."""
    req = _make_request(user_id="550e8400-e29b-41d4-a716-446655440000")
    assert _get_rate_limit_key(req) == "user:550e8400-e29b-41d4-a716-446655440000"
