"""
Smoke test del IngestionRouter contra Redis real.
NO requiere DB ni Playwright. Usa FakeSources para validar wiring.

Uso:
    python scripts/smoke_router.py

Gates que verifica:
    1. Redis responde a PING.
    2. Failover: source A falla, B responde → resultado de B.
    3. Circuit breaker: 5 fallos consecutivos → circuit OPEN en Redis.
    4. Rate limit: 11º request con max=10 → AcquireResult(allowed=False).
"""

import asyncio
from datetime import date

from redis.asyncio import Redis

from sky.core.config import settings
from sky.ingestion.circuit_breaker import CircuitBreaker
from sky.ingestion.contracts import (
    AccountBalance,
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
from sky.ingestion.rate_limiter import RateLimiter, RateLimitConfig
from sky.ingestion.routing.router import IngestionRouter, RoutingRule


class _AlwaysFailSource(DataSource):
    @property
    def source_identifier(self) -> str:
        return "fake.always_fail"

    @property
    def source_kind(self) -> SourceKind:
        return SourceKind.AGGREGATOR

    @property
    def supported_banks(self) -> list[str]:
        return ["bchile"]

    def capabilities(self) -> IngestionCapabilities:
        return IngestionCapabilities()

    async def fetch(self, *args: object, **kwargs: object) -> IngestionResult:
        raise RecoverableIngestionError("simulated downstream failure")


class _AlwaysOkSource(DataSource):
    @property
    def source_identifier(self) -> str:
        return "fake.always_ok"

    @property
    def source_kind(self) -> SourceKind:
        return SourceKind.SCRAPER

    @property
    def supported_banks(self) -> list[str]:
        return ["bchile"]

    def capabilities(self) -> IngestionCapabilities:
        return IngestionCapabilities()

    async def fetch(self, bank_id: str, credentials: object, **kwargs: object) -> IngestionResult:
        mv = CanonicalMovement(
            external_id=build_external_id(bank_id, date.today(), -1000, "smoke test"),
            amount_clp=-1000,
            raw_description="smoke test",
            occurred_at=date.today(),
            movement_source=MovementSource.ACCOUNT,
            source_kind=SourceKind.SCRAPER,
        )
        return IngestionResult(
            balance=AccountBalance(balance_clp=100_000, as_of=__import__("datetime").datetime.now()),
            movements=[mv],
            source_kind=SourceKind.SCRAPER,
            source_identifier=self.source_identifier,
            elapsed_ms=10,
        )


async def main() -> None:
    redis: Redis = Redis.from_url(settings.redis_url)  # type: ignore[type-arg]

    # ── Gate 1: Redis vivo ────────────────────────────────────────────────
    await redis.ping()
    print(f"[ok] Redis vivo en {settings.redis_url}")

    creds = BankCredentials(rut="11111111-1", password="smoke")

    # ── Gate 2: Failover ─────────────────────────────────────────────────
    sources = {
        "fake.always_fail": _AlwaysFailSource(),
        "fake.always_ok": _AlwaysOkSource(),
    }
    rules = [RoutingRule(bank_id="bchile", source_chain=["fake.always_fail", "fake.always_ok"])]
    rl = RateLimiter(redis, defaults=RateLimitConfig(max_requests=10, window_seconds=60))
    router = IngestionRouter(sources=sources, redis=redis, rules=rules, rate_limiter=rl)

    result = await router.ingest("bchile", "user-smoke", creds)
    assert result.source_identifier == "fake.always_ok", (
        f"Failover falló: se esperaba fake.always_ok, got {result.source_identifier}"
    )
    print(f"[ok] Failover: always_fail skipped, always_ok respondió con {len(result.movements)} mv(s)")

    # ── Gate 3: Circuit breaker ───────────────────────────────────────────
    # Limpiar estado previo del circuit de always_fail
    cb = CircuitBreaker(redis, "fake.always_fail")
    await cb.reset()

    only_fail_rules = [RoutingRule(bank_id="bchile", source_chain=["fake.always_fail"])]
    fail_router = IngestionRouter(sources=sources, redis=redis, rules=only_fail_rules, rate_limiter=rl)

    for _ in range(5):
        try:
            await fail_router.ingest("bchile", "user-smoke", creds)
        except Exception:
            pass

    from sky.ingestion.circuit_breaker import CircuitState
    state = await cb.get_state()
    assert state == CircuitState.OPEN, f"Circuit breaker debería estar OPEN, got {state}"
    print(f"[ok] Circuit breaker OPEN tras 5 fallos consecutivos")

    # ── Gate 4: Rate limit ────────────────────────────────────────────────
    rl_tight = RateLimiter(redis, defaults=RateLimitConfig(max_requests=10, window_seconds=60))
    await rl_tight.reset("smoke.src")
    for _ in range(10):
        r = await rl_tight.acquire("smoke.src")
        assert r.allowed, "Los primeros 10 requests deben ser permitidos"
    r11 = await rl_tight.acquire("smoke.src")
    assert not r11.allowed, "El 11º request debe ser bloqueado (429)"
    assert r11.retry_after_ms > 0
    print(f"[ok] Rate limit: 10 OK, 11º bloqueado (retry_after={r11.retry_after_ms}ms)")

    await redis.aclose()
    print("[ok] Smoke completado — todos los gates pasaron")


if __name__ == "__main__":
    asyncio.run(main())
