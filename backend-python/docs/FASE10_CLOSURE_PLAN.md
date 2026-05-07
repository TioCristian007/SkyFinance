# FASE 10 — Observabilidad: Plan de cierre

> Plan-first obligatorio. Sin plan aprobado no se escribe código.
> Template: `FASE9_CLOSURE_PLAN.md`.
> Fecha: 2026-05-06

---

## 1. Contexto

### Objetivo
Primera implementación de observabilidad en Sky (Node no tiene Prometheus ni Sentry).
Cuatro pilares:
1. **Prometheus** — 6 métricas instrumentadas en hot path.
2. **Sentry** — captura de excepciones con `before_send` que elimina PII.
3. **`/api/health/deep`** — endpoint de salud con timeouts para DB + Redis + Anthropic.
4. **TODO #7** — `core/db.py` usa `settings.database_url` en lugar de `os.getenv`.

### Paridad Node
Node no tiene ninguna de estas piezas. Esta es la primera implementación.
Doctrina aplicable: `prometheus_client` + `sentry-sdk` estándar de industria.

### Deuda que se cierra
- **P2-1** — Tests de observabilidad → tests nuevos en esta fase.
- **P2-2** — CI con métricas → `/metrics` endpoint disponible para Prometheus.
- **P2-3** — Rate limiting HTTP API: **diferido a Fase 11** con TODO explícito (ver §3.14).
  El rate limiting de scraper (Redis sliding window) ya cerró en Fase 5. ✓
- **P2-4** — Monitoring → Sentry + `/health/deep` cubren esto.
- **TODO #7** — `core/db.py` usa `os.getenv` directo; bloqueante DX local.

---

## 2. Archivos involucrados

### Nuevos (5)
```
src/sky/core/metrics.py                   ← 6 métricas Prometheus
src/sky/core/sentry_utils.py              ← init_sentry() + before_send hook
src/sky/api/middleware/tracing.py         ← RequestTimingMiddleware
tests/unit/test_sentry_utils.py           ← 13 casos before_send PII
tests/unit/test_health_deep.py            ← 7 casos check_db/redis/anthropic
```

### Modificados (10)
```
pyproject.toml                            ← agregar sentry-sdk[fastapi]>=2.0.0
src/sky/core/config.py                    ← database_url: str + sentry_dsn: str = ""
src/sky/core/db.py                        ← TODO #7: settings.database_url
src/sky/api/routers/health.py             ← /api/health/deep + helpers testables
src/sky/api/main.py                       ← /metrics endpoint + middleware + Sentry init + TODO P2-3
src/sky/worker/main.py                    ← Sentry init en startup
src/sky/worker/banking_sync.py            ← sky_sync_duration + sky_sync_total
src/sky/worker/jobs/categorize.py         ← sky_queue_depth
src/sky/ingestion/circuit_breaker.py      ← sky_circuit_breaker_state
src/sky/domain/mr_money.py               ← sky_mr_money_tokens_total
docs/MIGRATION_13_PHASES.md              ← Fase 10 ✅
```

---

## 3. Cambios detallados

### 3.1 `pyproject.toml`

```toml
"sentry-sdk[fastapi]>=2.0.0",    # extra fastapi incluye SentryAsgiMiddleware
```

### 3.2 `src/sky/core/config.py`

Dos settings nuevos:

```python
# ── Database (TODO #7) ────────────────────────────────────────────────────────
database_url: str   # fail-fast si falta. Format: postgresql+asyncpg://... o
                    # postgresql://... (db.py hace el replace automático)

# ── Observabilidad (Fase 10) ──────────────────────────────────────────────────
sentry_dsn: str = ""  # vacío = Sentry deshabilitado (dev silencioso)
```

`database_url` no tiene default → pydantic-settings falla en startup si falta en `.env`
(fail-fast doctrinal). Pydantic lee la var del `.env` vía `SettingsConfigDict`.

### 3.3 `src/sky/core/db.py` — TODO #7

Reemplazar `_get_database_url()`:

```python
# Antes:
import os
db_url = os.getenv("DATABASE_URL")
if db_url:
    return db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
raise RuntimeError(...)

# Después:
from sky.core.config import settings
db_url = settings.database_url
return db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
```

El `.replace` se mantiene por compat con el `DATABASE_URL` del backend Node
(que usa `postgresql://` sin el sufijo `+asyncpg`). Pydantic lee del `.env`
automáticamente — no hace falta `$env:DATABASE_URL` en cada terminal.

Eliminar el `import os` si no hay otros usos en el módulo.

**Test manual obligatorio (TODO #7):**
1. Abrir PowerShell fresco — sin ejecutar `$env:DATABASE_URL = "..."`.
2. `cd backend-python && .venv\Scripts\activate`
3. `python -c "from sky.core.db import get_engine; print('OK')"` → debe imprimir `OK`.
   (Antes de Fase 10: `os.getenv` no lee `.env` → raise RuntimeError o devuelve None.
   Post-fix: pydantic-settings lee `.env` automáticamente → `settings.database_url` disponible.)
4. Confirmar que `.env` tiene `DATABASE_URL=postgresql://...` (formato Node, sin `+asyncpg`).
   El `db.py` hace el replace automáticamente.

### 3.4 `src/sky/core/metrics.py` (NUEVO)

6 métricas Prometheus, definidas al nivel de módulo (singleton por proceso).

```python
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
    ["type"],  # type: input | output | cache_read | cache_creation
)

# Duración de requests HTTP por endpoint y status code.
sky_api_request_duration = Histogram(
    "sky_api_request_duration_seconds",
    "Duración de requests API",
    ["endpoint", "status"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
)
```

**PROHIBIDO en labels**: `user_id`, `bank_account_id`, montos exactos, RUT.
Solo `bank_id` (identificador de banco, no de cuenta), `source_kind`, `source_id`.

### 3.5 `src/sky/core/sentry_utils.py` (NUEVO) ← pieza más crítica

**Diseño del `before_send` hook — pipeline de dos pasos:**

**Paso 1 (`_scrub`)**: walk recursivo sobre el evento completo.
- Claves en `_SCRUB_KEYS` (case-insensitive via `k.lower()`) → valor reemplazado por
  `[REDACTED]`, sin importar en qué parte del evento aparezcan:
  `event['exception']`, `event['breadcrumbs']`, `event['request']['data']`,
  `event['request']['headers']`, y cualquier estructura arbitraria de Sentry.
- String values que matcheen `_TOKEN_RE` o `_RUT_CL_RE` → `[REDACTED]`.
- Depth cap en 10 → `[TRUNCATED]` (previene recursión infinita).

**Paso 2 (`_event_contains_sensitive`)**: serializa el evento scrubbed completo a JSON
y aplica `_TOKEN_RE` + `_RUT_CL_RE` sobre el string resultante. Captura PII que
sobrevivió el paso 1 (ej: token Anthropic como clave de dict, datos truncados por
depth cap, tipos no-string con repr sensible). Si detecta pattern → `before_send`
retorna `None` (drop del evento).

**Fail-safe**: si cualquier paso lanza excepción → `return None`.
Es preferible perder un evento que enviar PII sin sanitizar.

```python
"""sky.core.sentry_utils — Init de Sentry y filtrado de PII."""
from __future__ import annotations

import json
import re
from typing import Any

import sentry_sdk

from sky.core.config import settings
from sky.core.logging import get_logger

logger = get_logger("sentry")

# ── Credenciales a eliminar por nombre de clave (case-insensitive)
_SCRUB_KEYS = frozenset({
    # Credenciales bancarias
    "encrypted_rut",    # credencial AES-256-GCM — nunca debe aparecer en errores
    "encrypted_pass",   # ídem
    "password",         # contraseña en texto plano
    "rut",              # identificador nacional chileno (PII alta sensibilidad)
    "clave",            # sinónimo de contraseña en contexto bancario chileno
    "credential",       # genérico
    "credentials",      # ídem plural
    # HTTP headers sensibles (HTTP headers son case-insensitive → comparar con k.lower())
    "authorization",    # Bearer token / Basic auth
    "cookie",           # Session cookies
    "x-cron-secret",    # Secreto del cron interno de Sky
})

# ── Patrones en string values a eliminar
_TOKEN_RE = re.compile(
    r"\bsk-(?:ant-)?[A-Za-z0-9\-_]{10,}\b"
    # Cubre: sk-ant-api03-... (Anthropic), sk-proj-... (otros)
    # Umbral mínimo 10 chars para evitar falsos positivos en hashes cortos
)
_RUT_CL_RE = re.compile(
    r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[\dkK]\b"
    # Cubre: 12.345.678-9 · 12345678-9 · 12345678K · 9.876.543-k
)


def _scrub(obj: Any, depth: int = 0) -> Any:
    """
    Recursivamente elimina PII de un objeto arbitrario.
    depth cap en 10 para evitar recursión infinita en estructuras circulares.
    Comparación de claves es case-insensitive (HTTP headers son case-insensitive).
    """
    if depth > 10:
        return "[TRUNCATED]"
    if isinstance(obj, str):
        if _TOKEN_RE.search(obj) or _RUT_CL_RE.search(obj):
            return "[REDACTED]"
        return obj
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]" if k.lower() in _SCRUB_KEYS else _scrub(v, depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_scrub(item, depth + 1) for item in obj]
    return obj


def _event_contains_sensitive(event: Any) -> bool:
    """
    Post-scrub check: serializa el evento a JSON y busca patrones sensibles.
    Captura PII que sobrevivió _scrub (ej: token como clave de dict,
    datos truncados por depth cap, tipos no-string con repr sensible).
    Si no se puede serializar, asume sensible y descarta.
    """
    try:
        text = json.dumps(event, default=str)
        return bool(_TOKEN_RE.search(text) or _RUT_CL_RE.search(text))
    except Exception:
        return True  # No se pudo verificar → asumir sensible → descartar


def before_send(
    event: dict[str, Any], hint: dict[str, Any]
) -> dict[str, Any] | None:
    """
    Sentry before_send: pipeline de dos pasos para eliminar PII antes de enviar.

    Paso 1 — _scrub (walk recursivo):
      • Claves en _SCRUB_KEYS (case-insensitive) → [REDACTED] en cualquier parte
        del evento: exception.stacktrace.frames[].vars, breadcrumbs[].data,
        request.data, request.headers, y cualquier estructura arbitraria.
      • String values con token (sk-ant-..) o RUT chileno → [REDACTED].
      • Depth > 10 → [TRUNCATED].

    Paso 2 — _event_contains_sensitive (post-scrub check):
      • Serializa el evento scrubbed a JSON y aplica los regexes.
      • Si detecta pattern → return None (drop). Captura PII que sobrevivió
        el paso 1 (ej: token Anthropic como clave de dict, no como valor).

    Fail-safe: cualquier excepción en cualquier paso → return None.
    Es preferible perder el evento que enviar datos de usuario sin sanitizar.
    """
    try:
        scrubbed = _scrub(event)
        if _event_contains_sensitive(scrubbed):
            logger.warning("sentry_post_scrub_sensitive_dropping_event")
            return None
        return scrubbed  # type: ignore[return-value]
    except Exception:
        logger.warning("sentry_scrub_failed_dropping_event")
        return None


def init_sentry() -> None:
    """
    Inicializa Sentry SDK. No-op si SENTRY_DSN está vacío (dev mode).
    Llamar desde lifespan de API y startup del worker.
    """
    if not settings.sentry_dsn:
        logger.info("sentry_disabled", reason="SENTRY_DSN not configured")
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.1 if settings.is_production else 1.0,
        before_send=before_send,
        environment="production" if settings.is_production else "development",
    )
    logger.info("sentry_initialized", env=settings.node_env)
```

**Invariantes garantizados por el diseño:**
- Clave en `_SCRUB_KEYS` → siempre `[REDACTED]` (case-insensitive), sin importar el valor.
- String con token o RUT → siempre `[REDACTED]`, sin importar la clave.
- HTTP headers (`Authorization`, `Cookie`, `X-Cron-Secret`) scrubbed por key name.
- Depth cap en 10 previene recursión infinita.
- Post-scrub check como red de seguridad: elimina PII en claves de dict u otras formas.
- `except Exception → return None` en cada paso garantiza no enviar sin sanitizar.
- El hook es una función pura (sin side effects de Sentry) — testeable sin SDK.

### 3.6 `src/sky/api/middleware/tracing.py` (NUEVO)

```python
"""sky.api.middleware.tracing — Middleware de métricas por request."""
import time
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from sky.core.metrics import sky_api_request_duration


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Registra sky_api_request_duration_seconds por endpoint y status."""

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed = time.perf_counter() - start

        # Usar el path pattern de la ruta (no la URL real) para evitar alta cardinalidad.
        # Ej: "/api/banking/sync/{id}" en vez de "/api/banking/sync/abc-123".
        route = request.scope.get("route")
        endpoint = route.path if route and hasattr(route, "path") else request.url.path

        sky_api_request_duration.labels(
            endpoint=endpoint,
            status=str(response.status_code),
        ).observe(elapsed)

        return response
```

`route.path` → patrón de ruta FastAPI (evita alta cardinalidad de UUIDs en labels).
`/metrics` y `/api/health*` también se instrumentan — overhead es < 0.1ms.

### 3.7 `src/sky/api/routers/health.py` (MODIFICAR)

Agregar `/api/health/deep` con helpers extraídos y testables:

```python
# helpers testables sin HTTP

async def check_db() -> str:
    """SELECT 1 con timeout 2s. Retorna 'ok' | 'down'."""
    try:
        async with asyncio.timeout(2.0):
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "down"


async def check_redis(redis: Any) -> str:
    """PING con timeout 1s. Retorna 'ok' | 'down'."""
    try:
        async with asyncio.timeout(1.0):
            await redis.ping()
        return "ok"
    except Exception:
        return "down"


def check_anthropic() -> str:
    """Verifica key format. NO llama a la API. Retorna 'ok' | 'missing'."""
    key = settings.anthropic_api_key
    return "ok" if key and key.startswith("sk-ant-") else "missing"


@router.get("/api/health/deep")
async def health_deep(request: Request) -> JSONResponse:
    db     = await check_db()
    redis  = await check_redis(request.app.state.redis)
    anth   = check_anthropic()

    is_core_ok  = db == "ok" and redis == "ok"
    status      = "ok" if (is_core_ok and anth == "ok") \
                  else ("degraded" if is_core_ok else "down")
    http_status = 200 if is_core_ok else 503

    return JSONResponse(
        status_code=http_status,
        content={"status": status, "db": db, "redis": redis, "anthropic": anth},
    )
```

**Lógica de status:**
| db | redis | anthropic | status | HTTP |
|---|---|---|---|---|
| ok | ok | ok | ok | 200 |
| ok | ok | missing | degraded | 200 |
| down | * | * | down | 503 |
| * | down | * | down | 503 |

Core (DB + Redis) down → 503. Anthropic missing es degraded (Mr. Money no funciona
pero sync bancario sí).

### 3.8 `src/sky/api/main.py` (MODIFICAR)

Tres cambios:

```python
# a) Agregar /metrics endpoint (sin JWT — Prometheus lo scrapea directamente)
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response as StarletteResponse

@app.get("/metrics", include_in_schema=False)
async def metrics() -> StarletteResponse:
    return StarletteResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

# b) Agregar middleware de tracing (ANTES de CORSMiddleware para medir todo)
from sky.api.middleware.tracing import RequestTimingMiddleware
app.add_middleware(RequestTimingMiddleware)

# c) Init Sentry al startup
from sky.core.sentry_utils import init_sentry
# En lifespan, justo antes del yield:
init_sentry()

# d) TODO P2-3 (dejar como comentario en el archivo)
# TODO(Fase11): slowapi — rate limiting HTTP público (P2-3).
# Ver backend-python/docs/MIGRATION_13_PHASES.md §Fase11.
```

**Orden de middlewares:** Sentry > RequestTiming > CORS. Starlette aplica en orden inverso
de `add_middleware`, así que hay que agregar CORS al final (o sea, primero en código).

### 3.9 `src/sky/worker/main.py` (MODIFICAR)

En `startup()`, antes de `logger.info("worker_starting")`:

```python
from sky.core.sentry_utils import init_sentry
init_sentry()
```

### 3.10 `src/sky/worker/banking_sync.py` (MODIFICAR)

Instrumentar `sky_sync_duration` y `sky_sync_total` en `sync_bank_account`:

```python
from sky.core.metrics import sky_sync_duration, sky_sync_total

# Al final del sync exitoso:
elapsed_s = elapsed_ms / 1000
sky_sync_duration.labels(bank_id=bank_id, source_kind=result.source_kind.value).observe(elapsed_s)
sky_sync_total.labels(bank_id=bank_id, status="success").inc()

# En except blocks (donde bank_id está disponible):
except BankAuthError:
    await _mark_error(bank_account_id, "Credenciales rechazadas por el banco")
    sky_sync_total.labels(bank_id=bank_id, status="error").inc()
    raise
except AllSourcesFailedError as exc:
    await _mark_error(bank_account_id, _sanitize_error(str(exc)))
    sky_sync_total.labels(bank_id=bank_id, status="error").inc()
    raise
```

`_mark_error` no se modifica. La métrica se registra en el `except` block donde
`bank_id` ya está disponible (Opción B del plan original).

### 3.11 `src/sky/worker/jobs/categorize.py` (MODIFICAR)

Actualizar `sky_queue_depth` al inicio del job (backlog actual):

```python
from sky.core.metrics import sky_queue_depth

async def categorize_pending_job(ctx):
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(text("""
            SELECT id, raw_description, amount
              FROM public.transactions
             WHERE categorization_status = 'pending'
             ORDER BY created_at ASC
             LIMIT :batch
        """), {"batch": settings.categorize_batch_size})
        rows = rs.mappings().all()

    sky_queue_depth.set(len(rows))  # ← profundidad del backlog visible en Prometheus
    ...
```

### 3.12 `src/sky/ingestion/circuit_breaker.py` (MODIFICAR)

Leer el archivo antes de instrumentar. Objetivo: llamar
`sky_circuit_breaker_state.labels(source_id=...).set(value)` en cada transición de
estado. El valor es `0=CLOSED`, `1=OPEN`, `2=HALF_OPEN`.

Se implementa en la fase de codeo tras leer el archivo.
El plan garantiza que NO se modifica la lógica del CB — solo se agrega
la llamada a `metrics` al final de cada método que cambia estado.

### 3.13 `src/sky/domain/mr_money.py` (MODIFICAR)

Tras cada llamada real a la Anthropic API, capturar tokens del response:

```python
from sky.core.metrics import sky_mr_money_tokens

# Después de response = await client.messages.create(...)
usage = response.usage
sky_mr_money_tokens.labels(type="input").inc(usage.input_tokens)
sky_mr_money_tokens.labels(type="output").inc(usage.output_tokens)
if hasattr(usage, "cache_read_input_tokens") and usage.cache_read_input_tokens:
    sky_mr_money_tokens.labels(type="cache_read").inc(usage.cache_read_input_tokens)
if hasattr(usage, "cache_creation_input_tokens") and usage.cache_creation_input_tokens:
    sky_mr_money_tokens.labels(type="cache_creation").inc(usage.cache_creation_input_tokens)
```

### 3.14 P2-3 — Rate limiting HTTP API (DIFERIDO a Fase 11)

**Decisión**: `slowapi` no se implementa en Fase 10.

**Razón**: Fase 10 ya cierra 4 pilares ortogonales (Prometheus, Sentry, health/deep,
TODO #7). Agregar `slowapi` introduciría un 5.º pilar con su propio overhead:
configuración por endpoint, Redis como backend de conteo, manejo de `429 Too Many
Requests` en tests de integración. El scope correcto es Fase 11 (Docker + deploy),
donde también se configura el proxy reverso (Railway) que maneja rate limiting
a nivel de infraestructura.

**Cobertura actual (Fase 5)**:
- Rate limiting de scraper: Redis sliding window Lua, namespace `rl:<source_id>`.
  Protección operacional crítica (no martillar bancos). ✓

**Pendiente en Fase 11**:
- Rate limiting del API HTTP público: proteger `/api/*` de abuso externo por IP.
- `slowapi>=0.1.9` + límites configurables por endpoint + test de `429`.

**Acción en este commit**: dejar TODO visible en `src/sky/api/main.py`:

```python
# TODO(Fase11): slowapi — rate limiting HTTP público (P2-3).
# Ver backend-python/docs/MIGRATION_13_PHASES.md §Fase11.
```

---

## 4. Tests

### 4.1 `tests/unit/test_sentry_utils.py` — 13 casos (OBLIGATORIO)

| # | Nombre | Qué verifica |
|---|--------|-------------|
| 1 | `test_password_key_redacted` | `{"password": "s3cr3t"}` → valor = `[REDACTED]` |
| 2 | `test_encrypted_rut_key_redacted` | `{"encrypted_rut": "iv:tag:cipher"}` → `[REDACTED]` |
| 3 | `test_rut_key_redacted` | `{"rut": "12.345.678-9"}` → `[REDACTED]` por KEY |
| 4 | `test_anthropic_token_in_value_redacted` | string `"sk-ant-api03-ABC123defgh"` → `[REDACTED]` |
| 5 | `test_short_sk_not_redacted` | `"sk-abc"` (< 10 chars tras `sk-`) → NO redactado |
| 6 | `test_rut_chileno_in_value_redacted` | `"error para 12.345.678-9"` → `[REDACTED]` |
| 7 | `test_clean_event_unchanged` | evento sin PII → mismos valores en output |
| 8 | `test_nested_dict_scrubbed` | `{"data": {"password": "x"}}` → nested `[REDACTED]` |
| 9 | `test_exception_returns_none` | monkey-patch `_scrub` para lanzar → `before_send` retorna `None` |
| 10 | `test_exception_vars_password_scrubbed` | `event['exception']['values'][0]['stacktrace']['frames'][0]['vars']` con key `password` → `[REDACTED]` |
| 11 | `test_breadcrumb_authorization_scrubbed` | breadcrumb `data` con key `Authorization` (case variante) → `[REDACTED]` |
| 12 | `test_request_data_and_headers_scrubbed` | `event['request']['data']` con key `rut` + `event['request']['headers']` con key `Cookie` → ambos `[REDACTED]` |
| 13 | `test_post_scrub_residual_drops_event` | evento con token Anthropic como clave de dict (sobrevive `_scrub`) → `_event_contains_sensitive` detecta → `before_send` retorna `None` |

**Notas de implementación de tests nuevos (10-13):**

Test 10 — estructura realista de Sentry:
```python
event = {"exception": {"values": [{"stacktrace": {"frames": [{"vars": {"password": "secret"}}]}}]}}
result = before_send(event, {})
assert result["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]["password"] == "[REDACTED]"
```

Test 11 — HTTP header case-insensitive:
```python
event = {"breadcrumbs": {"values": [{"data": {"Authorization": "Bearer tok123"}}]}}
result = before_send(event, {})
assert result["breadcrumbs"]["values"][0]["data"]["Authorization"] == "[REDACTED]"
```

Test 12 — request data + headers:
```python
event = {"request": {"data": {"rut": "12345678-9"}, "headers": {"Cookie": "session=abc"}}}
result = before_send(event, {})
assert result["request"]["data"]["rut"] == "[REDACTED]"
assert result["request"]["headers"]["Cookie"] == "[REDACTED]"
```

Test 13 — post-scrub check (token como clave de dict, no como valor):
```python
# "sk-ant-api03-abc123xyzdef" como KEY no es eliminado por _scrub (no está en _SCRUB_KEYS),
# pero sí es detectado por _event_contains_sensitive al serializar el evento a JSON.
event = {"extra": {"sk-ant-api03-abc123xyzdef": "some_value"}}
result = before_send(event, {})
assert result is None
```

Nota sobre test #9: patch `sky.core.sentry_utils._scrub` para que tire `RuntimeError`.
Verifica que `before_send` atrapa la excepción y devuelve `None` (no re-raise).

### 4.2 `tests/unit/test_health_deep.py` — 7 casos

| # | Nombre | Qué verifica |
|---|--------|-------------|
| 1 | `test_check_db_ok` | mock engine SELECT 1 ok → `"ok"` |
| 2 | `test_check_db_timeout` | mock engine que demora > 2s → `"down"` |
| 3 | `test_check_redis_ok` | mock redis.ping() → `"ok"` |
| 4 | `test_check_redis_failure` | mock redis.ping() lanza → `"down"` |
| 5 | `test_check_anthropic_key_valid` | key `"sk-ant-abc..."` → `"ok"` |
| 6 | `test_check_anthropic_key_empty` | key `""` → `"missing"` |
| 7 | `test_check_anthropic_key_wrong_format` | key `"pk-..."` → `"missing"` |

Para `test_check_db_timeout`: usar `asyncio.sleep` mayor que el timeout y patch del engine
para que `conn.execute` no retorne hasta que `asyncio.timeout` lo cancele.

---

## 5. Definition of Done (gates §3)

Todos deben pasar con exit code 0 antes del commit:

- [ ] `ruff check src/sky/ tests/` → 0 errores
- [ ] `mypy src/sky/` → 0 errores
- [ ] `pytest tests/ -v` → baseline + nuevos tests (≥ 16 tests nuevos: 13 sentry + 7 health - overlap)
- [ ] coverage ≥ 75% en los 4 módulos nuevos:
      `core/metrics.py`, `core/sentry_utils.py`,
      `api/routers/health.py`, `api/middleware/tracing.py`
- [ ] Test manual TODO #7: nueva terminal sin `$env:DATABASE_URL`, import `get_engine` → OK
- [ ] `uvicorn sky.api.main:app` arranca limpio
- [ ] `curl http://localhost:8000/api/health/deep` → `{"status": ..., "db": ..., "redis": ..., "anthropic": ...}` con código 200 o 503
- [ ] `curl http://localhost:8000/metrics` → respuesta en formato Prometheus exposition

---

## 6. Mensaje de commit

```
Fase 10 cerrada: observabilidad Prometheus + Sentry + health profundo

- core/metrics.py: 6 métricas Prometheus sin PII en labels
  (sky_sync_duration, sky_sync_total, sky_queue_depth,
   sky_circuit_breaker_state, sky_api_request_duration,
   sky_mr_money_tokens_total).
- core/sentry_utils.py: init_sentry() + before_send pipeline de dos pasos:
  _scrub (walk recursivo, case-insensitive) elimina encrypted_rut/pass,
  password, rut, clave, tokens sk-ant-/sk-, RUT chileno, headers
  Authorization/Cookie/x-cron-secret.
  _event_contains_sensitive (post-scrub) descarta evento si sobrevive PII.
  Fail-safe: error en cualquier paso → return None.
- api/middleware/tracing.py: RequestTimingMiddleware registra
  sky_api_request_duration por endpoint (path pattern) y status.
- api/routers/health.py: /api/health/deep con check_db (timeout 2s),
  check_redis (timeout 1s), check_anthropic (solo formato de key).
  200 si core ok, 503 si DB o Redis down.
- api/main.py: /metrics endpoint + tracing middleware + Sentry init.
- worker/main.py: Sentry init en startup.
- banking_sync.py: sky_sync_duration + sky_sync_total por banco.
- categorize.py: sky_queue_depth al inicio del batch.
- circuit_breaker.py: sky_circuit_breaker_state en transiciones.
- mr_money.py: sky_mr_money_tokens_total post-llamada Anthropic.
- TODO #7 cerrado: core/db.py usa settings.database_url (pydantic-settings
  lee del .env automáticamente; no requiere $env:DATABASE_URL en shell).
- pyproject.toml: sentry-sdk[fastapi]>=2.0.0.
- P2-3 (rate limiting HTTP): diferido a Fase 11 — TODO en api/main.py.
- Deuda cerrada: P2-1, P2-2, P2-4.
- tests: 13 casos sentry_utils (9 base + 4 nuevos: exception vars,
         breadcrumb headers, request data/headers, post-scrub residual)
         + 7 casos health_deep.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## 7. Update `docs/MIGRATION_13_PHASES.md`

```markdown
### Estado: ✅ Cerrada (2026-05-06)

### Archivos finales
- src/sky/core/metrics.py            (6 métricas Prometheus — NUEVO)
- src/sky/core/sentry_utils.py       (init + before_send — NUEVO)
- src/sky/api/middleware/tracing.py  (RequestTimingMiddleware — NUEVO)
- src/sky/api/routers/health.py      (/api/health/deep)
- src/sky/api/main.py                (/metrics + middleware + Sentry + TODO P2-3)
- src/sky/worker/main.py             (Sentry init)
- src/sky/worker/banking_sync.py     (sky_sync_duration + sky_sync_total)
- src/sky/worker/jobs/categorize.py  (sky_queue_depth)
- src/sky/ingestion/circuit_breaker.py (sky_circuit_breaker_state)
- src/sky/domain/mr_money.py         (sky_mr_money_tokens_total)
- src/sky/core/config.py             (database_url + sentry_dsn)
- src/sky/core/db.py                 (TODO #7 — settings.database_url)
- pyproject.toml                     (sentry-sdk[fastapi])
- tests/unit/test_sentry_utils.py   (13 casos — NUEVO)
- tests/unit/test_health_deep.py    (7 casos — NUEVO)

### Deuda cerrada
- P2-1: tests de observabilidad → test_sentry_utils.py + test_health_deep.py
- P2-2: CI con métricas → /metrics endpoint disponible
- P2-3: DIFERIDO a Fase 11 — TODO en api/main.py (slowapi HTTP rate limiting)
- P2-4: Monitoring → Sentry + /health/deep
- TODO #7: database_url vía pydantic-settings

### Gates verificados
- [x] ruff → 0
- [x] mypy → 0
- [x] pytest baseline + nuevos
- [x] coverage ≥ 75% en core/metrics.py, sentry_utils.py, tracing.py, health.py
- [ ] test manual TODO #7 (nueva terminal sin $env:)
- [ ] uvicorn + /health/deep + /metrics (gates manuales)
```

---

## 8. Siguiente fase

**Fase 11** — Docker + deploy Railway. Los servicios Python se deployean como
servicios NUEVOS (sin tocar `api.skyfinanzas.com` aún). Incluye `slowapi` para
cerrar P2-3 definitivamente.
