"""Tests del IdempotencyMiddleware (Fase 11)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _make_idempotency_app(redis_mock: MagicMock | None = None) -> FastAPI:
    from sky.api.middleware.idempotency import IdempotencyMiddleware

    app = FastAPI()
    if redis_mock is not None:
        app.state.redis = redis_mock
    app.add_middleware(IdempotencyMiddleware)

    @app.post("/api/banking/sync/abc")
    async def handler() -> dict[str, str]:
        return {"status": "queued"}

    @app.post("/api/not-idempotent")
    async def other() -> dict[str, str]:
        return {"ok": "true"}

    return app


async def test_new_request_processes_normally() -> None:
    """Sin key en Redis → call_next ejecuta → 200."""
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=[None, None])  # [cache check, inprogress check]
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    app = _make_idempotency_app(redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/banking/sync/abc",
            headers={"Idempotency-Key": "test-uuid-new"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "queued"}


async def test_repeat_request_returns_cached() -> None:
    """Key en Redis con response cacheada → devuelve cached, X-Idempotency-Replay: true."""
    cached_data = json.dumps({"status_code": 200, "content": {"status": "queued"}}).encode()
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=cached_data)
    app = _make_idempotency_app(redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/banking/sync/abc",
            headers={"Idempotency-Key": "test-uuid-cached"},
        )

    assert resp.status_code == 200
    assert resp.headers.get("X-Idempotency-Replay") == "true"
    assert resp.json() == {"status": "queued"}


async def test_in_progress_sentinel_returns_409() -> None:
    """Primera request en vuelo (sentinel en Redis) → 409 + Retry-After."""
    redis = AsyncMock()
    # Primera llamada: cache miss (None), segunda: in-progress (b"1")
    redis.get = AsyncMock(side_effect=[None, b"1"])
    app = _make_idempotency_app(redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/banking/sync/abc",
            headers={"Idempotency-Key": "test-uuid-inprogress"},
        )

    assert resp.status_code == 409
    assert resp.headers.get("Retry-After") == "5"
    assert "en progreso" in resp.json()["error"].lower()


async def test_no_idempotency_header_skips() -> None:
    """Sin header Idempotency-Key → call_next directamente, sin tocar Redis."""
    redis = AsyncMock()
    redis.get = AsyncMock()
    app = _make_idempotency_app(redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/banking/sync/abc")

    assert resp.status_code == 200
    redis.get.assert_not_called()


async def test_non_idempotent_route_skips() -> None:
    """Ruta no idempotente → call_next sin Redis, aunque haya header."""
    redis = AsyncMock()
    redis.get = AsyncMock()
    app = _make_idempotency_app(redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/not-idempotent",
            headers={"Idempotency-Key": "test-uuid"},
        )

    assert resp.status_code == 200
    redis.get.assert_not_called()
