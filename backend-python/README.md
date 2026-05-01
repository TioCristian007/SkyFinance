# Sky Backend Python

Migración del backend de Sky Finance de Node.js a Python siguiendo el plan de 13 fases.

> **Estado:** Fases 0-5 cerradas. Migración en curso. **No toca producción** hasta Fase 13.
> **Stack:** Python 3.12 · FastAPI · ARQ · SQLAlchemy 2.0 async · Playwright · Redis · Supabase

---

## Qué está cerrado

### ✅ Fase 0 — Scaffolding
Estructura del repo, `pyproject.toml` con deps, dockerfiles placeholder, CI mínimo (lint + mypy + tests en cada PR).

### ✅ Fase 1 — Contrato `DataSource` y modelo canónico
Archivos: `src/sky/ingestion/contracts.py`
- `DataSource` ABC con `source_identifier`, `source_kind`, `supported_banks`, `capabilities()`, `fetch()`.
- `CanonicalMovement` (frozen dataclass) — el shape único que el dominio consume, sin saber de qué provider vino.
- `IngestionResult`, `BankCredentials`, `OAuthTokens`, `IngestionCapabilities`.
- `build_external_id(bank_id, date, amount, description)` — id determinístico SHA-256, mismo movimiento real → mismo id.

### ✅ Fase 2 — Core infrastructure
Archivos en `src/sky/core/`:
- `config.py` — `Settings` con pydantic-settings, fail-fast si falta env var crítica.
- `db.py` — SQLAlchemy 2.0 async engine sobre la misma DB Supabase del Node.
- `locks.py` — Postgres advisory locks (reemplaza `Set()` en memoria del Node).
- `logging.py` — `structlog` JSON con filtro automático de PII.
- `errors.py` — jerarquía tipada → HTTP status codes.
- `metrics.py` — registry Prometheus mínimo (Fase 10 lo expande).

### ✅ Fase 3 — Encryption compatible binario con Node
Archivo: `src/sky/core/encryption.py`
- AES-256-GCM con el mismo formato binario que `backend/services/encryptionService.js`.
- Verificado con fixtures generadas desde Node — Python descifra credenciales bancarias existentes sin migración de datos.
- `verify_encryption_ready()` corre al arranque (gate fail-fast).

### ✅ Fase 4 — Scrapers Playwright
Archivos en `src/sky/ingestion/sources/` y `src/sky/ingestion/parsers/`:
- `bchile_scraper.py` — login + 2FA app + extracción de cuentas y tarjetas. **Validado contra cuenta real**.
- `bchile_parser.py` — `normalize_date`, `parse_amount`, idempotente. 17 unit tests verde.
- `falabella_scraper.py` — **skeleton**: estructura e interfaz correcta, lógica de scraping pendiente. Lanza `RecoverableIngestionError` por ahora; el router hace skip.
- `bci_direct.py` — implementación parcial; gate end-to-end contra cuenta real **pendiente**.
- `browser_pool.py` — pool reutilizable de Playwright contexts compartido por todo el worker.

### ✅ Fase 5 — IngestionRouter, rate limiter, circuit breaker, rules en DB (cerrada 2026-04-30)
Archivos:
- `src/sky/ingestion/routing/router.py` — failover por cadena de providers, rollout %, integración con rate limiter y circuit breaker.
- `src/sky/ingestion/routing/rules.py` — lectura de `public.ingestion_routing_rules` con cache TTL en memoria. Fallback a `DEFAULT_RULES` si DB no responde y `ROUTING_RULES_DB_REQUIRED=false`.
- `src/sky/ingestion/rate_limiter.py` — sliding window log atómico (Redis sorted set + Lua script). UUID por request para evitar colisiones en mismo ms.
- `src/sky/ingestion/circuit_breaker.py` — CLOSED/OPEN/HALF_OPEN distribuido en Redis.
- `src/sky/ingestion/bootstrap.py` — `build_router(include_browser_sources)` único punto de ensamblaje. API → `False`, Worker → `True`.
- `src/sky/api/main.py` y `src/sky/worker/main.py` — wiring del router en lifespan/startup.

**Gates §3 verificados** (todos exit code 0):
- `ruff check` — 0 errores
- `mypy --strict` — 0 errores
- `pytest tests/unit/` — 64 pass + 2 skip
- Cobertura ≥85% en `routing/`, `circuit_breaker.py`, `rate_limiter.py`
- `scripts/smoke_router.py` contra Redis real — failover OK, circuit breaker abierto tras 5 fallos, rate limit (11º request bloqueado, retry_after≈60s)
- `uvicorn` arranca + `/api/health` responde `200 {"status":"ok","app":"sky-backend-python"}`
- Migración `001_routing_rules.sql` aplicada en staging y producción (8 filas)

---

## Qué falta

### 🔴 Fase 6 — Queue ARQ (siguiente)
Estado actual: `worker/jobs/sync.py`, `categorize.py`, `webhook.py`, `scheduled.py` y `worker/banking_sync.py` son archivos placeholders de 4-10 LOC.

A construir: `sync_bank_account_job` que llama al `IngestionRouter` ya listo, persiste movimientos con `INSERT ... ON CONFLICT (external_id)`, encola job de categorización. Advisory lock por cuenta para evitar syncs duplicados. Colas separadas en Redis.

### 🔴 Fase 7 — FastAPI paridad 1:1 con Node
Estado actual: 11 routers en `api/routers/*.py` son stubs de 8 LOC; 6 schemas en `api/schemas/*.py` son stubs de 4 LOC. **El JWT auth ya está implementado** (`api/middleware/jwt_auth.py`, 70 LOC) — P0-1 cerrado desde día 1.

A construir: 17 endpoints con paridad de shapes vs Node, schemas Pydantic, rate limiting, tests de paridad.

### 🔴 Fase 8 — Domain
`domain/finance.py`, `mr_money.py`, `aria.py`, `categorizer.py`, `goals.py`, `challenges.py`, `simulations.py` — todos placeholders de 6 LOC. Portar lógica del Node manteniendo paridad.

### 🔴 Fases 9-13
Scheduler ARQ cron · Observabilidad (Prometheus + tracing) · Docker prod · Migraciones SQL faltantes + índices · Parity tests + cutover gradual a Python.

Detalle completo en [`docs/MIGRATION_13_PHASES.md`](docs/MIGRATION_13_PHASES.md).

---

## Setup

### Requisitos
- Python 3.12+
- Redis (Docker recomendado: `docker run -d --rm -p 6379:6379 redis:7-alpine`)
- Cuenta Supabase con la misma DB del backend Node
- Acceso al `.env` del Node para `BANK_ENCRYPTION_KEY` (debe ser idéntica o no se podrán descifrar credenciales existentes)

### Instalación

```powershell
cd backend-python
python -m venv .venv
.venv\Scripts\activate            # Windows; Linux/Mac: source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium       # solo si vas a tocar scrapers

cp .env.example .env
# Llenar .env con valores reales (mismos que el Node)
```

### Tests

```powershell
pytest tests/unit/ -v --cov=src/sky/ingestion --cov-report=term-missing
ruff check src/sky/ingestion/ tests/
mypy src/sky/ingestion/
```

Esperado: 64 pass + 2 skip · 0 errores ruff · 0 errores mypy.

### Smoke test del IngestionRouter (requiere Redis vivo)

```powershell
docker run -d --rm -p 6379:6379 --name sky-redis-smoke redis:7-alpine
$env:REDIS_URL = "redis://localhost:6379"
python scripts/smoke_router.py
# Esperado:
#   [ok] Redis vivo
#   [ok] Failover: always_fail skipped, always_ok respondió con 1 mv(s)
#   [ok] Circuit breaker OPEN tras 5 fallos consecutivos
#   [ok] Rate limit: 10 OK, 11º bloqueado (retry_after≈60s)
#   [ok] Smoke completado
docker stop sky-redis-smoke
```

### Levantar API + Worker local

```powershell
# Terminal 1 — API
$env:REDIS_URL = "redis://localhost:6379"
uvicorn sky.api.main:app --reload --port 8000
curl http://localhost:8000/api/health
# {"status":"ok","app":"sky-backend-python"}

# Terminal 2 — Worker (Fase 6 lo activará; hoy arranca pero sin jobs registrados)
$env:REDIS_URL = "redis://localhost:6379"
arq sky.worker.main.WorkerSettings
```

---

## Convenciones técnicas

### Source identifiers
| Identifier | Capa | Estado |
|---|---|---|
| `scraper.bchile` | Playwright | ✅ Validado contra cuenta real |
| `scraper.falabella` | Playwright | 🟡 Skeleton |
| `scraper.bci` | Playwright | 🟡 Parcial |
| `mercadopago.api` | OAuth2 API | 🔴 Futuro |
| `fintoc` | Open banking aggregator | 🔴 Futuro |
| `manual` | Upload manual de archivos | 🔴 Futuro |
| `sfa` | API regulada SFA | 🔴 Futuro |

### Determinismo del `external_id`
```python
external_id = f"{bank_id}_{sha256(f'{date}|{amount}|{desc.lower()}').hexdigest()[:16]}"
```
Mismo movimiento real → mismo id → idempotencia natural en `INSERT ... ON CONFLICT`.

### Settings críticos del `.env`
- `BANK_ENCRYPTION_KEY` — DEBE ser idéntica a la del Node. Si no, no descifra credenciales existentes.
- `REDIS_URL` — Fase 5+ requiere Redis vivo en startup (`bootstrap.py` hace `redis.ping()` fail-fast).
- `ROUTING_RULES_DB_REQUIRED` — `false` por default; en prod `true` para fallar si la tabla no responde.
- `RATE_LIMIT_DEFAULT_MAX` / `RATE_LIMIT_DEFAULT_WINDOW_SEC` — defaults 10/60.
- `RATE_LIMIT_OVERRIDES` — string formato `"scraper.bchile=2/60,fintoc=30/60"`.

### Reglas de oro de la migración
- API **nunca** importa Playwright. El worker es el único con browser pool arrancado.
- `AuthenticationError` **no** dispara failover (regla del router — bloqueante).
- Rate limit es "skip", no "fail" — el siguiente provider de la cadena se intenta.
- ARIA solo escribe `aria.*` con `service_role`. Cliente nunca lee/escribe ahí.

---

## Migraciones SQL aplicadas

Ubicación: `migrations/`. Aplicadas vía Supabase SQL Editor en staging y producción.

| Migración | Aplicada | Verificación |
|---|---|---|
| `000_immediate_fixes.sql` | ✅ | Pre-Fase 5, fixes varios |
| `001_routing_rules.sql` | ✅ | `SELECT count(*) FROM public.ingestion_routing_rules` → 8 |

---

## Documentación interna

- [`docs/MIGRATION_13_PHASES.md`](docs/MIGRATION_13_PHASES.md) — plan maestro completo, archivos y gates por fase. **Fuente de verdad del estado.**
- [`docs/REMEDIATION_P0_P3.md`](docs/REMEDIATION_P0_P3.md) — deuda técnica P0-P3 mapeada a su fase de cierre.
- [`docs/FASE5_CLOSURE_PLAN.md`](docs/FASE5_CLOSURE_PLAN.md) — template del proceso de cierre por fase. Base para FASE6, FASE7, etc.
- [`../CLAUDE.md`](../CLAUDE.md) — contexto persistente para sesiones de Claude Code (root del repo).

---

*Sky Finance · backend-python · 2026-04-30*
