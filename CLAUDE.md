# CLAUDE.md — Sky Finance

> Contexto persistente para sesiones de Claude Code en este monorepo.
> Léelo antes de tocar nada. Mantenlo conciso. Si algo cambia de fondo, actualízalo.

---

## Doctrina inviolable

1. **Frontend NUNCA llama a Anthropic ni a Supabase con `service_role`.** Solo llama al backend (Node hoy, Python en migración).
2. **`SUPABASE_SERVICE_KEY` y `BANK_ENCRYPTION_KEY` solo en backend.** Nunca en frontend, repo, ni logs.
3. **Credenciales bancarias = AES-256-GCM con IV único** (formato compatible binario Node ↔ Python). Nunca en plaintext en disk/logs/responses.
4. **API Python NUNCA importa Playwright.** El worker es el único con browser pool arrancado.
5. **`AuthenticationError` jamás dispara failover** del `IngestionRouter`. Es bloqueante, propaga al usuario.
6. **Rate limit es `skip`, no `fail`** en el router — si un provider está rate-limited, el router intenta el siguiente.
7. **ARIA solo escribe analytics anónimos** y solo si `aria_consent = true`. Sin UUID en `aria.*`. Service_role exclusivo.
8. **`sky.domain` no pregunta de qué `source` vino un movimiento** — `contracts.py` lo enforza.
9. **`AuthMode.PASSWORD` es un literal de tipo, no un secreto** (silenciar S105/S106 si ruff lo detecta como falso positivo).
10. **Git**: nunca `--force` push a main. PRs los maneja el usuario desde su terminal. Solo commit local desde Claude.
11. **No commitear**: secretos, `.env*` (excepto `.env.example`), `.claude/`, `node_modules/`, `dist/`, `.venv/`.

---

## Stack y arquitectura

Monorepo. Tres patas:

| Carpeta | Rol | Estado |
|---|---|---|
| `backend/` | Node.js + Express, vivo en producción sirviendo usuarios reales | ✅ Estable |
| `backend-python/` | Python 3.12 + FastAPI + ARQ + Playwright. Migración. **No toca prod** hasta Fase 13. | 🟡 En curso (Fases 0-5 cerradas) |
| `frontend/` | React + Vite. Solo consume el backend. | ✅ Estable |

DB compartida: Supabase Postgres. Esquemas `public` (RLS) y `aria` (analytics, service_role only).

Regla de oro:
```
Frontend  → solo muestra, captura y llama al backend
Backend   → calcula, decide, guarda, llama a la IA
IA        → solo desde el backend, nunca desde el browser
ARIA      → solo escribe analytics anónimos
Cifrado   → solo el backend conoce BANK_ENCRYPTION_KEY
```

---

## Mapa del repo

```
sky_OFFICIAL/
├── backend/                     ← Node.js prod (no migrar a la ligera)
├── backend-python/              ← FOCO ACTIVO de migración
│   ├── src/sky/
│   │   ├── core/                ← config, db, encryption, locks, logging, errors, metrics
│   │   ├── ingestion/           ← Fase 4-5 ✅ (router + scrapers + rate limit + CB + rules DB)
│   │   │   ├── routing/         ← router.py, rules.py
│   │   │   ├── sources/         ← bchile_scraper, falabella_scraper (skeleton), bci_direct (parcial)
│   │   │   └── parsers/         ← bchile_parser
│   │   ├── api/                 ← FastAPI; main + jwt_auth ✅; routers/* y schemas/* STUBS hasta Fase 7
│   │   ├── worker/              ← ARQ; main ✅; jobs/* y banking_sync STUBS hasta Fase 6
│   │   └── domain/              ← Mr. Money, ARIA, finance, categorizer — STUBS hasta Fase 8
│   ├── tests/                   ← unit (verde) + integration (vacío) + parity (vacío)
│   ├── scripts/                 ← smoke_router, test_bchile_scraper, test_bci_scraper, verify_encryption_compat
│   ├── migrations/              ← 000_immediate_fixes.sql, 001_routing_rules.sql
│   ├── docs/
│   │   ├── MIGRATION_13_PHASES.md     ← plan maestro (fuente de verdad del estado de fases)
│   │   ├── REMEDIATION_P0_P3.md       ← deuda P0-P3 → fase donde se cierra
│   │   └── FASE5_CLOSURE_PLAN.md      ← template del proceso de cierre por fase
│   ├── pyproject.toml           ← deps + ruff + mypy + pytest config
│   ├── ruff.toml                ← per-file-ignores (scrapers ↔ E501, SIM105)
│   └── mypy.ini                 ← per-module overrides (scrapers + browser_pool)
└── frontend/                    ← React app
```

**Fuente de verdad del estado de fases**: `backend-python/docs/MIGRATION_13_PHASES.md`. NO duplicar el estado en otros docs — leer ese cuando lo necesites.

---

## Convenciones técnicas

### Python
- `from __future__ import annotations` en todos los archivos.
- `StrEnum` (3.11+) en vez de `(str, Enum)`. Importar `from enum import StrEnum`.
- Async-first: SQLAlchemy 2.0 async, `redis.asyncio`, FastAPI native async, ARQ.
- `structlog` con context binding. Nunca `print`.
- Excepciones tipadas en `sky.core.errors`. NO crear duplicados (revisar antes de crear).
- `pydantic-settings` (`Settings` clase) para config; fail-fast si falta env var crítica.
- `dataclass(frozen=True, slots=True)` para value objects inmutables.
- Sin `# type: ignore` salvo cuando mypy genuinamente no puede inferir; ruff `UP037` los detecta sobrantes.

### Tests
- `pytest` con `asyncio_mode=auto` (configurado en pyproject). Sin `@pytest.mark.asyncio` en cada test.
- `fakeredis[lua]>=2.26` para Redis en tests. Fixture `fake_redis` ya disponible en `conftest.py`.
- `@pytest.fixture(autouse=True)` para resetear estado global (ej. cache de rules).
- Nunca `time.sleep` en tests async — usa `await asyncio.sleep`.
- Para timing tests del circuit breaker: `await asyncio.sleep ≥ 1.0s`. Nunca `< 1.0s`.
- Variables dummy de Supabase en `conftest.py` con `os.environ.setdefault(...)` ANTES de cualquier import de `sky.*`.

### Naming y formatos
- Source identifiers: `<provider>.<bank>` para scrapers/aggregators, `<provider>` solo si es API global.
  - `scraper.bchile`, `scraper.falabella`, `scraper.bci`, `mercadopago.api`, `fintoc`, `manual`, `sfa`.
- `external_id` de movimientos: `<bank_id>_<16-char-hex>`, donde el hex es `sha256(date|amount|desc.lower())[:16]`. Determinístico — mismo movimiento real produce mismo id.
- Redis keys con namespace separado: `rl:<source_id>` rate limit, `cb:<source_id>` circuit breaker.
- Commit messages al cerrar fase: español, formato del plan correspondiente. Ej: `Fase 5 cerrada: IngestionRouter con rate limit, circuit breaker, rules en DB`.

---

## Comandos comunes

### Setup (una vez)
```powershell
cd backend-python
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -e ".[dev]"
playwright install chromium
```

### Loop de desarrollo
```powershell
# Activar venv
.venv\Scripts\activate

# Tests + lint + type check
pytest tests/unit/ -v --cov=src/sky/ingestion --cov-report=term-missing
ruff check src/sky/ingestion/ tests/
mypy src/sky/ingestion/

# Smoke test contra Redis real
docker run -d --rm -p 6379:6379 --name sky-redis-smoke redis:7-alpine
$env:REDIS_URL = "redis://localhost:6379"
python scripts/smoke_router.py
docker stop sky-redis-smoke
```

### Levantar el stack Python (dev)
```powershell
$env:REDIS_URL = "redis://localhost:6379"
uvicorn sky.api.main:app --reload --port 8000
# Worker (cuando Fase 6 esté implementada):
arq sky.worker.main.WorkerSettings
```

### PowerShell vs bash
- PowerShell: `$env:VAR = "valor"` (no `VAR=valor cmd` estilo bash).
- PowerShell: `;` en vez de `&&` para chaining; o usar `if ($?) { ... }`.
- Heredoc para multilínea: usar `@'...'@` (single-quoted, literal). El cierre `'@` debe estar en columna 0.

---

## Cierre de fase — proceso estándar

Cada fase nueva sigue este patrón:

1. **Plan**: crear `docs/FASE<N>_CLOSURE_PLAN.md` usando `FASE5_CLOSURE_PLAN.md` como template.
2. **Implementación**: por archivo según el plan.
3. **Gates §3** (todos exit code 0):
   - `ruff check src/sky/ingestion/ tests/`
   - `mypy src/sky/ingestion/`
   - `pytest tests/ -v --cov=... --cov-report=term-missing`
   - Smoke contra Redis local (si aplica)
   - `uvicorn` arranca + `/api/health` 200
4. **Migraciones SQL**: aplicar en staging primero, prod después. Verificar con query.
5. **Commit**: mensaje exacto del plan, en español, con `Co-Authored-By: Claude ...`.
6. **Update**: `docs/MIGRATION_13_PHASES.md` con `### Estado: ✅ Cerrada (YYYY-MM-DD)` + lista de archivos + gates marcados.

---

## Reglas de operación con Claude

- **Trabajamos directo en `main`** (decisión 2026-04-30). Sin worktrees, sin PRs en flujo normal. `.claude/` está en `.gitignore`.
- **El usuario hace `push`**. Yo solo commit local.
- **Cuando algo está oscuro o conflictivo**: parar y preguntar antes de tocar archivos. No tomar decisiones destructivas (reset --hard, merge, force) sin OK explícito.
- **Plan-first para fases**: nunca empezar a escribir código de una fase sin antes proponer/escribir el `FASE<N>_CLOSURE_PLAN.md`.
- **Si encuentro deuda fuera de scope**: documentar como TODO referenciando la fase correcta, no arreglarlo en el momento.
- **No tocar `backend/` (Node)** salvo que el usuario lo pida explícitamente. Ese código está en producción.

---

## Atajos de contexto frecuentes

- "Estado de fases" → `backend-python/docs/MIGRATION_13_PHASES.md`
- "Por qué este patrón" / "deuda P0" → `backend-python/docs/REMEDIATION_P0_P3.md`
- "Cómo cierro una fase" → `backend-python/docs/FASE5_CLOSURE_PLAN.md` (template)
- "Cómo corrió el smoke" → `backend-python/scripts/smoke_router.py`
- "Bancos soportados" → `backend-python/src/sky/ingestion/sources/__init__.py` (`SUPPORTED_BANKS`)
- "Router rules iniciales" → `backend-python/migrations/001_routing_rules.sql`

---

*Última actualización: 2026-04-30 · Tras cierre de Fase 5*
