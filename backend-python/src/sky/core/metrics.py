"""sky.core.metrics — Métricas Prometheus de Sky Finance."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# Duración de sync bancario por banco y tipo de fuente.
sky_sync_duration = Histogram(
    "sky_sync_duration_seconds",
    "Duración del sync bancario",
    ["bank_id", "source_kind"],
    buckets=[1, 5, 10, 30, 60, 120, 180, 300, 600],
)

# Conteo de syncs por banco y resultado.
sky_sync_total = Counter(
    "sky_sync_total",
    "Total de syncs bancarios",
    ["bank_id", "status"],  # status: success | error
)

# Backlog de transacciones pendientes de categorización.
sky_queue_depth = Gauge(
    "sky_queue_depth",
    "Transacciones con categorization_status='pending'",
)

# Estado del circuit breaker por fuente (0=CLOSED, 1=OPEN, 2=HALF_OPEN).
sky_circuit_breaker_state = Gauge(
    "sky_circuit_breaker_state",
    "Estado del circuit breaker por source",
    ["source_id"],
)

# Tokens Anthropic consumidos por Mr. Money.
sky_mr_money_tokens = Counter(
    "sky_mr_money_tokens_total",
    "Tokens Anthropic consumidos por Mr. Money",
    ["type"],  # values: input | output | cache_read | cache_creation
)

# Duración de requests HTTP por endpoint y status code.
sky_api_request_duration = Histogram(
    "sky_api_request_duration_seconds",
    "Duración de requests API",
    ["endpoint", "status"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
)
