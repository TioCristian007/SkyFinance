"""Pytest fixtures compartidas."""
import os

# ── Valores dummy para pydantic-settings — deben estar ANTES de importar sky ──
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key")
os.environ.setdefault("BANK_ENCRYPTION_KEY", "0" * 64)

import fakeredis  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from sky.ingestion.circuit_breaker import CircuitBreakerConfig  # noqa: E402
from sky.ingestion.rate_limiter import RateLimitConfig, RateLimiter  # noqa: E402


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
