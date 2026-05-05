# SKY FINANCE — PLAN DE MIGRACIÓN EN 13 FASES

## Reglas del plan

- **No se avanza a la siguiente fase sin verificar la anterior.**
- **Node sigue en producción hasta Fase 13.** Python no toca tráfico real hasta el cutover.
- **Cada fase tiene un gate de verificación.** Si el gate falla, la fase no está completa.
- **El frontend NO se toca.** React sigue igual. Solo cambia el backend al que apunta `VITE_API_URL`.

---

## FASE 0 — Scaffolding del repo Python

**Objetivo:** tener un repo Python funcional donde el equipo pueda hacer `pytest` y ver verde.

**Estado:** ✅ ENTREGADO (ZIP `sky_migration_complete.zip`)

### Qué se hace
1. Crear repo `sky-backend-python` en GitHub.
2. Volcar el contenido de `02_python_scaffold/` del ZIP entregado.
3. Configurar Python 3.12, crear virtualenv.
4. Instalar dependencias: `pip install -e ".[dev]"`
5. Instalar Playwright: `playwright install chromium`
6. Copiar `.env.example` → `.env` con los valores reales (mismos del backend Node).

### Archivos que existen al terminar
```
pyproject.toml
.python-version (3.12)
.gitignore
.env.example
.github/workflows/ci.yml
src/sky/__init__.py
src/sky/core/ (config, db, encryption, errors, locks, logging)
src/sky/ingestion/ (contracts, browser_pool, circuit_breaker)
src/sky/ingestion/routing/ (router)
src/sky/api/ (main, deps, middleware/jwt_auth)
src/sky/worker/ (main)
src/sky/domain/ (vacío — Fase 8)
tests/unit/ (test_encryption_compat, test_contracts)
docker/ (api.Dockerfile, worker.Dockerfile, docker-compose.yml)
migrations/ (001_routing_rules.sql)
```

### Gate de verificación
```bash
cd sky-backend-python
pip install -e ".[dev]"
pytest tests/unit/ -v
# Resultado: 2 archivos de test, todos los tests pasan (excepto los marcados @skip)
uvicorn sky.api.main:app --port 8000
curl http://localhost:8000/api/health
# → {"status":"ok","app":"sky-backend-python"}
```

### Estimación: 1-2 horas

---

## FASE 1 — Contrato DataSource y modelo canónico

**Objetivo:** firmar el diseño core que todo el sistema usa. Es el contrato más importante del proyecto.

**Estado:** ✅ ENTREGADO (incluido en scaffold)

### Qué se hace
1. Revisar `src/sky/ingestion/contracts.py` con todo el equipo.
2. Validar que `build_external_id` es determinístico y compatible con lo que Node produce.
3. Validar que `CanonicalMovement` tiene todos los campos que el dominio necesita.
4. Si falta algo, enriquecer el modelo AHORA — después de Fase 4 cambiarlo es caro.

### Archivos clave
```
src/sky/ingestion/contracts.py  ← DataSource, CanonicalMovement, build_external_id
                                   SourceKind, AuthMode, MovementSource
                                   IngestionResult, IngestionCapabilities
                                   BankCredentials, OAuthTokens
                                   Excepciones: AuthenticationError, RecoverableIngestionError, etc.
```

### Gate de verificación
```bash
pytest tests/unit/test_contracts.py -v
# Todos pasan. build_external_id es determinístico y case-insensitive.
```

### Decisión doctrinal que se firma aquí
> Nada en `sky.domain` puede importar desde `sky.ingestion.sources`.
> El dominio solo consume `CanonicalMovement`. Si necesita saber de qué fuente
> vino, el modelo está incompleto.

### Estimación: medio día (es revisión + ajustes, no escritura desde cero)

---

## FASE 2 — Core infrastructure

**Objetivo:** las fundaciones compartidas que API y worker necesitan están listas y testeadas.

### Qué se hace
1. Verificar que `config.py` carga todas las variables necesarias. Agregar las que falten.
2. Configurar `DATABASE_URL` en `.env` apuntando a la DB de Supabase directamente (formato `postgresql+asyncpg://...`).
3. Verificar que `db.py` puede conectarse y hacer un SELECT simple.
4. Verificar que `logging.py` produce JSON limpio y filtra PII.
5. Verificar que `locks.py` funciona contra Postgres real.
6. Agregar tests para cada módulo.

### Archivos que se crean o modifican
```
src/sky/core/config.py      ← revisar, agregar variables faltantes
src/sky/core/db.py           ← verificar conexión real
src/sky/core/logging.py      ← ya listo
src/sky/core/errors.py       ← ya listo
src/sky/core/locks.py        ← testear contra DB real
tests/unit/test_config.py    ← NUEVO
tests/unit/test_logging.py   ← NUEVO
tests/integration/test_db.py ← NUEVO (requiere DB real)
```

### Gate de verificación
```bash
pytest tests/unit/ tests/integration/test_db.py -v
# Todos pasan. La conexión a Supabase funciona.
```

```python
# Test manual en Python REPL:
from sky.core.db import get_session
async with get_session() as s:
    result = await s.execute(text("SELECT count(*) FROM profiles"))
    print(result.scalar())  # debe devolver un número ≥ 0
```

### Estimación: 1-2 días

---

## FASE 3 — EncryptionService compatible binario con Node

**Objetivo:** Python puede descifrar credenciales que Node cifró. GATE BLOQUEANTE.

### Por qué es bloqueante
Los usuarios existentes tienen RUT y password cifrados por Node.js con AES-256-GCM.
Esos ciphertexts están en `bank_accounts.encrypted_rut` y `encrypted_pass`.
Si Python no puede descifrarlos, no puede hacer login en los bancos → no hay sync → no hay producto.

### Qué se hace
1. En el backend Node actual, generar fixtures de test:
```javascript
process.env.BANK_ENCRYPTION_KEY = "tu_clave_real_de_produccion";
const { encrypt } = await import('./services/encryptionService.js');
console.log("FIXTURE_RUT:", encrypt("12345678-9"));
console.log("FIXTURE_PASS:", encrypt("mi_clave_test_2026"));
```
2. Pegar los outputs en `tests/unit/test_encryption_compat.py`.
3. Descomentar los tests `test_decrypt_node_rut` y `test_decrypt_node_password`.
4. Correr: `pytest tests/unit/test_encryption_compat.py -v`
5. Si pasan → compatibilidad binaria verificada.
6. Si fallan → debuggear hasta que pasen. NO avanzar sin esto.

### Archivos
```
src/sky/core/encryption.py                    ← ya listo
tests/unit/test_encryption_compat.py          ← agregar fixtures reales
scripts/verify_encryption_compat.py           ← NUEVO (script standalone)
```

### Script de verificación standalone
```python
# scripts/verify_encryption_compat.py
"""
Correr con: python scripts/verify_encryption_compat.py
Verifica que Python descifra tokens producidos por Node.
"""
import sys
from sky.core.encryption import decrypt
from sky.core.config import settings

# Pegar un token real de bank_accounts.encrypted_rut de Supabase:
NODE_TOKEN = "PEGAR_AQUI"
EXPECTED_PLAINTEXT = "RUT_ESPERADO"

try:
    result = decrypt(NODE_TOKEN, settings.bank_encryption_key)
    if result == EXPECTED_PLAINTEXT:
        print(f"✅ Compatibilidad verificada: '{result}'")
        sys.exit(0)
    else:
        print(f"❌ Decrypt OK pero valor distinto: got '{result}', expected '{EXPECTED_PLAINTEXT}'")
        sys.exit(1)
except Exception as e:
    print(f"❌ Decrypt falló: {e}")
    sys.exit(1)
```

### Gate de verificación
```bash
pytest tests/unit/test_encryption_compat.py -v
# TODOS los tests pasan, incluyendo los de fixtures de Node.
python scripts/verify_encryption_compat.py
# ✅ Compatibilidad verificada
```

**Si este gate falla, STOP. No avanzar a Fase 4.**

### Estimación: 1 día (generar fixtures + debug si falla)

---

## FASE 4 — BChileScraperSource con Playwright + browser pool

**Objetivo:** el primer DataSource operativo. Hace lo mismo que el scraper Node actual pero con Playwright Python.

### Qué se hace
1. Implementar `BChileScraperSource` que implementa el contrato `DataSource`.
2. Usa `browser_pool.py` para adquirir un contexto de browser.
3. Replica el flujo exacto del scraper Node: login → 2FA → navegación → extracción de movimientos.
4. Devuelve `IngestionResult` con `CanonicalMovement[]`.
5. Implementar también `FalabellaScraperSource` (más simple, sin 2FA).
6. Testear con cuentas reales.

### Archivos
```
src/sky/ingestion/sources/__init__.py          ← registry de sources
src/sky/ingestion/sources/bchile_scraper.py    ← NUEVO
src/sky/ingestion/sources/falabella_scraper.py ← NUEVO
src/sky/ingestion/parsers/bchile_parser.py     ← NUEVO (parsing de HTML/tablas)
src/sky/ingestion/parsers/falabella_parser.py  ← NUEVO
tests/integration/test_bchile_scraper.py       ← NUEVO (@skip sin creds)
```

### Estructura de un DataSource concreto
```python
# src/sky/ingestion/sources/bchile_scraper.py
class BChileScraperSource(DataSource):
    @property
    def source_identifier(self) -> str:
        return "scraper.bchile"

    @property
    def source_kind(self) -> SourceKind:
        return SourceKind.SCRAPER

    @property
    def supported_banks(self) -> list[str]:
        return ["bchile"]

    def capabilities(self) -> IngestionCapabilities:
        return IngestionCapabilities(
            typical_latency_ms=180_000,  # 3 min con 2FA
            estimated_failure_rate=0.15,
            supports_backfill=True,
            backfill_days=90,
        )

    async def fetch(self, bank_id, credentials, *, on_progress=None):
        pool = get_browser_pool()
        async with pool.acquire() as context:
            page = await context.new_page()
            # ... login, 2FA, scrape, parse ...
            movements = parse_movements(raw_table_data)
            return IngestionResult(
                balance=AccountBalance(balance_clp=..., as_of=...),
                movements=[...],  # list[CanonicalMovement]
                source_kind=SourceKind.SCRAPER,
                source_identifier="scraper.bchile",
            )
```

### Gate de verificación
```bash
# Test con cuenta real (manual, con dev presente):
python -c "
import asyncio
from sky.ingestion.sources.bchile_scraper import BChileScraperSource
from sky.ingestion.contracts import BankCredentials
from sky.ingestion.browser_pool import get_browser_pool

async def test():
    pool = get_browser_pool()
    await pool.start()
    source = BChileScraperSource()
    result = await source.fetch('bchile', BankCredentials(rut='...', password='...'))
    print(f'Balance: {result.balance}')
    print(f'Movements: {len(result.movements)}')
    for m in result.movements[:3]:
        print(f'  {m.occurred_at} | {m.amount_clp} | {m.raw_description}')
    await pool.stop()

asyncio.run(test())
"
# Debe mostrar balance real y movimientos reales.
```

### Estimación: 1-2 semanas (scraping es inherentemente laborioso)

---

## FASE 5 — IngestionRouter, circuit breaker, rate limiter

**Objetivo:** el router de ingesta con failover automático está operativo.

### Estado: ✅ Cerrada (2026-04-29)

### Archivos finales
```
src/sky/ingestion/rate_limiter.py              (sliding window log Redis — reescrito)
src/sky/ingestion/routing/rules.py             (lectura DB + cache TTL — reescrito)
src/sky/ingestion/routing/router.py            (con rate limiter inyectado)
src/sky/ingestion/sources/__init__.py          (factory build_all_sources)
src/sky/ingestion/bootstrap.py                 (ensamble único — NUEVO)
src/sky/core/config.py                         (settings rate_limit_* y routing_rules_*)
src/sky/api/main.py                            (wiring bootstrap en lifespan)
src/sky/worker/main.py                         (wiring bootstrap en startup/shutdown)
tests/unit/test_rate_limiter.py                (7 casos)
tests/unit/test_circuit_breaker.py             (7 casos)
tests/unit/test_routing_rules.py               (7 casos)
tests/unit/test_router.py                      (10 casos + 1 extra = 11)
tests/conftest.py                              (fixtures fake_redis, rate_limiter, cb_config)
scripts/smoke_router.py                        (gate humano contra Redis real — NUEVO)
migrations/001_routing_rules.sql               (sin cambios — ya listo)
```

### Gates verificados
- [x] `pytest tests/unit/ -v` → todos pasan (≥ 31 casos nuevos)
- [x] `pytest --cov=src/sky/ingestion --cov-report=term-missing` ≥ 85%
- [x] `mypy src/sky/ingestion/` → 0 errores
- [x] `ruff check src/sky/ingestion/ tests/` → 0 errores
- [x] `scripts/smoke_router.py` corrió contra Redis local con éxito
- [x] `uvicorn sky.api.main:app` arranca con bootstrap wired
- [x] `api/main.py` y `worker/main.py` usan `build_router()` de `ingestion.bootstrap`

### Doctrina confirmada
- `AuthenticationError` no dispara failover (implementado en router.py)
- `rate_limit` es "skip" (acumula en `errors`), no "fail"
- API nunca importa Playwright (`include_browser_sources=False`)
- Credenciales nunca se logean

### Estimación: 3-5 días

---

## FASE 6 — Queue system con ARQ

**Objetivo:** los syncs corren como jobs encolados, no como funciones inline.

### Qué se hace
1. Implementar `sync_bank_account_job` en `worker/jobs/sync.py`.
2. Implementar `categorize_pending_job` en `worker/jobs/categorize.py`.
3. Configurar colas separadas: `queue:scraper:sync`, `queue:categorization`.
4. El API encola jobs con `await arq_pool.enqueue_job(...)`, nunca ejecuta sync inline.
5. Advisory lock en cada job para evitar syncs duplicados.
6. Verificar con Redis local que los jobs se procesan correctamente.

### Archivos
```
src/sky/worker/main.py                     ← modificar (registrar jobs)
src/sky/worker/jobs/sync.py                ← NUEVO
src/sky/worker/jobs/categorize.py          ← NUEVO
src/sky/worker/banking_sync.py             ← NUEVO (orquestador con advisory lock)
tests/integration/test_sync_job.py         ← NUEVO
```

### Flujo objetivo
```
Frontend click "Actualizar"
    → POST /api/banking/sync/:id
    → API encola job: arq_pool.enqueue_job("sync_bank_account", account_id, user_id)
    → Responde inmediato: {"started": true}

Worker recibe job
    → Adquiere advisory lock
    → Descifra credenciales
    → Llama IngestionRouter.ingest()
    → Inserta movimientos con categorization_status='pending'
    → Encola job de categorización
    → Actualiza bank_accounts con balance y status

Worker recibe job de categorización
    → Procesa cola de pendientes (3 capas)
    → Actualiza transactions con categoría real
```

### Gate de verificación
```bash
# Levantar worker + Redis localmente:
docker compose -f docker/docker-compose.yml up redis -d
arq sky.worker.main.WorkerSettings &

# Encolar job manualmente:
python -c "
import asyncio
from arq import create_pool
from arq.connections import RedisSettings

async def test():
    pool = await create_pool(RedisSettings())
    job = await pool.enqueue_job('sync_bank_account', 'account_id_test', 'user_id_test')
    print(f'Job encolado: {job.job_id}')

asyncio.run(test())
"
# Worker debe procesar el job y logearlo.
```

### Estado: ✅ Cerrada (2026-05-04)

Archivos finales:
- `src/sky/domain/categorizer.py`             (3 capas: regex + cache + Claude Haiku)
- `src/sky/worker/banking_sync.py`            (orquestador con advisory lock)
- `src/sky/worker/jobs/sync.py`               (sync_bank_account_job, sync_all_user_accounts_job)
- `src/sky/worker/jobs/categorize.py`         (categorize_pending_job)
- `src/sky/worker/main.py`                    (registra functions + arq_pool en ctx)
- `src/sky/api/main.py`                       (arq_pool en app.state)
- `src/sky/api/routers/banking.py`            (POST /api/banking/sync/:id, /sync-all)
- `src/sky/api/schemas/banking.py`
- `src/sky/core/locks.py`                     (try_advisory_lock async)
- `migrations/002_indexes_and_constraints.sql`
- `tests/unit/test_categorizer.py`            (35 casos: regex + _key_variants + _lookup_cache + _save_to_cache + _categorize_with_ai)
- `tests/unit/test_advisory_lock.py`         (6 casos: _key_from_string + try_advisory_lock acquired/not/exception)
- `tests/unit/test_sync_job.py`              (15 casos: success + auth error + all-sources-failed + helpers + job wrappers)
- `tests/unit/test_categorize_job.py`        (4 casos: empty + proceso + fallback + db error)
- `tests/integration/test_sync_job.py`       (gate manual con cuenta real — skip si no hay creds)

Bugs cerrados: BUG-1 (external_id determinístico), BUG-2 (UNIQUE INDEX),
BUG-3 (advisory lock), BUG-4 (browser pool paralelo).

Gates verificados:
- [x] `pytest tests/ -v`                    → 131 passed, 1 skipped
- [x] coverage domain/categorizer.py        → 99%
- [x] coverage worker/banking_sync.py       → 95%
- [x] coverage worker/jobs/categorize.py    → 100%
- [x] coverage worker/jobs/sync.py          → 100%
- [x] coverage core/locks.py               → 100%
- [x] `mypy src/sky/`                       → 0 errores (70 archivos)
- [x] `ruff check src/sky/ tests/`          → 0 errores
- [ ] migración 002 aplicada en staging y prod (gate manual — pendiente usuario)
- [ ] arq sky.worker.main.WorkerSettings  → arranca limpio (gate manual)
- [ ] sync end-to-end con cuenta real (gate manual)

---

## FASE 7 — FastAPI con paridad 1:1 de endpoints Node

**Objetivo:** todos los endpoints del backend Node existen en Python y responden con el mismo shape.

### Qué se hace
1. Implementar cada router con exacta paridad de rutas y response shapes:
   - `/api/health` — ya listo
   - `/api/summary` — GET
   - `/api/transactions` — GET, POST, DELETE
   - `/api/chat` — POST
   - `/api/goals` — GET, POST, PATCH, DELETE
   - `/api/challenges` — GET, POST (activate, complete)
   - `/api/simulate` — POST
   - `/api/banking/accounts` — GET
   - `/api/banking/banks` — GET
   - `/api/banking/connect` — POST
   - `/api/banking/sync/:id` — POST
   - `/api/banking/sync-all` — POST
   - `/api/banking/accounts/:id` — DELETE
   - `/api/internal/scheduled-sync` — POST
   - `/api/internal/process-queue` — POST
   - `/api/internal/queue-depth` — GET
2. Crear Pydantic schemas para request/response de cada endpoint.
3. JWT auth verificado en TODOS los endpoints (excepto health e internal).
4. Rate limiting en endpoints sensibles.

### Archivos
```
src/sky/api/routers/health.py          ← NUEVO
src/sky/api/routers/summary.py         ← NUEVO
src/sky/api/routers/transactions.py    ← NUEVO
src/sky/api/routers/chat.py            ← NUEVO
src/sky/api/routers/goals.py           ← NUEVO
src/sky/api/routers/challenges.py      ← NUEVO
src/sky/api/routers/simulate.py        ← NUEVO
src/sky/api/routers/banking.py         ← NUEVO
src/sky/api/routers/internal.py        ← NUEVO
src/sky/api/schemas/summary.py         ← NUEVO
src/sky/api/schemas/transactions.py    ← NUEVO
src/sky/api/schemas/chat.py            ← NUEVO
src/sky/api/schemas/goals.py           ← NUEVO
src/sky/api/schemas/challenges.py      ← NUEVO
src/sky/api/schemas/banking.py         ← NUEVO
src/sky/api/middleware/rate_limit.py    ← NUEVO
src/sky/api/main.py                    ← modificar (montar routers)
```

### Gate de verificación
```bash
# Levantar Python API:
uvicorn sky.api.main:app --port 8000

# Comparar con Node:
# Para cada endpoint, verificar que el response JSON tiene el mismo shape.
# Script de parity (tests/parity/test_endpoint_parity.py):
curl http://localhost:3001/api/summary -H "x-user-id: TEST_UUID" > /tmp/node.json
curl http://localhost:8000/api/summary -H "Authorization: Bearer TEST_JWT" > /tmp/python.json
diff <(jq -S . /tmp/node.json) <(jq -S . /tmp/python.json)
# Diferencias = 0 en los campos que el frontend consume.
```

### P0-1 se cierra aquí
El middleware JWT está activo desde el primer endpoint. No hay header `x-user-id` en Python. Auth verificada criptográficamente.

### Estimación: 2-3 semanas (la fase más larga)

---

## FASE 8 — Dominio: Mr. Money, ARIA, finance service

**Objetivo:** la lógica de negocio completa portada a Python.

### Qué se hace
1. Portar `financeService.js` → `domain/finance.py` (summary, balance, tasas, badges).
2. Portar `aiService.js` → `domain/mr_money.py` (detección local + Claude con tools).
3. Portar `ariaService.js` → `domain/aria.py` (pipeline anonimización con consent estricto).
4. Portar `categorizerService.js` → `domain/categorizer.py` (3 capas).
5. Portar challenges y simulaciones.

### Archivos
```
src/sky/domain/finance.py        ← NUEVO
src/sky/domain/mr_money.py       ← NUEVO
src/sky/domain/aria.py           ← NUEVO (con guard estricto — P0-2 cerrado)
src/sky/domain/categorizer.py    ← NUEVO
src/sky/domain/goals.py          ← NUEVO
src/sky/domain/challenges.py     ← NUEVO
src/sky/domain/simulations.py    ← NUEVO
tests/unit/test_categorizer.py   ← NUEVO (golden cases)
tests/unit/test_aria.py          ← NUEVO (invariantes de anonimización)
tests/unit/test_finance.py       ← NUEVO
```

### Regla doctrinal
- `domain/aria.py`: guard `if not user_id or not await has_aria_consent(user_id): return` en TODAS las funciones track*. Sin excepciones.
- `domain/mr_money.py`: system prompt idéntico al de Node. Claude tools idénticas. Mr. Money guía, no decide.
- Ningún archivo en `domain/` importa desde `ingestion/sources/`.

### Gate de verificación
```bash
pytest tests/unit/test_categorizer.py tests/unit/test_aria.py tests/unit/test_finance.py -v
# Todos pasan.
```

Test manual: conversar con Mr. Money vía Python API y verificar que las respuestas son coherentes con las del backend Node.

### Estimación: 2 semanas

---

## FASE 9 — Scheduler como ARQ cron

**Objetivo:** el cron de auto-sync corre como cron nativo de ARQ, no como script externo.

### Qué se hace
1. Implementar `scheduled_sync_job` en `worker/jobs/scheduled.py`.
2. Registrar como ARQ cron en `worker/main.py`.
3. Incluir backoff exponencial (misma lógica que `schedulerService.js` de Node).
4. Verificar que cada hora sincroniza cuentas elegibles.

### Archivos
```
src/sky/worker/jobs/scheduled.py   ← NUEVO
src/sky/worker/main.py             ← modificar (agregar cron)
```

### Gate de verificación
El worker logea cada hora:
```
[scheduler] tick start
[scheduler] 2 candidatos → 2 due → 2 a procesar
[sync] completado en ...
[scheduler] tick done — 2 OK, 0 fail
```

### Estimación: 2-3 días

---

## FASE 10 — Observabilidad: métricas + tracing + healthchecks

**Objetivo:** el equipo puede ver qué pasa en producción sin leer logs manualmente.

### Qué se hace
1. Instrumentar métricas Prometheus en endpoints clave:
   - `sky_sync_duration_seconds` (histogram, labels: bank_id, source_kind)
   - `sky_sync_total` (counter, labels: bank_id, status=success|error)
   - `sky_queue_depth` (gauge)
   - `sky_circuit_breaker_state` (gauge, labels: source_id)
   - `sky_api_request_duration_seconds` (histogram, labels: endpoint)
2. Health check profundo: `/api/health/deep` que verifica DB + Redis + Anthropic.
3. Integrar Sentry para errores.
4. Trace ID por request (ya preparado en structlog).

### Archivos
```
src/sky/core/metrics.py              ← NUEVO
src/sky/api/routers/health.py        ← modificar (agregar /deep)
src/sky/api/middleware/tracing.py     ← NUEVO
```

### Gate de verificación
```bash
curl http://localhost:8000/metrics
# Devuelve métricas en formato Prometheus.
curl http://localhost:8000/api/health/deep
# {"status":"ok","db":"ok","redis":"ok","anthropic":"ok"}
```

### Estimación: 3-5 días

---

## FASE 11 — Dockerización y despliegue

**Objetivo:** los servicios Python están deployados en Railway (o equivalente), accesibles pero sin tráfico real.

### Qué se hace
1. Verificar que `docker/api.Dockerfile` y `docker/worker.Dockerfile` buildean correctamente.
2. Deployar en Railway como servicios NUEVOS (no reemplazar los de Node):
   - `sky-api-python` — FastAPI, puerto 8000
   - `sky-worker-python` — ARQ worker
   - `sky-redis` — Redis (si Railway lo soporta, o Redis Cloud free tier)
3. Configurar variables de entorno (mismas que Node + `REDIS_URL` + `DATABASE_URL`).
4. Verificar que `/api/health` responde en el servicio Python.
5. **NO apuntar `api.skyfinanzas.com` a Python todavía.** Dar un dominio temporal tipo `api-python.skyfinanzas.com` o usar el dominio de Railway.

### Archivos
```
docker/api.Dockerfile          ← ya listo
docker/worker.Dockerfile       ← ya listo
docker/docker-compose.yml      ← ya listo
```

### Gate de verificación
```bash
curl https://sky-api-python-production.up.railway.app/api/health
# {"status":"ok","app":"sky-backend-python"}
```

### Estimación: 1-2 días

---

## FASE 12 — Migraciones SQL e índices faltantes

**Objetivo:** la base de datos tiene todos los índices y constraints que el código Python necesita.

### Qué se hace
1. Crear y correr migración: `UNIQUE INDEX uniq_tx_identity ON transactions (user_id, bank_account_id, external_id)` — cierra BUG-2 definitivamente.
2. Crear tabla `ingestion_routing_rules` si no existe (migración 001 del scaffold).
3. Crear tabla `bank_tokens` para OAuth futuro (Fintoc).
4. Verificar que todos los índices de performance existen.
5. Verificar que RLS está activo en todas las tablas nuevas.

### Archivos
```
migrations/001_routing_rules.sql               ← ya listo
migrations/002_indexes_and_constraints.sql      ← NUEVO
migrations/003_webhook_events_seen.sql          ← NUEVO (futuro)
migrations/004_bank_tokens.sql                  ← NUEVO (futuro)
```

### Gate de verificación
```sql
-- En Supabase SQL Editor:
SELECT indexname FROM pg_indexes
 WHERE tablename = 'transactions'
   AND indexname LIKE 'uniq_%';
-- Debe devolver: uniq_tx_identity

SELECT tablename FROM information_schema.tables
 WHERE table_schema = 'public'
   AND table_name = 'ingestion_routing_rules';
-- Debe devolver 1 fila.
```

### Estimación: medio día

---

## FASE 13 — Parity tests y cutover gradual

**Objetivo:** Python reemplaza a Node en producción sin que el usuario note diferencia.

### Qué se hace

#### Paso 1: Parity tests (1 semana)
1. Implementar `tests/parity/test_endpoint_parity.py`.
2. Para cada endpoint: llamar Node y Python con el mismo input, comparar responses.
3. Diferencias aceptables: timestamps, IDs generados, orden de arrays.
4. Diferencias NO aceptables: campos faltantes, tipos distintos, valores de negocio distintos.
5. **100% de endpoints deben pasar parity.** Si uno falla, no se hace cutover.

#### Paso 2: Canary (2-3 días)
1. En Squarespace DNS, crear `api-v2.skyfinanzas.com` → servicio Python de Railway.
2. En el frontend, agregar feature flag: si el usuario está en lista de canary, `VITE_API_URL` apunta a `api-v2`.
3. Testers internos usan Python durante 48h. Monitorear métricas y errores.

#### Paso 3: Cutover gradual (1 semana)
1. **10%**: cambiar 10% del tráfico a Python (vía load balancer de Railway o DNS weighted).
2. Monitorear 24h. Si hay errores, rollback inmediato.
3. **50%**: subir a 50%. Monitorear 24h.
4. **100%**: todo el tráfico a Python.
5. Cambiar `api.skyfinanzas.com` de Node a Python.

#### Paso 4: Decomisión de Node (después de 2 semanas estables)
1. Mantener Node apagado pero deployable durante 2 semanas.
2. Si Python falla en producción, rollback = cambiar DNS de vuelta a Node (<5 min).
3. Después de 2 semanas sin incidentes, archivar repo Node.

### Archivos
```
tests/parity/test_endpoint_parity.py   ← NUEVO
scripts/run_parity.sh                  ← NUEVO (automatiza comparación)
```

### Gate de verificación
```
✅ 100% parity tests pasan
✅ 48h de canary sin errores
✅ 24h al 50% sin errores
✅ 24h al 100% sin errores
✅ Rollback verificado (DNS switch < 5 min)
```

### Estimación: 2-3 semanas

---

## RESUMEN DE ESTIMACIONES

| Fase | Contenido | Estimación | Acumulado |
|------|-----------|------------|-----------|
| 0 | Scaffolding | 1-2h | 1-2h |
| 1 | Contrato DataSource | medio día | 1 día |
| 2 | Core infrastructure | 1-2 días | 3 días |
| 3 | Encryption compatible | 1 día | 4 días |
| 4 | Scrapers Playwright | 1-2 semanas | 2.5 semanas |
| 5 | Router + circuit breaker | 3-5 días | 3.5 semanas |
| 6 | Queue ARQ | 1 semana | 4.5 semanas |
| 7 | FastAPI endpoints | 2-3 semanas | 7 semanas |
| 8 | Dominio (Mr. Money, ARIA) | 2 semanas | 9 semanas |
| 9 | Scheduler ARQ | 2-3 días | 9.5 semanas |
| 10 | Observabilidad | 3-5 días | 10.5 semanas |
| 11 | Docker + deploy | 1-2 días | 11 semanas |
| 12 | Migraciones SQL | medio día | 11 semanas |
| 13 | Parity + cutover | 2-3 semanas | 13-14 semanas |

**Total estimado: 13-14 semanas con equipo dedicado.**

Con un equipo de 2 devs trabajando en paralelo (uno en ingestion/scrapers, otro en dominio/API), se puede comprimir a **8-10 semanas**.

---

## PARALELISMO POSIBLE

```
Semana 1-2:   Fases 0-3 (secuencial, fundaciones)
Semana 3-5:   Fase 4 (Dev A: scrapers) + Fase 8 parte 1 (Dev B: categorizer, finance)
Semana 5-7:   Fase 5-6 (Dev A: router, queue) + Fase 8 parte 2 (Dev B: Mr. Money, ARIA)
Semana 7-9:   Fase 7 (ambos: endpoints, schemas)
Semana 9-10:  Fases 9-10-11-12 (infra, ambos)
Semana 10-13: Fase 13 (parity + cutover, ambos)
```

---

## RIESGO #1 QUE PUEDE MATAR EL PLAN

**Scope creep durante la migración.** Si en la semana 5 alguien dice "ya que estamos reescribiendo, agreguemos también X", el plan se extiende indefinidamente. La regla es: **paridad primero, features después.** Python debe hacer exactamente lo mismo que Node antes de hacer algo nuevo. Cualquier feature nuevo se agrega DESPUÉS del cutover.
