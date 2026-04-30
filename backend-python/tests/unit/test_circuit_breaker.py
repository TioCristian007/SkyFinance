"""Tests del CircuitBreaker (CLOSED/OPEN/HALF_OPEN, Redis)."""
import asyncio

import fakeredis
import pytest

from sky.ingestion.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState


def make_cb(
    redis: fakeredis.FakeAsyncRedis,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreaker:
    return CircuitBreaker(redis, "test.source", config)


@pytest.mark.asyncio
async def test_initial_state_closed(
    fake_redis: fakeredis.FakeAsyncRedis,
    cb_config: CircuitBreakerConfig,
) -> None:
    cb = make_cb(fake_redis, cb_config)
    assert await cb.get_state() == CircuitState.CLOSED
    assert await cb.is_available() is True


@pytest.mark.asyncio
async def test_opens_after_threshold(
    fake_redis: fakeredis.FakeAsyncRedis,
    cb_config: CircuitBreakerConfig,
) -> None:
    cb = make_cb(fake_redis, cb_config)  # threshold=3
    for _ in range(3):
        await cb.record_failure()
    assert await cb.get_state() == CircuitState.OPEN
    assert await cb.is_available() is False


@pytest.mark.asyncio
async def test_failures_expire_within_window(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    config = CircuitBreakerConfig(
        failure_threshold=3,
        failure_window_seconds=1,   # ventana de 1s
        open_duration_seconds=60,
        half_open_success_threshold=2,
    )
    cb = make_cb(fake_redis, config)
    # 2 fallos (< threshold) dentro de la ventana
    await cb.record_failure()
    await cb.record_failure()
    assert await cb.get_state() == CircuitState.CLOSED

    # esperar que expire la ventana TTL
    await asyncio.sleep(1.2)

    # 1 fallo más — la ventana expiró, el contador empieza de 0
    await cb.record_failure()
    # 1 < threshold=3, sigue cerrado
    assert await cb.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_reopens_after_open_duration(
    fake_redis: fakeredis.FakeAsyncRedis,
    cb_config: CircuitBreakerConfig,
) -> None:
    cb = make_cb(fake_redis, cb_config)  # open_duration=2s
    for _ in range(3):
        await cb.record_failure()
    assert await cb.get_state() == CircuitState.OPEN
    assert await cb.is_available() is False

    await asyncio.sleep(2.1)

    # is_available() detecta expiración y transiciona a HALF_OPEN
    assert await cb.is_available() is True
    assert await cb.get_state() == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_half_open_close_after_successes(
    fake_redis: fakeredis.FakeAsyncRedis,
    cb_config: CircuitBreakerConfig,
) -> None:
    cb = make_cb(fake_redis, cb_config)  # half_open_success_threshold=2
    # Forzar OPEN
    for _ in range(3):
        await cb.record_failure()
    await asyncio.sleep(2.1)
    await cb.is_available()  # transiciona a HALF_OPEN
    assert await cb.get_state() == CircuitState.HALF_OPEN

    # 2 éxitos → CLOSED
    await cb.record_success()
    await cb.record_success()
    assert await cb.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_half_open_reopen_on_failure(
    fake_redis: fakeredis.FakeAsyncRedis,
    cb_config: CircuitBreakerConfig,
) -> None:
    cb = make_cb(fake_redis, cb_config)
    # Forzar OPEN → esperar → HALF_OPEN
    for _ in range(3):
        await cb.record_failure()
    await asyncio.sleep(2.1)
    await cb.is_available()
    assert await cb.get_state() == CircuitState.HALF_OPEN

    # 1 fallo en HALF_OPEN → vuelve a OPEN
    await cb.record_failure()
    assert await cb.get_state() == CircuitState.OPEN


@pytest.mark.asyncio
async def test_reset_returns_to_closed(
    fake_redis: fakeredis.FakeAsyncRedis,
    cb_config: CircuitBreakerConfig,
) -> None:
    cb = make_cb(fake_redis, cb_config)
    for _ in range(3):
        await cb.record_failure()
    assert await cb.get_state() == CircuitState.OPEN

    await cb.reset()

    assert await cb.get_state() == CircuitState.CLOSED
    assert await cb.is_available() is True
