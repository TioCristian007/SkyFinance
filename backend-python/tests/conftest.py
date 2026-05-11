"""Pytest fixtures compartidas."""
import os

# ── Valores dummy para pydantic-settings — deben estar ANTES de importar sky ──
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key")
os.environ.setdefault("BANK_ENCRYPTION_KEY", "0" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
# TODO #8 fix: REDIS_URL dummy para que pydantic-settings no falle al importar
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

import fakeredis  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from sky.ingestion.circuit_breaker import CircuitBreakerConfig  # noqa: E402
from sky.ingestion.rate_limiter import RateLimitConfig, RateLimiter  # noqa: E402


@pytest.fixture(autouse=True)
def _disable_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fix TODO #8: deshabilita slowapi para tests (no requiere Redis real)."""
    try:
        from sky.api.middleware.rate_limit import limiter

        monkeypatch.setattr(limiter, "enabled", False)
    except Exception:
        pass  # Tests que no usan la API no necesitan esto


@pytest.fixture
def test_encryption_key() -> str:
    return "test_key_for_unit_tests_only_32chars!"


@pytest_asyncio.fixture
async def fake_redis() -> fakeredis.FakeAsyncRedis:
    client: fakeredis.FakeAsyncRedis = fakeredis.FakeAsyncRedis()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def rate_limiter(fake_redis: fakeredis.FakeAsyncRedis) -> RateLimiter:
    return RateLimiter(
        fake_redis,
        defaults=RateLimitConfig(max_requests=10, window_seconds=60),
    )


@pytest.fixture
def cb_config() -> CircuitBreakerConfig:
    return CircuitBreakerConfig(
        failure_threshold=3,
        failure_window_seconds=60,
        open_duration_seconds=2,        # corto para tests de timing
        half_open_success_threshold=2,
    )
