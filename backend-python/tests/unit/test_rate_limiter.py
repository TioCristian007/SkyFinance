"""Tests del RateLimiter (sliding window log, Redis Lua)."""
import asyncio

import fakeredis
import pytest

from sky.ingestion.rate_limiter import AcquireResult, RateLimitConfig, RateLimiter


def make_limiter(
    redis: fakeredis.FakeAsyncRedis,
    max_requests: int = 10,
    window_seconds: int = 60,
    overrides: dict[str, RateLimitConfig] | None = None,
) -> RateLimiter:
    return RateLimiter(
        redis,
        defaults=RateLimitConfig(max_requests=max_requests, window_seconds=window_seconds),
        overrides=overrides,
    )


@pytest.mark.asyncio
async def test_acquire_allows_within_window(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    limiter = make_limiter(fake_redis, max_requests=10, window_seconds=60)
    results = [await limiter.acquire("src.a") for _ in range(10)]
    assert all(r.allowed for r in results)
    # remaining decrece de 9 a 0
    assert results[0].remaining == 9
    assert results[9].remaining == 0


@pytest.mark.asyncio
async def test_acquire_blocks_when_full(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    limiter = make_limiter(fake_redis, max_requests=10, window_seconds=60)
    for _ in range(10):
        await limiter.acquire("src.b")
    result = await limiter.acquire("src.b")
    assert not result.allowed
    assert result.remaining == 0
    assert result.retry_after_ms > 0


@pytest.mark.asyncio
async def test_acquire_releases_after_window(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    limiter = make_limiter(fake_redis, max_requests=3, window_seconds=1)
    for _ in range(3):
        await limiter.acquire("src.c")
    blocked = await limiter.acquire("src.c")
    assert not blocked.allowed

    await asyncio.sleep(1.1)

    after = await limiter.acquire("src.c")
    assert after.allowed


@pytest.mark.asyncio
async def test_overrides_per_source(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    limiter = make_limiter(
        fake_redis,
        max_requests=10,
        window_seconds=60,
        overrides={"scraper.bchile": RateLimitConfig(max_requests=2, window_seconds=60)},
    )
    # bchile: solo 2 permitidos
    r1 = await limiter.acquire("scraper.bchile")
    r2 = await limiter.acquire("scraper.bchile")
    r3 = await limiter.acquire("scraper.bchile")
    assert r1.allowed
    assert r2.allowed
    assert not r3.allowed

    # otra source: usa el default de 10
    for _ in range(10):
        r = await limiter.acquire("scraper.other")
        assert r.allowed
    blocked = await limiter.acquire("scraper.other")
    assert not blocked.allowed


@pytest.mark.asyncio
async def test_isolation_between_sources(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    limiter = make_limiter(fake_redis, max_requests=2, window_seconds=60)
    # agotar source A
    await limiter.acquire("src.a")
    await limiter.acquire("src.a")
    blocked = await limiter.acquire("src.a")
    assert not blocked.allowed

    # source B no debe verse afectada
    result_b = await limiter.acquire("src.b")
    assert result_b.allowed


@pytest.mark.asyncio
async def test_reset_clears_window(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    limiter = make_limiter(fake_redis, max_requests=3, window_seconds=60)
    for _ in range(3):
        await limiter.acquire("src.d")
    blocked = await limiter.acquire("src.d")
    assert not blocked.allowed

    await limiter.reset("src.d")

    after_reset = await limiter.acquire("src.d")
    assert after_reset.allowed


@pytest.mark.asyncio
async def test_atomicity_under_concurrency(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    limiter = make_limiter(fake_redis, max_requests=20, window_seconds=60)
    results: list[AcquireResult] = await asyncio.gather(
        *[limiter.acquire("src.concurrent") for _ in range(50)]
    )
    allowed_count = sum(1 for r in results if r.allowed)
    blocked_count = sum(1 for r in results if not r.allowed)
    assert allowed_count == 20
    assert blocked_count == 30
