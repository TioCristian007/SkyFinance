"""
sky.ingestion.circuit_breaker — Circuit breaker por source en Redis.

Estados: CLOSED (normal) → OPEN (rechazo) → HALF_OPEN (probando).
Parámetros: abrir tras 5 fallos en 60s, mantener abierto 120s,
cerrar tras 3 éxitos en half-open.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from redis.asyncio import Redis


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    failure_window_seconds: int = 60
    open_duration_seconds: int = 120
    half_open_success_threshold: int = 3


class CircuitBreaker:
    """Circuit breaker distribuido con estado en Redis."""

    def __init__(self, redis: Redis, source_id: str, config: CircuitBreakerConfig | None = None):
        self.redis = redis
        self.source_id = source_id
        self.config = config or CircuitBreakerConfig()
        self._prefix = f"cb:{source_id}"

    async def get_state(self) -> CircuitState:
        state = await self.redis.get(f"{self._prefix}:state")
        if state is None:
            return CircuitState.CLOSED
        return CircuitState(state.decode() if isinstance(state, bytes) else state)

    async def is_available(self) -> bool:
        """¿Se puede intentar esta fuente?"""
        state = await self.get_state()
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.OPEN:
            opened_at = await self.redis.get(f"{self._prefix}:opened_at")
            if opened_at:
                elapsed = time.time() - float(opened_at)
                if elapsed >= self.config.open_duration_seconds:
                    await self.redis.set(f"{self._prefix}:state", CircuitState.HALF_OPEN.value)
                    return True
            return False
        # HALF_OPEN — permitir intentos limitados
        return True

    async def record_success(self) -> None:
        state = await self.get_state()
        if state == CircuitState.HALF_OPEN:
            count = await self.redis.incr(f"{self._prefix}:ho_success")
            if count >= self.config.half_open_success_threshold:
                await self._close()
        elif state == CircuitState.CLOSED:
            # Limpiar contador de fallos si hubo éxito
            await self.redis.delete(f"{self._prefix}:failures")

    async def record_failure(self) -> None:
        state = await self.get_state()
        if state == CircuitState.HALF_OPEN:
            await self._open()
            return

        # CLOSED — contar fallos
        pipe = self.redis.pipeline()
        key = f"{self._prefix}:failures"
        pipe.incr(key)
        pipe.expire(key, self.config.failure_window_seconds)
        results = await pipe.execute()
        count = results[0]

        if count >= self.config.failure_threshold:
            await self._open()

    async def _open(self) -> None:
        pipe = self.redis.pipeline()
        pipe.set(f"{self._prefix}:state", CircuitState.OPEN.value)
        pipe.set(f"{self._prefix}:opened_at", str(time.time()))
        pipe.delete(f"{self._prefix}:ho_success")
        await pipe.execute()

    async def _close(self) -> None:
        pipe = self.redis.pipeline()
        pipe.set(f"{self._prefix}:state", CircuitState.CLOSED.value)
        pipe.delete(f"{self._prefix}:opened_at")
        pipe.delete(f"{self._prefix}:ho_success")
        pipe.delete(f"{self._prefix}:failures")
        await pipe.execute()

    async def reset(self) -> None:
        """Reset manual (para admin/debug)."""
        await self._close()
