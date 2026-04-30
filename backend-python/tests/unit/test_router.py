"""Tests del IngestionRouter (failover, circuit breaker, rate limit, rollout)."""
from __future__ import annotations

import hashlib
from datetime import date

import fakeredis
import pytest

from sky.ingestion.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from sky.ingestion.contracts import (
    AllSourcesFailedError,
    AuthenticationError,
    BankCredentials,
    CanonicalMovement,
    DataSource,
    IngestionCapabilities,
    IngestionResult,
    MovementSource,
    RecoverableIngestionError,
    SourceKind,
    build_external_id,
)
from sky.ingestion.rate_limiter import RateLimitConfig, RateLimiter
from sky.ingestion.routing.router import IngestionRouter, RoutingRule

# ── Helpers ──────────────────────────────────────────────────────────────────

CREDS = BankCredentials(rut="11111111-1", password="x")


def make_result(source_id: str) -> IngestionResult:
    mv = CanonicalMovement(
        external_id=build_external_id("bchile", date.today(), -1000, "test"),
        amount_clp=-1000,
        raw_description="test",
        occurred_at=date.today(),
        movement_source=MovementSource.ACCOUNT,
        source_kind=SourceKind.SCRAPER,
    )
    return IngestionResult(
        balance=None,
        movements=[mv],
        source_kind=SourceKind.SCRAPER,
        source_identifier=source_id,
        elapsed_ms=1,
    )


class FakeSource(DataSource):
    """Source configurable para tests: puede devolver result o lanzar excepción."""

    def __init__(
        self,
        source_id: str,
        banks: list[str],
        result: IngestionResult | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._source_id = source_id
        self._banks = banks
        self._result = result
        self._raises = raises
        self.call_count = 0

    @property
    def source_identifier(self) -> str:
        return self._source_id

    @property
    def source_kind(self) -> SourceKind:
        return SourceKind.SCRAPER

    @property
    def supported_banks(self) -> list[str]:
        return self._banks

    def capabilities(self) -> IngestionCapabilities:
        return IngestionCapabilities()

    async def fetch(self, bank_id: str, credentials: object, **kwargs: object) -> IngestionResult:
        self.call_count += 1
        if self._raises is not None:
            raise self._raises
        assert self._result is not None
        return self._result


def make_router(
    sources: dict[str, DataSource],
    rules: list[RoutingRule],
    redis: fakeredis.FakeAsyncRedis,
    rate_limiter: RateLimiter | None = None,
) -> IngestionRouter:
    return IngestionRouter(sources=sources, redis=redis, rules=rules, rate_limiter=rate_limiter)


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_source_success(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    src = FakeSource("scraper.bchile", ["bchile"], result=make_result("scraper.bchile"))
    router = make_router(
        {"scraper.bchile": src},
        [RoutingRule(bank_id="bchile", source_chain=["scraper.bchile"])],
        fake_redis,
    )
    result = await router.ingest("bchile", "user-1", CREDS)
    assert result.source_identifier == "scraper.bchile"
    assert src.call_count == 1


@pytest.mark.asyncio
async def test_failover_on_recoverable(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    src_a = FakeSource("src.a", ["bchile"], raises=RecoverableIngestionError("timeout"))
    src_b = FakeSource("src.b", ["bchile"], result=make_result("src.b"))
    router = make_router(
        {"src.a": src_a, "src.b": src_b},
        [RoutingRule(bank_id="bchile", source_chain=["src.a", "src.b"])],
        fake_redis,
    )
    result = await router.ingest("bchile", "user-1", CREDS)
    assert result.source_identifier == "src.b"
    assert src_a.call_count == 1
    assert src_b.call_count == 1


@pytest.mark.asyncio
async def test_no_failover_on_authentication_error(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    src_a = FakeSource("src.a", ["bchile"], raises=AuthenticationError("bad creds"))
    src_b = FakeSource("src.b", ["bchile"], result=make_result("src.b"))
    router = make_router(
        {"src.a": src_a, "src.b": src_b},
        [RoutingRule(bank_id="bchile", source_chain=["src.a", "src.b"])],
        fake_redis,
    )
    with pytest.raises(AuthenticationError):
        await router.ingest("bchile", "user-1", CREDS)
    # B nunca se llamó
    assert src_b.call_count == 0


@pytest.mark.asyncio
async def test_circuit_open_skips_source(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    src_a = FakeSource("src.a", ["bchile"], result=make_result("src.a"))
    src_b = FakeSource("src.b", ["bchile"], result=make_result("src.b"))

    # Abrir manualmente el circuit de src.a
    cb_config = CircuitBreakerConfig(failure_threshold=1, failure_window_seconds=60,
                                     open_duration_seconds=300, half_open_success_threshold=1)
    cb = CircuitBreaker(fake_redis, "src.a", cb_config)
    await cb.record_failure()  # 1 fallo → OPEN
    assert not await cb.is_available()

    router = make_router(
        {"src.a": src_a, "src.b": src_b},
        [RoutingRule(bank_id="bchile", source_chain=["src.a", "src.b"])],
        fake_redis,
    )
    result = await router.ingest("bchile", "user-1", CREDS)
    assert result.source_identifier == "src.b"
    # A se saltó (circuit abierto)
    assert src_a.call_count == 0
    assert src_b.call_count == 1


@pytest.mark.asyncio
async def test_rate_limited_skips_source(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    src_a = FakeSource("src.a", ["bchile"], result=make_result("src.a"))
    src_b = FakeSource("src.b", ["bchile"], result=make_result("src.b"))

    # Limiter que bloquea src.a desde el primer request
    rl = RateLimiter(
        fake_redis,
        defaults=RateLimitConfig(max_requests=10, window_seconds=60),
        overrides={"src.a": RateLimitConfig(max_requests=0, window_seconds=60)},
    )
    router = make_router(
        {"src.a": src_a, "src.b": src_b},
        [RoutingRule(bank_id="bchile", source_chain=["src.a", "src.b"])],
        fake_redis,
        rate_limiter=rl,
    )
    result = await router.ingest("bchile", "user-1", CREDS)
    assert result.source_identifier == "src.b"
    assert src_a.call_count == 0


@pytest.mark.asyncio
async def test_all_sources_fail_raises_all_sources_failed(
    fake_redis: fakeredis.FakeAsyncRedis,
) -> None:
    src_a = FakeSource("src.a", ["bchile"], raises=RecoverableIngestionError("a down"))
    src_b = FakeSource("src.b", ["bchile"], raises=RecoverableIngestionError("b down"))
    router = make_router(
        {"src.a": src_a, "src.b": src_b},
        [RoutingRule(bank_id="bchile", source_chain=["src.a", "src.b"])],
        fake_redis,
    )
    with pytest.raises(AllSourcesFailedError) as exc_info:
        await router.ingest("bchile", "user-1", CREDS)
    err = exc_info.value
    assert err.bank_id == "bchile"
    assert len(err.errors) == 2


@pytest.mark.asyncio
async def test_unknown_source_id_skipped(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    src_bchile = FakeSource("scraper.bchile", ["bchile"], result=make_result("scraper.bchile"))
    router = make_router(
        {"scraper.bchile": src_bchile},
        [RoutingRule(bank_id="bchile", source_chain=["ghost", "scraper.bchile"])],
        fake_redis,
    )
    result = await router.ingest("bchile", "user-1", CREDS)
    assert result.source_identifier == "scraper.bchile"
    assert src_bchile.call_count == 1


@pytest.mark.asyncio
async def test_rollout_excludes_user_outside_bucket(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    bank_id = "bchile"
    rollout_pct = 10

    # Encontrar un user_id determinísticamente fuera del bucket (bucket >= 10)
    outside_user: str | None = None
    for i in range(1000):
        uid = f"user-{i}"
        h = hashlib.sha256(f"{uid}:{bank_id}".encode()).hexdigest()
        if int(h[:8], 16) % 100 >= rollout_pct:
            outside_user = uid
            break
    assert outside_user is not None, "No se encontró usuario fuera del rollout"

    src_primary = FakeSource("src.primary", [bank_id], result=make_result("src.primary"))
    src_fallback = FakeSource("scraper.bchile", [bank_id], result=make_result("scraper.bchile"))
    router = make_router(
        {"src.primary": src_primary, "scraper.bchile": src_fallback},
        [RoutingRule(bank_id=bank_id, source_chain=["src.primary", "scraper.bchile"],
                     rollout_percentage=rollout_pct)],
        fake_redis,
    )
    result = await router.ingest(bank_id, outside_user, CREDS)
    # Usuario fuera del rollout → solo usa el fallback (último de la cadena)
    assert result.source_identifier == "scraper.bchile"
    assert src_primary.call_count == 0


@pytest.mark.asyncio
async def test_rollout_includes_user_inside_bucket(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    bank_id = "bchile"
    rollout_pct = 100  # 100% → todos dentro

    src_primary = FakeSource("src.primary", [bank_id], result=make_result("src.primary"))
    src_fallback = FakeSource("scraper.bchile", [bank_id], result=make_result("scraper.bchile"))
    router = make_router(
        {"src.primary": src_primary, "scraper.bchile": src_fallback},
        [RoutingRule(bank_id=bank_id, source_chain=["src.primary", "scraper.bchile"],
                     rollout_percentage=rollout_pct)],
        fake_redis,
    )
    result = await router.ingest(bank_id, "any-user", CREDS)
    # Con rollout=100, siempre usa la cadena completa → primary va primero
    assert result.source_identifier == "src.primary"
    assert src_primary.call_count == 1
    assert src_fallback.call_count == 0


@pytest.mark.asyncio
async def test_no_rule_falls_back_to_scraper_naming(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    # Banco sin regla explícita, pero con "scraper.<bank>" registrado
    src = FakeSource("scraper.newbank", ["newbank"], result=make_result("scraper.newbank"))
    router = make_router(
        {"scraper.newbank": src},
        [],  # sin reglas
        fake_redis,
    )
    result = await router.ingest("newbank", "user-1", CREDS)
    assert result.source_identifier == "scraper.newbank"


@pytest.mark.asyncio
async def test_no_rule_no_scraper_raises_value_error(fake_redis: fakeredis.FakeAsyncRedis) -> None:
    router = make_router(
        {},   # sin sources
        [],   # sin reglas
        fake_redis,
    )
    with pytest.raises(ValueError, match="No hay regla de routing"):
        await router.ingest("unknown", "user-1", CREDS)
