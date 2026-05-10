"""Tests del SecurityHeadersMiddleware (Fase 11)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.requests import Request
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from sky.api.middleware.rate_limit import on_rate_limit_exceeded
from sky.api.middleware.security_headers import SecurityHeadersMiddleware


def _make_app(production: bool = False) -> FastAPI:
    with patch("sky.api.middleware.security_headers.settings") as mock_settings:
        mock_settings.is_production = production
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def handler() -> dict[str, str]:
            return {"ok": "true"}

        # Force middleware instantiation inside the patch context
        return app, mock_settings


@pytest.fixture
def dev_app() -> FastAPI:
    app = FastAPI()
    with patch("sky.api.middleware.security_headers.settings") as mock_settings:
        mock_settings.is_production = False
        app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    async def handler() -> dict[str, str]:
        return {"ok": "true"}

    return app


@pytest.fixture
def prod_app() -> FastAPI:
    app = FastAPI()
    with patch("sky.api.middleware.security_headers.settings") as mock_settings:
        mock_settings.is_production = True
        app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    async def handler() -> dict[str, str]:
        return {"ok": "true"}

    return app


@pytest.fixture
def base_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    async def handler() -> dict[str, str]:
        return {"ok": "true"}

    return app


async def test_hsts(base_app: FastAPI) -> None:
    """HSTS header siempre presente."""
    async with AsyncClient(transport=ASGITransport(app=base_app), base_url="http://test") as c:
        resp = await c.get("/test")
    expected_hsts = "max-age=63072000; includeSubDomains; preload"
    assert resp.headers["Strict-Transport-Security"] == expected_hsts


async def test_x_content_type_options(base_app: FastAPI) -> None:
    """X-Content-Type-Options: nosniff siempre presente."""
    async with AsyncClient(transport=ASGITransport(app=base_app), base_url="http://test") as c:
        resp = await c.get("/test")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


async def test_x_frame_options(base_app: FastAPI) -> None:
    """X-Frame-Options: DENY siempre presente."""
    async with AsyncClient(transport=ASGITransport(app=base_app), base_url="http://test") as c:
        resp = await c.get("/test")
    assert resp.headers["X-Frame-Options"] == "DENY"


async def test_referrer_policy(base_app: FastAPI) -> None:
    """Referrer-Policy siempre presente."""
    async with AsyncClient(transport=ASGITransport(app=base_app), base_url="http://test") as c:
        resp = await c.get("/test")
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


async def test_permissions_policy(base_app: FastAPI) -> None:
    """Permissions-Policy siempre presente."""
    async with AsyncClient(transport=ASGITransport(app=base_app), base_url="http://test") as c:
        resp = await c.get("/test")
    assert "geolocation=()" in resp.headers["Permissions-Policy"]


async def test_csp_absent_in_dev() -> None:
    """CSP NO está presente en dev (no rompe Swagger)."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    async def h() -> dict[str, str]:
        return {}

    with patch("sky.api.middleware.security_headers.settings") as ms:
        ms.is_production = False
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/test")

    assert "Content-Security-Policy" not in resp.headers


async def test_csp_present_in_production() -> None:
    """CSP presente en producción con 'default-src self'."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    async def h() -> dict[str, str]:
        return {}

    with patch("sky.api.middleware.security_headers.settings") as ms:
        ms.is_production = True
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/test")

    assert resp.headers["Content-Security-Policy"] == "default-src 'self'"


async def test_headers_present_on_4xx(base_app: FastAPI) -> None:
    """Headers presentes en 404 (ruta inexistente)."""
    async with AsyncClient(transport=ASGITransport(app=base_app), base_url="http://test") as c:
        resp = await c.get("/no-existe")
    assert resp.status_code == 404
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


async def test_security_headers_on_rate_limited_response() -> None:
    """Security headers en respuesta 429 — verifica SecurityHeaders es más externo que SlowAPI."""
    test_limiter = Limiter(key_func=lambda request: "global-test-key")
    app = FastAPI()
    app.state.limiter = test_limiter
    app.add_exception_handler(RateLimitExceeded, on_rate_limit_exceeded)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/rate-test")
    @test_limiter.limit("1/minute")
    async def handler(request: Request) -> dict[str, str]:
        return {"ok": "true"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.get("/rate-test")
        r2 = await c.get("/rate-test")

    assert r1.status_code == 200
    assert "X-Frame-Options" in r1.headers

    assert r2.status_code == 429
    assert "X-Frame-Options" in r2.headers  # SecurityHeaders debe ser más externo que SlowAPI
