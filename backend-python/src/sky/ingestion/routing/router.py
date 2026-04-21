"""
sky.ingestion.routing.router — Router de ingesta con failover.

Dado un bank_id y un user_id, recorre la cadena de providers
en orden hasta que uno funcione. Respeta circuit breakers y
rollout percentages.

Ejemplo de cadena para BCI:
    ["bci.direct", "fintoc", "scraper.bci"]
    1. Intenta API directa de BCI
    2. Si falla (o circuit abierto), intenta Fintoc
    3. Si falla, cae a scraper como último recurso
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from redis.asyncio import Redis

from sky.ingestion.circuit_breaker import CircuitBreaker
from sky.ingestion.contracts import (
    AllSourcesFailedError,
    AuthenticationError,
    BankCredentials,
    DataSource,
    IngestionResult,
    OAuthTokens,
    ProgressCallback,
    RecoverableIngestionError,
)
from sky.core.logging import get_logger

logger = get_logger("ingestion_router")


@dataclass
class RoutingRule:
    """Regla de enrutamiento para un banco."""
    bank_id: str
    source_chain: list[str]       # ordered list of source_identifiers
    rollout_percentage: int = 100  # 0-100
    user_cohort: str = "all"      # "all" | cohort name


class IngestionRouter:
    """
    Enruta syncs a la fuente correcta con failover automático.

    Uso:
        router = IngestionRouter(sources={...}, redis=redis, rules=[...])
        result = await router.ingest(bank_id, user_id, credentials)
    """

    def __init__(
        self,
        sources: dict[str, DataSource],
        redis: Redis,
        rules: list[RoutingRule],
    ):
        self._sources = sources
        self._redis = redis
        self._rules = {r.bank_id: r for r in rules}

    def _get_chain(self, bank_id: str, user_id: str) -> list[str]:
        """Obtiene la cadena de providers para este banco y usuario."""
        rule = self._rules.get(bank_id)
        if not rule:
            # Fallback: si no hay regla, buscar scraper genérico
            fallback = f"scraper.{bank_id}"
            if fallback in self._sources:
                return [fallback]
            raise ValueError(f"No hay regla de routing para {bank_id}")

        # Rollout check: hash determinístico de user_id + bank_id
        if rule.rollout_percentage < 100:
            h = hashlib.sha256(f"{user_id}:{bank_id}".encode()).hexdigest()
            bucket = int(h[:8], 16) % 100
            if bucket >= rule.rollout_percentage:
                # Fuera del rollout → usar solo el último (scraper fallback)
                return rule.source_chain[-1:]

        return rule.source_chain

    async def ingest(
        self,
        bank_id: str,
        user_id: str,
        credentials: BankCredentials | OAuthTokens,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> IngestionResult:
        """
        Intenta ingestar datos bancarios recorriendo la cadena de providers.

        Reglas de failover:
            - AuthenticationError → NO failover (la credencial es el problema)
            - RecoverableIngestionError → registrar fallo, intentar siguiente
            - Circuit abierto → saltar al siguiente sin intentar

        Raises:
            AuthenticationError: credenciales rechazadas
            AllSourcesFailedError: toda la cadena falló
        """
        chain = self._get_chain(bank_id, user_id)
        errors: list[tuple[str, Exception]] = []

        for source_id in chain:
            source = self._sources.get(source_id)
            if source is None:
                logger.warning("source_not_found", source_id=source_id, bank_id=bank_id)
                continue

            # Check circuit breaker
            cb = CircuitBreaker(self._redis, source_id)
            if not await cb.is_available():
                logger.info("circuit_open_skipping", source_id=source_id)
                continue

            try:
                logger.info("trying_source", source_id=source_id, bank_id=bank_id)
                result = await source.fetch(bank_id, credentials, on_progress=on_progress)
                await cb.record_success()
                logger.info(
                    "source_success",
                    source_id=source_id,
                    movements=len(result.movements),
                    elapsed_ms=result.elapsed_ms,
                )
                return result

            except AuthenticationError:
                # Auth fail → no hacer failover, todos fallarían igual
                await cb.record_failure()
                raise

            except RecoverableIngestionError as e:
                await cb.record_failure()
                errors.append((source_id, e))
                logger.warning(
                    "source_failed_trying_next",
                    source_id=source_id,
                    error=str(e),
                )
                continue

            except Exception as e:
                await cb.record_failure()
                errors.append((source_id, e))
                logger.error(
                    "source_unexpected_error",
                    source_id=source_id,
                    error=str(e),
                )
                continue

        raise AllSourcesFailedError(bank_id, errors)
