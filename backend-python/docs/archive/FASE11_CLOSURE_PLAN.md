# FASE 11 — Docker + Deploy + Production Hardening: Plan de cierre v2

> Plan-first obligatorio. Sin plan aprobado no se escribe código.
> Template: `FASE10_CLOSURE_PLAN.md`.
> Fecha: 2026-05-10
> Doctrina: production-grade desde día 1. Sin deuda "a mejorar después".

---

## 1. Contexto

### Objetivo
Siete resultados en un solo commit:

1. **Docker images** — API (<500 MB, sin Playwright) y worker (<1.5 GB, con Chromium)
   buildean y arrancan localmente.
2. **Runbook Railway** — checklist completo para deploy manual como servicios nuevos.
3. **P2-3 cerrado** — `slowapi` rate limiting Redis-backed por `user_id` verificado.
   Requiere `JWTContextMiddleware` que setea `request.state.user_id` antes del
   rate limiter.
4. **P2-6 cerrado** — key versioning en `encryption.py` + `rekey_bank_accounts.py`
   (script de rotación) + `RUNBOOK_KEY_ROTATION.md`.
5. **R4 cerrado** — `DECISION_SECRETS_MANAGER.md` como ADR formal.
6. **Audit log (R18 adelantado de Fase 12)** — tabla `audit_log` + helper `core/audit.py`
   instrumentado en hot paths de banking. ISO27001 A.12.4.
7. **Idempotency key** — deduplicación 24h vía Redis en endpoints de side-effect.

### Hardening transversal (en TODO el código de esta fase)
- Security headers en TODA response (nuevo middleware).
- `PROMETHEUS_SECRET` y `SENTRY_DSN` required en `is_production=True` (fail-fast).
- Sin PII en `audit_log.metadata`, métricas, ni Sentry (ya garantizado por
  `before_send` de Fase 10).
- Audit log es inmutable (solo INSERT, sin UPDATE/DELETE).

### Lo que esta fase NO hace
- NO apunta `api.skyfinanzas.com` a Python (Fase 13, tras parity tests).
- NO ejecuta el deploy en Railway — provee el runbook. El usuario lo corre.
- NO toca `backend/` (Node, producción viva).

### Deuda que se cierra
| ID | Descripción |
|----|-------------|
| P2-3 | Rate limiting HTTP API por user_id (Redis-backed) |
| P2-6 | Rotación `BANK_ENCRYPTION_KEY` con procedimiento |
| R4 | Decisión Secrets Manager (ADR) |
| R18 adelantado | Audit log en producción desde día 1 (requerimiento ISO27001) |
| DEPRECATED | `/api/internal/cron/sync-due`: añadir warning log. NO borrar aún (Fase 13). |

---

## 2. Archivos involucrados

### Nuevos (19)
```
docker/api.Dockerfile
docker/worker.Dockerfile
docker/docker-compose.yml
railway.json

src/sky/api/middleware/jwt_context.py   ← JWTContextMiddleware (setea request.state.user_id)
src/sky/api/middleware/rate_limit.py    ← slowapi Limiter Redis-backed (P2-3)
src/sky/api/middleware/security_headers.py
src/sky/api/middleware/idempotency.py
src/sky/core/audit.py                   ← log_event() helper (R18)

migrations/004_audit_log.sql

scripts/rekey_bank_accounts.py          ← re-cifrado dry-run+apply (P2-6)

docs/RUNBOOK_KEY_ROTATION.md
docs/SECURITY.md
docs/DR_RUNBOOK.md
docs/DECISION_SECRETS_MANAGER.md
docs/API_CONTRACT.md
docs/FASE11_DEPLOY_CHECKLIST.md

tests/unit/test_rate_limit.py           ← ≥5 casos
tests/unit/test_security_headers.py     ← 1 caso por header (≥6)
tests/unit/test_idempotency.py          ← 3 casos
tests/unit/test_audit.py                ← 5 casos
```

### Modificados (10)
```
pyproject.toml
src/sky/core/config.py
src/sky/core/encryption.py              ← strip_version_prefix + decrypt actualizado
src/sky/api/deps.py                     ← require_user_id lee request.state.user_id
src/sky/api/main.py
src/sky/api/routers/chat.py             ← @limiter.limit
src/sky/api/routers/banking.py          ← @limiter.limit + audit log
src/sky/api/routers/internal.py         ← warning log en /cron/sync-due (NO borrar)
src/sky/worker/banking_sync.py          ← audit log
.env.example
docs/MIGRATION_13_PHASES.md
```

---

## 3. Cambios detallados

### 3.1 `docker/api.Dockerfile` (NUEVO)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

# No editable, no dev extras, sin playwright install chromium
RUN pip install --no-cache-dir .

EXPOSE 8000

# DB-less health check — responde aunque DB y Redis no estén disponibles.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

CMD ["uvicorn", "sky.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Doctrina**: `playwright` Python package se instala (dep del proyecto), pero NO se
ejecuta `playwright install chromium`. La API nunca usa browser pool. Target < 500 MB.

### 3.2 `docker/worker.Dockerfile` (NUEVO)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# Chromium + todas sus dependencias de sistema en una pasada
RUN playwright install chromium --with-deps

RUN rm -rf /var/lib/apt/lists/*

CMD ["arq", "sky.worker.main.WorkerSettings"]
```

**Target < 1.5 GB**. Sin HEALTHCHECK — ARQ no expone HTTP.

### 3.3 `docker/docker-compose.yml` (NUEVO)

```yaml
version: "3.9"
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  api:
    build:
      context: ..          # build context = backend-python/
      dockerfile: docker/api.Dockerfile
    ports:
      - "8000:8000"
    env_file:
      - ../.env
    environment:
      - REDIS_URL=redis://redis:6379
      - NODE_ENV=development
    depends_on:
      redis:
        condition: service_healthy

  worker:
    build:
      context: ..
      dockerfile: docker/worker.Dockerfile
    env_file:
      - ../.env
    environment:
      - REDIS_URL=redis://redis:6379
      - NODE_ENV=development
    depends_on:
      redis:
        condition: service_healthy
```

### 3.4 `railway.json` (NUEVO — en `backend-python/`)

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "dockerfilePath": "docker/api.Dockerfile"
  },
  "deploy": {
    "healthcheckPath": "/api/health",
    "healthcheckTimeout": 30,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

El worker Railway service sobreescribe `dockerfilePath` a `docker/worker.Dockerfile`
desde el dashboard (no se puede configurar dos servicios en el mismo `railway.json`).

### 3.5 `pyproject.toml` (MODIFICAR)

```toml
"slowapi>=0.1.9",     # rate limiting HTTP (P2-3)
```

Mypy override para slowapi (por si carece de stubs completos):
```toml
[[tool.mypy.overrides]]
module = ["slowapi", "slowapi.*"]
ignore_missing_imports = true
```

### 3.6 `src/sky/core/config.py` (MODIFICAR)

Cinco settings nuevos:

```python
# ── Rate limiting HTTP (Fase 11 — P2-3) ───────────────────────────────────────
api_rate_limit_per_minute: int = 60

# ── Observabilidad prod (Fase 11) ─────────────────────────────────────────────
# Fail-fast si is_production=True y están vacíos (verificado en main.py).
prometheus_secret: str = ""   # vacío = acceso libre en dev
# sentry_dsn: str = ""        ← ya existe — solo documentar el fail-fast de prod

# ── Idempotency (Fase 11) ─────────────────────────────────────────────────────
idempotency_ttl_seconds: int = 86400    # 24h

# ── Rotación de clave bancaria (Fase 11 — P2-6) ───────────────────────────────
bank_encryption_key_v2: str = ""        # vacío = sin rotación activa
```

### 3.7 `src/sky/core/encryption.py` (MODIFICAR — P2-6)

Dos cambios:

**A) Agregar `strip_version_prefix`**:
```python
import re as _re
_VERSION_PREFIX_RE = _re.compile(r"^v\d+:")

def strip_version_prefix(ciphertext: str) -> str:
    """
    Elimina prefijo de versión si está presente.
    'v2:iv:tag:cipher' → 'iv:tag:cipher'. Sin prefijo → sin cambios.
    """
    return _VERSION_PREFIX_RE.sub("", ciphertext, count=1)
```

**B) Actualizar `decrypt()` para aceptar prefijo**:
```python
def decrypt(encrypted_string: str, raw_key: str) -> str:
    if not encrypted_string:
        raise ValueError("encrypted_string inválido")

    # Eliminar prefijo de versión si presente ('v1:', 'v2:', etc.)
    cleaned = strip_version_prefix(encrypted_string)

    parts = cleaned.split(":")
    if len(parts) != 3:
        raise ValueError("formato inválido — esperado [vN:]iv:authTag:ciphertext")
    # ... resto sin cambios
```

**Invariante**: ciphertexts actuales en DB (sin prefijo = v1) → `strip_version_prefix`
es no-op → decrypt funciona igual que antes. Ciphertexts v2 (post-rotación, con `v2:`)
→ strip prefix → decrypt con `bank_encryption_key_v2`.

Para el período de rotación, `banking_sync.py` necesitará lógica dual-key (ver
`RUNBOOK_KEY_ROTATION.md` §Paso 3). No se implementa ahora: no hay ciphertexts v2
en producción.

### 3.8 `src/sky/api/middleware/jwt_context.py` (NUEVO)

**Problema**: `SlowAPIMiddleware` aplica el rate limit en la capa de middleware,
antes de que las dependencias de FastAPI (como `require_user_id`) se ejecuten.
Para usar `user_id` verificado como rate limit key, necesitamos setear
`request.state.user_id` en un middleware que corra ANTES de `SlowAPIMiddleware`.

```python
"""sky.api.middleware.jwt_context — Setea request.state.user_id (para rate limiter)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from sky.api.middleware.jwt_auth import extract_and_verify_user_id
from sky.core.errors import AuthenticationError


class JWTContextMiddleware(BaseHTTPMiddleware):
    """
    Extrae y verifica JWT. Si es válido, setea request.state.user_id.
    Si es inválido o ausente, setea request.state.user_id = None.

    NO rechaza requests — eso es responsabilidad de require_user_id.
    Propósito: proveer user_id verificado al rate limiter y otros middlewares.
    """

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        request.state.user_id = None
        try:
            request.state.user_id = await extract_and_verify_user_id(request)
        except (AuthenticationError, Exception):
            pass  # user_id stays None — route handler enforces auth
        return await call_next(request)
```

Actualizar `src/sky/api/deps.py` para leer del state en lugar de re-decodificar:

```python
async def require_user_id(request: Request) -> str:
    """Dependency que garantiza un usuario autenticado."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise AuthenticationError("Token de autenticación requerido")
    return user_id
```

**Beneficio doble**: JWT se verifica UNA sola vez por request (en el middleware),
no dos veces (middleware + dependency). Defense-in-depth mantenida: si el middleware
falla silenciosamente, `require_user_id` rechaza con 401.

### 3.9 `src/sky/api/middleware/rate_limit.py` (NUEVO — P2-3)

```python
"""sky.api.middleware.rate_limit — slowapi Limiter Redis-backed (P2-3)."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from sky.core.config import settings


def _get_rate_limit_key(request: Request) -> str:
    """
    Rate limit key: user_id verificado (seteado por JWTContextMiddleware).
    IP como fallback para endpoints públicos o requests sin JWT válido.

    JWTContextMiddleware debe correr ANTES de SlowAPIMiddleware para que
    request.state.user_id esté disponible aquí.
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


# Redis-backed: contador compartido entre todas las instancias del API.
# Garantía de autoescala — si se agregan instancias en Railway, el límite
# sigue siendo efectivo a nivel global (no por proceso).
limiter = Limiter(
    key_func=_get_rate_limit_key,
    storage_uri=settings.redis_url,
)


def on_rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:  # noqa: ARG001
    return JSONResponse(
        status_code=429,
        content={"error": "Rate limit excedido. Intenta en unos segundos."},
    )
```

### 3.10 `src/sky/api/middleware/security_headers.py` (NUEVO)

```python
"""sky.api.middleware.security_headers — HTTP security headers en toda response."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Agrega security headers a TODA response, incluidas 4xx/5xx.
    Requerido para compliance ISO27001 A.14.1 y auditoría bancaria.
    """

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        response: Response = await call_next(request)
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains; preload"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response
```

### 3.11 `src/sky/api/middleware/idempotency.py` (NUEVO)

Deduplicación 24h para endpoints de side-effect. Evita doble sync y doble connect
en caso de retry del frontend (red inestable, timeout aparente).

```python
"""sky.api.middleware.idempotency — Deduplicación 24h vía Redis."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sky.core.config import settings
from sky.core.logging import get_logger

logger = get_logger("idempotency")

# Rutas POST donde aplica la deduplicación
_IDEMPOTENT_PATHS = frozenset({
    "/api/banking/sync",        # prefix — cualquier /api/banking/sync/*
    "/api/banking/sync-all",
    "/api/banking/accounts",    # POST connect
})


def _is_idempotent_route(request: Request) -> bool:
    if request.method != "POST":
        return False
    path = request.url.path
    return any(path == p or path.startswith(p + "/") for p in _IDEMPOTENT_PATHS)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Si el request incluye header 'Idempotency-Key' (UUID v4) y la ruta
    es idempotente, busca la respuesta en Redis.
    - Si existe: retorna cached (X-Idempotency-Replay: true).
    - Si no: procesa y almacena la respuesta 24h.
    """

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        idk = request.headers.get("Idempotency-Key")
        if not idk or not _is_idempotent_route(request):
            return await call_next(request)

        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            return await call_next(request)

        cache_key = f"idk:{idk}"

        try:
            cached = await redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                logger.info("idempotency_replay", key=idk)
                return JSONResponse(
                    status_code=data["status_code"],
                    content=data["content"],
                    headers={"X-Idempotency-Replay": "true"},
                )
        except Exception as exc:
            logger.warning("idempotency_cache_read_failed", error=str(exc))
            return await call_next(request)

        response: Response = await call_next(request)

        # Solo cachear respuestas exitosas (2xx)
        if 200 <= response.status_code < 300:
            try:
                body = b""
                async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                    body += chunk

                await redis.setex(
                    cache_key,
                    settings.idempotency_ttl_seconds,
                    json.dumps({
                        "status_code": response.status_code,
                        "content": json.loads(body) if body else {},
                    }),
                )

                return Response(
                    content=body,
                    status_code=response.status_code,
                    media_type=response.media_type,
                    headers=dict(response.headers),
                )
            except Exception as exc:
                logger.warning("idempotency_cache_write_failed", error=str(exc))

        return response
```

**Nota de seguridad**: el `cache_key` es `idk:{idempotency_key}`. Si el usuario
malintencionado usa el UUID de otro usuario, accede a la respuesta cacheada de ese
UUID. **Mitigación**: el UUID v4 tiene 122 bits de entropía — colisión intencional
es computacionalmente inviable. Si se requiere más aislamiento, se puede namespear
como `idk:{user_id}:{idempotency_key}` (añadir en una futura iteración).

### 3.12 `src/sky/api/main.py` (MODIFICAR)

**Cambio A** — Fail-fast producción (junto al check de CORS existente):
```python
if settings.is_production and not settings.prometheus_secret:
    raise RuntimeError(
        "PROMETHEUS_SECRET requerido en producción. "
        "Las métricas no pueden ser públicas."
    )
if settings.is_production and not settings.sentry_dsn:
    raise RuntimeError(
        "SENTRY_DSN requerido en producción. "
        "La falta de Sentry en prod es un agujero de observabilidad."
    )
```

**Cambio B** — Agregar middlewares (orden CRÍTICO — LIFO):
```python
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sky.api.middleware.idempotency import IdempotencyMiddleware
from sky.api.middleware.jwt_context import JWTContextMiddleware
from sky.api.middleware.rate_limit import limiter, on_rate_limit_exceeded
from sky.api.middleware.security_headers import SecurityHeadersMiddleware

# En create_app(), DESPUÉS de añadir CORSMiddleware:
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, on_rate_limit_exceeded)  # type: ignore[arg-type]

# Orden de add_middleware (LIFO → último añadido = más externo):
# CORSMiddleware ya está (1°, más interno)
app.add_middleware(RequestTimingMiddleware)      # 2° — mide tiempo
app.add_middleware(SlowAPIMiddleware)            # 3° — aplica rate limit
app.add_middleware(IdempotencyMiddleware)        # 4° — dedup
app.add_middleware(JWTContextMiddleware)         # 5° — setea user_id antes de SlowAPI
app.add_middleware(SecurityHeadersMiddleware)    # 6° (más externo) — headers en TODA response
```

**Flujo de request resultante**:
SecurityHeaders → JWTContext (setea user_id) → Idempotency → SlowAPI (lee user_id) → RequestTiming → CORS → handler

**Cambio C** — Protección `/metrics`:
```python
import secrets as _secrets

@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> StarletteResponse:
    if settings.prometheus_secret:
        provided = request.headers.get("x-prometheus-secret", "")
        if not _secrets.compare_digest(provided, settings.prometheus_secret):
            return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return StarletteResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

### 3.13 `src/sky/api/routers/chat.py` + `banking.py` (MODIFICAR — P2-3)

Agregar `@limiter.limit(...)` a endpoints sensibles. Todos ya tienen `request: Request`.

**chat.py**:
```python
from sky.api.middleware.rate_limit import limiter
from sky.core.config import settings

@router.post("", ...)
@limiter.limit(f"{settings.api_rate_limit_per_minute}/minute")
async def chat_endpoint(body: ChatRequest, request: Request, ...):
    ...
```

**banking.py** — tres endpoints:
```python
from sky.api.middleware.rate_limit import limiter
from sky.core.config import settings

@router.post("/sync/{account_id}", ...)
@limiter.limit(f"{settings.api_rate_limit_per_minute}/minute")
async def sync_bank_account_endpoint(account_id: str, request: Request, ...):
    ...

@router.post("/sync-all", ...)
@limiter.limit(f"{settings.api_rate_limit_per_minute}/minute")
async def sync_all_endpoint(request: Request, ...):
    ...

@router.post("/accounts", ..., status_code=201)
@limiter.limit(f"{settings.api_rate_limit_per_minute}/minute")
async def connect_account(body: ..., request: Request, ...):
    ...
```

**GET /accounts NO se rate-limita** — lectura liviana, no opera contra bancos.

### 3.14 `src/sky/api/routers/internal.py` (MODIFICAR)

Agregar warning log a `/cron/sync-due` pero NO borrar (Fase 13 cleanup):

```python
@router.post("/cron/sync-due")
async def cron_sync_due(request: Request) -> dict[str, int]:
    """
    [DEPRECATED — Fase 9, eliminar en Fase 13]
    ...
    """
    logger.warning(
        "cron_sync_due_deprecated",
        reason="Replaced by ARQ cron (scheduled_sync_job). Remove in Fase 13.",
    )
    # ... resto del código sin cambios
```

### 3.15 `src/sky/core/audit.py` (NUEVO — R18)

```python
"""sky.core.audit — Registro de eventos auditables (ISO27001 A.12.4)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("audit")


async def log_event(
    *,
    action: str,
    user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """
    Inserta evento en public.audit_log. Fire-and-forget: si falla, loguea
    warning pero NO propaga excepción (nunca bloquear hot path de negocio).

    NUNCA incluir PII en metadata: sin RUT, password, ni tokens bancarios.
    Audit log es inmutable: no UPDATE, no DELETE.

    Acciones críticas:
        sync.start, sync.success, sync.error,
        account.connected, account.disconnected,
        key.access (para trazabilidad en rotación de clave)
    """
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO public.audit_log
                        (user_id, action, resource_type, resource_id,
                         metadata, ip_address, user_agent)
                    VALUES
                        (:user_id, :action, :resource_type, :resource_id,
                         :metadata::jsonb, :ip_address::inet, :user_agent)
                """),
                {
                    "user_id": user_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "metadata": json.dumps(metadata or {}),
                    "ip_address": ip_address,
                    "user_agent": user_agent,
                },
            )
    except Exception as exc:
        logger.warning("audit_log_failed", action=action, error=str(exc))
```

Instrumentar en:

**`banking_sync.py`**:
```python
from sky.core.audit import log_event

# Al inicio de sync (antes del advisory lock check):
await log_event(
    action="sync.start",
    user_id=user_id,
    resource_type="bank_account",
    resource_id=bank_account_id,
    metadata={"bank_id": bank_id},
)

# Al final, tras update exitoso:
await log_event(
    action="sync.success",
    user_id=user_id,
    resource_type="bank_account",
    resource_id=bank_account_id,
    metadata={"bank_id": bank_id, "new_transactions": inserted, "elapsed_ms": elapsed_ms},
)

# En excepciones:
await log_event(
    action="sync.error",
    user_id=user_id,
    resource_type="bank_account",
    resource_id=bank_account_id,
    metadata={"bank_id": bank_id, "error_type": type(exc).__name__},
)
```

**`banking.py`**:
```python
# Tras connect_account exitoso:
await log_event(
    action="account.connected",
    user_id=user_id,
    resource_type="bank_account",
    resource_id=str(new_account_id),
    metadata={"bank_id": body.bank_id},
    ip_address=request.client.host if request.client else None,
)

# En DELETE /accounts/{id}:
await log_event(
    action="account.disconnected",
    user_id=user_id,
    resource_type="bank_account",
    resource_id=account_id,
    ip_address=request.client.host if request.client else None,
)
```

**Invariante de seguridad**: `metadata` NUNCA contiene `rut`, `password`,
`encrypted_rut`, `encrypted_pass`, ni tokens. Test lo verifica explícitamente.

### 3.16 `migrations/004_audit_log.sql` (NUEVO)

```sql
-- Fase 11: tabla de audit log (ISO27001 A.12.4)
-- Aplicar ANTES del deploy en Railway.

CREATE TABLE IF NOT EXISTS public.audit_log (
    id           BIGSERIAL PRIMARY KEY,
    user_id      UUID,
    action       TEXT    NOT NULL,
    resource_type TEXT,
    resource_id  UUID,
    metadata     JSONB   NOT NULL DEFAULT '{}'::jsonb,
    ip_address   INET,
    user_agent   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_log_user_created
    ON public.audit_log (user_id, created_at DESC);

CREATE INDEX idx_audit_log_action
    ON public.audit_log (action, created_at DESC);

-- RLS: usuarios solo pueden leer sus propios eventos.
-- El backend escribe con service_role (sin RLS).
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_log_own_read ON public.audit_log
    FOR SELECT USING (user_id = auth.uid());

-- Inmutabilidad: prevenir UPDATE y DELETE en la tabla.
-- (REVOKE solo es efectivo si los roles de app usan anon_key, no service_role)
-- Con service_role: la inmutabilidad es doctrinal (aplicada en código — solo INSERT).
-- TODO Fase 12: trigger de purge para registros > 90 días (cumplimiento retención).

COMMENT ON TABLE public.audit_log IS
    'Inmutable. Solo INSERT permitido desde código. Retención: 90 días (TODO trigger Fase 12).';
```

### 3.17 `scripts/rekey_bank_accounts.py` (NUEVO — P2-6)

Script de re-cifrado para rotación de clave. Dry-run por default.

```python
"""
scripts/rekey_bank_accounts.py — Re-cifrado de credenciales con nueva clave.

Uso (dry-run, NO escribe en DB):
    python scripts/rekey_bank_accounts.py

Uso (aplicar cambios reales):
    python scripts/rekey_bank_accounts.py --apply

Requiere:
    BANK_ENCRYPTION_KEY    = clave actual (ciphertexts sin prefijo en DB)
    BANK_ENCRYPTION_KEY_V2 = clave nueva (ciphertexts re-cifrados tendrán prefijo 'v2:')
    DATABASE_URL           = postgresql://... (Supabase)

Proceso:
    1. Lee todos los bank_accounts donde encrypted_rut NOT LIKE 'v2:%'.
    2. Para cada registro: decrypt con BANK_ENCRYPTION_KEY (v1).
    3. Re-cifra con BANK_ENCRYPTION_KEY_V2, agrega prefijo 'v2:'.
    4. Si --apply: UPDATE bank_accounts SET encrypted_rut=..., encrypted_pass=...
    5. Imprime resumen: N procesados, M ya en v2 (skipped), K errores.

Ver docs/RUNBOOK_KEY_ROTATION.md para el procedimiento completo.
"""
```

### 3.18 Documentación (NUEVOS)

**`docs/RUNBOOK_KEY_ROTATION.md`** — 5 pasos:
1. Generar nueva clave (`secrets.token_hex(32)`).
2. Dry-run del script.
3. Actualizar `banking_sync.py` para dual-decrypt (código incluido paso a paso).
4. Deploy del código dual-decrypt. Ejecutar `rekey_bank_accounts.py --apply`.
5. Retirar clave v1: rename v2→v1 en Railway, redeploy, revertir dual-decrypt.

**`docs/SECURITY.md`** — 9 secciones:
Cifrado (doble capa: app + Supabase), TLS/HSTS, Auth (JWT + RLS), Audit Log,
Acceso a credenciales, 2FA enforcement, Backup/Recovery (Supabase Pro, PITR 7d),
Vendor risk (Supabase/Railway/Anthropic SOC2), Contacts.

**`docs/DR_RUNBOOK.md`** — 3 escenarios:
Supabase down, Railway down (fallback Render/Fly.io), breach de credenciales
(linkea RUNBOOK_KEY_ROTATION.md).

**`docs/DECISION_SECRETS_MANAGER.md`** — ADR formal:
Tres opciones (Railway env vars / AWS SM / Vault). Decisión: Railway con plan
documentado de migración a AWS SM si/cuando exija due diligence bancaria.

**`docs/API_CONTRACT.md`** — `Idempotency-Key` header: cuándo usarlo, qué
endpoints lo soportan, TTL 24h, comportamiento sin header.

**`docs/FASE11_DEPLOY_CHECKLIST.md`** — env vars por servicio Railway, pasos
de verificación post-deploy, DNS temporal.

### 3.19 `.env.example` (MODIFICAR)

```bash
# Rate limiting HTTP
API_RATE_LIMIT_PER_MINUTE=60

# Métricas (vacío = abiertas en dev, requerido en prod)
PROMETHEUS_SECRET=

# Idempotency window
IDEMPOTENCY_TTL_SECONDS=86400

# Rotación de clave (solo durante período de rotación activa)
# BANK_ENCRYPTION_KEY_V2=nueva_clave_hex_64_chars
```

### 3.20 Confirmaciones definitivas (adendas al plan original)

Cuatro ajustes aprobados al iniciar implementación:

1. **Idempotency in-progress sentinel**: Si hay request en vuelo con la misma
   `Idempotency-Key`, Redis tiene `idk:inprogress:{key}` (TTL 30s de seguridad).
   Responder 409 + `Retry-After: 5` en lugar de dejar la segunda request colgar.
   Cuando la primera termina: DELETE sentinel, SETEX respuesta real.
   Tests: `test_in_progress_sentinel_returns_409` incluido.

2. **CSP solo en producción**: `Content-Security-Policy: default-src 'self'` se
   aplica solo cuando `settings.is_production=True`. En dev, omitir para no romper
   Swagger (`/docs`). Otros 5 headers se aplican siempre.

3. **Audit log NO silencioso**: si INSERT falla → `logger.error(...)` +
   `sentry_sdk.capture_message(level="warning")` (no-op si Sentry no está
   inicializado). Excepción swallowed solo para no bloquear hot path de negocio.

4. **Orden LIFO explícito en main.py** (source code):
   `add_middleware(IdempotencyMiddleware)` →
   `add_middleware(SlowAPIMiddleware)` →
   `add_middleware(JWTContextMiddleware)` →
   `add_middleware(SecurityHeadersMiddleware)` (último = más externo).
   Ejecución request: SecurityHeaders → JWTContext → SlowAPI → Idempotency → CORS → handler.
   Test `test_security_headers_on_rate_limited_response` verifica headers en 429.

---

## 4. Tests

### `tests/unit/test_rate_limit.py` — 5+ casos

| # | Nombre | Qué verifica |
|---|--------|-------------|
| 1 | `test_key_with_user_id_on_state` | `request.state.user_id = "abc"` → key = `"user:abc"` |
| 2 | `test_key_without_user_id_fallback_to_ip` | `request.state.user_id = None`, `client.host = "1.2.3.4"` → key = `"ip:1.2.3.4"` |
| 3 | `test_key_no_state_attribute` | `request.state` sin `user_id` attr → fallback IP |
| 4 | `test_on_rate_limit_exceeded_returns_429` | handler → JSONResponse status 429 |
| 5 | `test_limiter_uses_redis_storage` | `type(limiter.storage).__name__` contiene "Redis" |

**Test 5 — autoescala safety**:
```python
def test_limiter_uses_redis_storage():
    """Verifica Redis-backed (no in-memory). Redis-backed = seguro para autoescala."""
    from sky.api.middleware.rate_limit import limiter
    storage_name = type(limiter.storage).__name__
    assert "redis" in storage_name.lower() or "Redis" in storage_name
```

### `tests/unit/test_security_headers.py` — ≥6 casos

Un caso por header. Usar `FastAPI` + `httpx.AsyncClient` en cada test:
```python
app = FastAPI()
app.add_middleware(SecurityHeadersMiddleware)

@app.get("/test")
async def dummy(): return {}

async def test_hsts():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/test")
    assert resp.headers["Strict-Transport-Security"] == "max-age=63072000; includeSubDomains; preload"
```

| # | Header verificado |
|---|-------------------|
| 1 | `Strict-Transport-Security` |
| 2 | `X-Content-Type-Options` |
| 3 | `X-Frame-Options` |
| 4 | `Content-Security-Policy` |
| 5 | `Referrer-Policy` |
| 6 | `Permissions-Policy` |
| 7 | `test_headers_present_on_4xx` — GET a ruta inexistente → 404, headers igualmente presentes |

### `tests/unit/test_idempotency.py` — 3 casos

```
test_new_request_processes_normally: sin key en Redis → llama call_next → 200
test_repeat_request_returns_cached:  key en Redis → devuelve cached, X-Idempotency-Replay: true
test_no_idempotency_header_skips:    sin header → llama call_next directamente
```

Usar `AsyncMock` para `redis.get` y `redis.setex`. Mockear `request.app.state.redis`.

### `tests/unit/test_audit.py` — 5 casos

```
test_log_sync_start:           log_event("sync.start", ...) → INSERT ejecutado
test_log_sync_success:         log_event("sync.success", ...) → INSERT ejecutado
test_log_sync_error:           log_event("sync.error", ...) → INSERT ejecutado
test_log_account_connected:    log_event("account.connected", ...) → INSERT ejecutado
test_log_db_failure_no_raise:  DB lanza excepción → log_event swallows → no re-raise
```

Para todos: mockear `get_engine()` con `AsyncMock`. Verificar que la query SQL
contiene el `action` correspondiente. Verificar que `metadata` en los tests de
sync no contiene claves `rut`, `password`, `encrypted_rut`, `encrypted_pass`.

---

## 5. Definition of Done (gates §3)

Todos deben pasar con exit code 0 antes del commit:

- [ ] `ruff check src/sky/ tests/ scripts/` → 0 errores
- [ ] `mypy src/sky/` → 0 errores
- [ ] `pytest tests/ -v` → ≥308 baseline + nuevos (esperado ~327)
- [ ] coverage ≥ 80% en:
      `rate_limit.py`, `security_headers.py`, `idempotency.py`,
      `audit.py`, `encryption.py` (incluyendo `strip_version_prefix`)
- [ ] `docker build -f docker/api.Dockerfile -t sky-api-test .` → exit 0
      (desde `backend-python/`)
- [ ] `docker image ls sky-api-test --format "{{.Size}}"` → resultado < 500 MB
- [ ] `docker build -f docker/worker.Dockerfile -t sky-worker-test .` → exit 0
      (puede tomar 5-10 min por descarga de Chromium)
- [ ] `docker image ls sky-worker-test --format "{{.Size}}"` → resultado < 1.5 GB
- [ ] `docker compose -f docker/docker-compose.yml up -d --build`
      → `curl http://localhost:8000/api/health` → 200 JSON
- [ ] `docker compose -f docker/docker-compose.yml down`
- [ ] Test manual prod fail-fast:
      `$env:NODE_ENV="production"; $env:PROMETHEUS_SECRET=""; python -c "from sky.api.main import create_app; create_app()"` → RuntimeError visible

---

## 6. Mensaje de commit

```
Fase 11 cerrada: Docker + Railway + production-grade hardening

- docker/api.Dockerfile: python:3.12-slim sin Playwright (<500MB)
- docker/worker.Dockerfile: playwright install chromium --with-deps (<1.5GB)
- docker/docker-compose.yml: stack local Redis + API + worker
- railway.json: healthcheckPath /api/health, ON_FAILURE restart
- P2-3 cerrado: slowapi Redis-backed por user_id verificado (JWTContextMiddleware
  setea request.state.user_id antes de SlowAPIMiddleware)
  /api/chat, /api/banking/sync/*, /api/banking/sync-all, /api/banking/accounts
  default 60 req/min, configurable via API_RATE_LIMIT_PER_MINUTE
- SecurityHeadersMiddleware: HSTS, X-Frame-Options, CSP, Referrer-Policy,
  Permissions-Policy en toda response (incluidas 4xx/5xx)
- IdempotencyMiddleware: dedup 24h vía Redis para POST banking endpoints
- PROMETHEUS_SECRET + SENTRY_DSN: fail-fast en is_production=True
- /metrics: requiere x-prometheus-secret header en prod
- R18 cerrado (adelantado de Fase 12): public.audit_log + core/audit.py
  log_event en sync.start/success/error, account.connected/disconnected
  Inmutable por doctrina. RLS habilitado. TODO purge Fase 12.
- P2-6 cerrado: encryption.strip_version_prefix + decrypt acepta prefijo vN:
  + scripts/rekey_bank_accounts.py (dry-run/apply)
  + docs/RUNBOOK_KEY_ROTATION.md (5 pasos step-by-step)
- R4 cerrado: docs/DECISION_SECRETS_MANAGER.md (ADR: Railway env vars;
  plan migración a AWS SM documentado)
- /api/internal/cron/sync-due: warning log agregado (NO borrado — Fase 13)
- 5 docs nuevos: SECURITY.md, DR_RUNBOOK.md, RUNBOOK_KEY_ROTATION.md,
  DECISION_SECRETS_MANAGER.md, API_CONTRACT.md, FASE11_DEPLOY_CHECKLIST.md
- tests: test_rate_limit (5), test_security_headers (7), test_idempotency (3),
  test_audit (5) — coverage ≥80% en módulos nuevos

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## 7. Update `docs/MIGRATION_13_PHASES.md`

```markdown
### Estado: ✅ Cerrada (2026-05-10)

### Nota
Audit log (R18) adelantado de Fase 12 a Fase 11 por requerimiento de demo
ISO27001 / due diligence bancaria. Fase 12 queda limitada a índices SQL,
RLS audit y purge trigger.

### Archivos finales
[lista completa de los 29 archivos involucrados]

### Deuda cerrada
- P2-3: rate limit Redis-backed por user_id verificado
- P2-6: key versioning + runbook rotación
- R4: ADR Secrets Manager (Railway env vars)
- R18: audit log en producción desde día 1

### Gates verificados
[lista de gates §5]
```

---

## 8. Siguiente fase

**Fase 12** — Migraciones SQL finales + RLS audit.
- Alcance reducido por adelanto de R18: índices faltantes, verificar RLS en
  tablas de Python, trigger de purge en `audit_log` (> 90 días).
- Estimación: medio día.
