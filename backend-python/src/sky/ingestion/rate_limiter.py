"""
sky.ingestion.rate_limiter — Sliding window log rate limiter en Redis.

Cada source_identifier tiene una ventana propia. Cuando se consume el cupo,
acquire() devuelve AcquireResult(allowed=False) y el router salta al siguiente
provider acumulando el error en AllSourcesFailedError.

Por qué sliding window log y no token bucket clásico:
    - Granularidad real: rechaza al request N+1 dentro de la ventana,
      no al "siguiente segundo aproximado".
    - Limpieza barata: ZREMRANGEBYSCORE expira entradas viejas en O(log n).
    - Compatible con Redis Cluster (single key por source).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

from sky.core.config import settings
from sky.core.logging import get_logger

logger = get_logger("rate_limiter")


# Lua atómico:
#   1. Limpia entradas anteriores a (now - window).
#   2. Cuenta entradas vivas.
#   3. Si < max, agrega el request (score=now_ms, member=uuid) y devuelve {1, remaining}.
#   4. Si >= max, devuelve {0, retry_after_ms}.
# NOTAS:
#   - ARGV[4] = member único (UUID) para que requests del mismo ms no colisionen.
#   - max_req == 0 bloquea siempre (shortcut).
#   - Cuando la ZSET está vacía en el else (ej. max_req=0) retry_after_ms = window_ms.
_ACQUIRE_SCRIPT = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local max_req = tonumber(ARGV[3])
local member = ARGV[4]

if max_req <= 0 then
    return {0, window_ms}
end

local cutoff = now_ms - window_ms
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)

if count < max_req then
    redis.call('ZADD', key, now_ms, member)
    redis.call('PEXPIRE', key, window_ms)
    return {1, max_req - count - 1}
else
    local oldest = redis.call('ZRANGE', key, 0, 0)
    if #oldest == 0 then
        return {0, window_ms}
    end
    local oldest_score = tonumber(redis.call('ZSCORE', key, oldest[1]))
    local retry_ms = window_ms - (now_ms - oldest_score)
    if retry_ms < 1 then retry_ms = 1 end
    return {0, retry_ms}
end
"""


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    max_requests: int
    window_seconds: int

    @property
    def window_ms(self) -> int:
        return self.window_seconds * 1000


@dataclass(frozen=True, slots=True)
class AcquireResult:
    allowed: bool
    remaining: int        # cuántos requests quedan en la ventana
    retry_after_ms: int   # si allowed=False, en cuántos ms se libera espacio


class RateLimiter:
    """Sliding window log rate limiter atómico (Lua + sorted set)."""

    def __init__(
        self,
        redis: Redis,
        defaults: RateLimitConfig | None = None,
        overrides: dict[str, RateLimitConfig] | None = None,
    ) -> None:
        self._redis = redis
        self._defaults = defaults or RateLimitConfig(
            max_requests=settings.rate_limit_default_max,
            window_seconds=settings.rate_limit_default_window_sec,
        )
        self._overrides: dict[str, RateLimitConfig] = overrides or {}
        self._script: Any = redis.register_script(_ACQUIRE_SCRIPT)

    @classmethod
    def from_settings(cls, redis: Redis) -> RateLimiter:
        overrides = {
            sid: RateLimitConfig(max_requests=mx, window_seconds=win)
            for sid, (mx, win) in settings.rate_limit_overrides_map.items()
        }
        return cls(redis, overrides=overrides)

    def _config_for(self, source_id: str) -> RateLimitConfig:
        return self._overrides.get(source_id, self._defaults)

    async def acquire(self, source_id: str) -> AcquireResult:
        """Intenta consumir un slot para esta source. Atómico vía Lua."""
        cfg = self._config_for(source_id)
        now_ms = int(time.time() * 1000)
        member = str(uuid.uuid4())  # único para evitar colisiones en el mismo ms
        key = f"rl:{source_id}"
        result: list[int] = await self._script(
            keys=[key],
            args=[now_ms, cfg.window_ms, cfg.max_requests, member],
        )
        allowed = bool(result[0])
        if allowed:
            return AcquireResult(allowed=True, remaining=int(result[1]), retry_after_ms=0)
        return AcquireResult(allowed=False, remaining=0, retry_after_ms=int(result[1]))

    async def reset(self, source_id: str) -> None:
        """Limpia la ventana de un source (admin/debug)."""
        await self._redis.delete(f"rl:{source_id}")
