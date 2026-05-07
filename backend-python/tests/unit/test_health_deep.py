"""Tests unitarios de helpers y rutas de /api/health."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from sky.api.routers.health import (
    check_anthropic,
    check_db,
    check_redis,
    health,
    health_deep,
)


async def test_check_db_ok() -> None:
    """Engine que ejecuta SELECT 1 sin error → 'ok'."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=MagicMock())
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx

    with patch("sky.api.routers.health.get_engine", return_value=mock_engine):
        result = await check_db()

    assert result == "ok"


async def test_check_db_timeout() -> None:
    """Engine que no responde (TimeoutError) → check_db retorna 'down'."""
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = TimeoutError()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx

    with patch("sky.api.routers.health.get_engine", return_value=mock_engine):
        result = await check_db()

    assert result == "down"


async def test_check_redis_ok() -> None:
    """redis.ping() ok → 'ok'."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    result = await check_redis(mock_redis)
    assert result == "ok"


async def test_check_redis_failure() -> None:
    """redis.ping() lanza ConnectionError → 'down'."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(side_effect=ConnectionError("refused"))
    result = await check_redis(mock_redis)
    assert result == "down"


def test_check_anthropic_key_valid() -> None:
    """Key 'sk-ant-...' → 'ok'."""
    with patch("sky.api.routers.health.settings") as mock_settings:
        mock_settings.anthropic_api_key = "sk-ant-abc123"
        result = check_anthropic()
    assert result == "ok"


def test_check_anthropic_key_empty() -> None:
    """Key vacía → 'missing'."""
    with patch("sky.api.routers.health.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        result = check_anthropic()
    assert result == "missing"


def test_check_anthropic_key_wrong_format() -> None:
    """Key con prefijo incorrecto → 'missing'."""
    with patch("sky.api.routers.health.settings") as mock_settings:
        mock_settings.anthropic_api_key = "pk-abc123"
        result = check_anthropic()
    assert result == "missing"


async def test_health_simple_route() -> None:
    """GET /api/health → dict con status ok."""
    result = await health()
    assert result == {"status": "ok", "app": "sky-backend-python"}


async def test_health_deep_route_all_ok() -> None:
    """health_deep con db+redis+anthropic ok → status ok, http 200."""
    mock_request = MagicMock()
    with (
        patch("sky.api.routers.health.check_db", new=AsyncMock(return_value="ok")),
        patch("sky.api.routers.health.check_redis", new=AsyncMock(return_value="ok")),
        patch("sky.api.routers.health.check_anthropic", return_value="ok"),
    ):
        resp = await health_deep(mock_request)
    assert resp.status_code == 200
    assert resp.body  # tiene contenido JSON


async def test_health_deep_route_degraded() -> None:
    """health_deep con core ok pero anthropic missing → status degraded, http 200."""
    mock_request = MagicMock()
    with (
        patch("sky.api.routers.health.check_db", new=AsyncMock(return_value="ok")),
        patch("sky.api.routers.health.check_redis", new=AsyncMock(return_value="ok")),
        patch("sky.api.routers.health.check_anthropic", return_value="missing"),
    ):
        resp = await health_deep(mock_request)
    assert resp.status_code == 200
    import json
    data = json.loads(resp.body)
    assert data["status"] == "degraded"


async def test_health_deep_route_down() -> None:
    """health_deep con db down → status down, http 503."""
    mock_request = MagicMock()
    with (
        patch("sky.api.routers.health.check_db", new=AsyncMock(return_value="down")),
        patch("sky.api.routers.health.check_redis", new=AsyncMock(return_value="ok")),
        patch("sky.api.routers.health.check_anthropic", return_value="ok"),
    ):
        resp = await health_deep(mock_request)
    assert resp.status_code == 503
    import json
    data = json.loads(resp.body)
    assert data["status"] == "down"
