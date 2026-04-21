"""
sky.core.metrics — Instrumentación Prometheus.

Fase 10: agregar counters, histograms y gauges aquí.
Los routers y services los importan y los actualizan.
"""

# TODO (Fase 10): implementar métricas
# from prometheus_client import Counter, Histogram, Gauge
#
# sync_duration = Histogram(
#     "sky_sync_duration_seconds",
#     "Duración de sync bancario",
#     labelnames=["bank_id", "source_kind"],
# )
#
# sync_total = Counter(
#     "sky_sync_total",
#     "Total de syncs ejecutados",
#     labelnames=["bank_id", "status"],
# )
#
# queue_depth = Gauge(
#     "sky_queue_depth",
#     "Transacciones pendientes de categorización",
# )
