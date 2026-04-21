"""
sky.ingestion.rate_limiter — Token bucket por proveedor.

Evita exceder cuotas del banco o del agregador.
Cada source_identifier tiene su propio bucket.

TODO (Fase 5): implementar con Redis.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    max_requests: int = 10        # requests máximos en la ventana
    window_seconds: int = 60      # tamaño de la ventana


class RateLimiter:
    """Placeholder — implementar en Fase 5 con Redis."""

    async def acquire(self, source_id: str) -> bool:
        """Intenta adquirir un token. Retorna True si hay cuota."""
        # TODO: implementar con Redis INCR + EXPIRE
        return True

    async def release(self, source_id: str) -> None:
        """Libera un token (si el modelo lo requiere)."""
        pass
