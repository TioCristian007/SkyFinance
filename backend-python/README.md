# Sky Backend Python — Scaffold Fase 0-1

## Qué es esto

Este es el scaffolding completo para la migración del backend de Sky de Node.js a Python.
Contiene las fundaciones (Fases 0 y 1 del plan de 13 fases) listas para que el equipo
empiece a construir sobre ellas.

## Qué está incluido (listo para usar)

### Core (`src/sky/core/`)
- `config.py` — Settings con pydantic-settings, fail-fast si faltan variables
- `db.py` — SQLAlchemy async engine (misma DB Supabase, cero migración de datos)
- `encryption.py` — AES-256-GCM **compatible binario con Node.js** ← CRÍTICO
- `errors.py` — Jerarquía de excepciones tipadas → HTTP status codes
- `locks.py` — Advisory locks de Postgres (reemplazo de Set() en memoria)
- `logging.py` — structlog JSON con filtro automático de PII

### Ingestion (`src/sky/ingestion/`)
- `contracts.py` — **DataSource**, **CanonicalMovement**, **build_external_id** ← EL CONTRATO
- `browser_pool.py` — Pool reutilizable de Playwright browsers
- `circuit_breaker.py` — Circuit breaker distribuido en Redis
- `routing/router.py` — IngestionRouter con failover por cadena de providers

### API (`src/sky/api/`)
- `main.py` — FastAPI app con CORS estricto en prod
- `middleware/jwt_auth.py` — Verificación JWT (resuelve P0-1)
- `deps.py` — `require_user_id` dependency

### Worker (`src/sky/worker/`)
- `main.py` — ARQ worker settings con browser pool lifecycle

### Tests
- `test_encryption_compat.py` — Roundtrip + fixtures para compatibilidad Node
- `test_contracts.py` — build_external_id determinístico

### Infra
- `docker/` — Dockerfiles para API y worker + docker-compose para dev
- `.github/workflows/ci.yml` — Lint + mypy + tests en cada PR
- `migrations/001_routing_rules.sql` — Tabla de reglas de routing

## Qué NO está incluido (fases siguientes)

- Scrapers concretos (Fase 4: `sources/bchile_scraper.py`, etc.)
- Routers FastAPI con paridad de endpoints (Fase 7)
- Dominio: Mr. Money, ARIA, finance service (Fase 8)
- ARQ jobs concretos (Fase 6)
- Observabilidad: métricas Prometheus (Fase 10)

## Primeros pasos para el equipo

```bash
# 1. Clonar y setup
git clone <nuevo-repo>
cd sky-backend-python
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Copiar env
cp .env.example .env
# Llenar con valores reales (MISMOS que el backend Node)

# 3. Instalar Playwright browsers
playwright install chromium

# 4. Correr tests
pytest tests/unit/ -v

# 5. Levantar API (sin worker todavía)
uvicorn sky.api.main:app --reload --port 8000

# 6. Verificar
curl http://localhost:8000/api/health
# → {"status":"ok","app":"sky-backend-python"}
```

## Gate bloqueante: compatibilidad de encryption

Antes de CUALQUIER otra cosa, generar fixtures de Node y verificar:

```bash
# En el backend Node actual:
node -e "
  process.env.BANK_ENCRYPTION_KEY = 'tu_clave_real';
  import('./services/encryptionService.js').then(m => {
    console.log('RUT:', m.encrypt('12345678-9'));
    console.log('PASS:', m.encrypt('test_password'));
  });
"
```

Pegar los outputs en `tests/unit/test_encryption_compat.py`, descomentar los tests,
y correr. Si pasan, Python puede descifrar credenciales existentes.
Si fallan, NO avanzar hasta resolver.

## Siguiente fase del equipo

Una vez verificada la encryption, el equipo puede empezar Fase 2-3 en paralelo:
- **Dev A**: implementar `BChileScraperSource` usando Playwright (Fase 4)
- **Dev B**: portar `categorizerService` a `src/sky/domain/categorizer.py` (Fase 8)
- **Ambos**: usar `pytest` para cada módulo nuevo

El backend Node sigue en producción sirviendo a usuarios.
Python no toca producción hasta Fase 13 (parity tests OK + cutover gradual).
