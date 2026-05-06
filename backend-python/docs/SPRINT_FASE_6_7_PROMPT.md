# Sprint Fase 6 + 7 — Prompt para Claude Code Sonnet (PowerShell)

> Pegar este texto entero en una sesión nueva de Claude Code Sonnet, working dir =
> `C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL`.
> Modelo: `claude-sonnet-4-5` (más potente y mucho más rápido en este tipo de
> implementación masiva). El usuario opera Windows + miniconda + PowerShell.

---

## INSTRUCCIÓN PRIMARIA

Cierra **Fase 6** (Queue ARQ + Categorizer + Sync orchestrator) y luego **Fase 7**
(API endpoints) del backend Python (`backend-python/`). Trabaja directo en `main`,
commit local, el usuario hace `git push`. No worktrees. No PRs.

Antes de tocar una sola línea, **lee en orden**:

1. `CLAUDE.md` (raíz) — doctrina, reglas inviolables, mapa del repo.
2. `backend-python/docs/MIGRATION_13_PHASES.md` — plan maestro técnico.
3. `backend-python/docs/FASE6_CLOSURE_PLAN.md` — plan completo de Fase 6.
4. `backend-python/docs/REMEDIATION_P0_P3.md` — deuda y qué cierra cada fase.
5. `backend-python/README.md` — estado real de cada fase.

Si algo en este prompt contradice esos archivos, **gana el archivo**. Si la
contradicción es importante, para y avisa al usuario.

---

## DOCTRINA INVIOLABLE (no negociable, sobrescribe conveniencia de corto plazo)

1. **API Python NUNCA importa Playwright.** El worker es el único con browser pool.
2. **`sky.domain` jamás pregunta de qué `source` vino un movimiento.** Modelo
   canónico único.
3. **Scraper como fallback permanente.**
4. **`AuthenticationError` NO dispara failover** del IngestionRouter.
5. **Rate limit = `skip`, no `fail`.** Siguiente provider de la cadena se intenta.
6. **`SUPABASE_SERVICE_KEY` y `BANK_ENCRYPTION_KEY` solo en backend.** Nunca en
   logs ni en frontend.
7. **Credenciales bancarias = AES-256-GCM con IV único** (`b64(iv):b64(authTag):b64(ct)`,
   binario-compatible con Node — esto YA está validado en
   `tests/unit/test_encryption_compat.py`, NO romper).
8. **Mr. Money guía; no decide.** Toda propuesta estructurada requiere confirmación.
9. **ARIA solo se activa con `aria_consent = true`.** Sin UUID en `aria.*`.
   Service_role exclusivo.
10. **RLS habilitado en TODAS las tablas de `public`.**
11. **Nunca `print`** — usar `structlog` con `get_logger(...)`.
12. **`StrEnum` (3.11+)** en vez de `(str, Enum)`.
13. **`from __future__ import annotations` siempre** al tope de cada `.py`.
14. **`pydantic-settings` `Settings` clase** para config; fail-fast si falta env var.
15. **Sin `# type: ignore`** salvo cuando mypy genuinamente no puede inferir.
16. **Async-first**: SQLAlchemy 2.0 async, `redis.asyncio`, FastAPI native async,
    ARQ, `httpx` async.
17. **Errores tipados en `sky.core.errors`.** No crear duplicados.

---

## ESTADO ACTUAL VERIFICADO (2026-05-05)

### ✅ Fase 5 cerrada
IngestionRouter con rate limiter (Redis sliding window log), circuit breaker,
routing rules en DB. 64 tests verdes. Migration `001_routing_rules.sql` aplicada
en Supabase.

### 🟡 Fase 6 — ~90% IMPLEMENTADA, faltan tests + migration + gates

**Archivos YA implementados (NO tocar salvo bug genuino):**
- `src/sky/core/locks.py` — `try_advisory_lock` con SHA-256 → int64.
- `src/sky/domain/categorizer.py` — 3 capas, paridad con Node v3.
- `src/sky/worker/banking_sync.py` — orquestador con advisory lock.
- `src/sky/worker/jobs/sync.py` — `sync_bank_account_job`, `sync_all_user_accounts_job`.
- `src/sky/worker/jobs/categorize.py` — `categorize_pending_job`.
- `src/sky/worker/main.py` — `WorkerSettings`, `arq_pool` en ctx.
- `src/sky/api/main.py` — `arq_pool` en `app.state`.
- `src/sky/api/schemas/banking.py` — `SyncBankAccountResponse`, `SyncAllResponse`.
- `src/sky/api/routers/banking.py` — `POST /api/banking/sync/:id`, `POST /api/banking/sync-all`.

**Lo que FALTA y debes hacer:**

1. `backend-python/migrations/002_indexes_and_constraints.sql`
   - Crear `idx_transactions_pending` (índice parcial sobre
     `(created_at) WHERE categorization_status = 'pending'`).
   - Reforzar `uniq_tx_external` si no existe (ya está en `000_immediate_fixes.sql`,
     pero verificar y dejar `IF NOT EXISTS`).
   - Verificación inline al final con `-- SELECT indexname FROM pg_indexes ...`

2. `tests/unit/test_categorizer.py`
   - Layer 1 cierra para 22 reglas (al menos un caso por regla).
   - `normalize_merchant`: limpia `"Pago: Jumbo Las Condes  *  ..."` → `"jumbo las condes"`.
   - `_key_variants("jumbo las condes")` == `["jumbo las condes", "jumbo las", "jumbo"]`.
   - `_lookup_cache` con DB mockeada: golpea variante de prefijo.
   - `_categorize_with_ai` con `anthropic` mockeado (no llamadas reales).
   - `categorize_movements` end-to-end con stub de las 3 capas.

3. `tests/unit/test_advisory_lock.py`
   - Lock se adquiere si está libre.
   - Lock se rechaza si ya tomado por otra conexión simultánea.
   - Lock se libera al salir del bloque (verificar con segundo `try_advisory_lock`).
   - Usa fixtures de Postgres real o `pytest-postgresql` (preferible mock con
     `engine.connect()` que devuelva `pg_try_advisory_lock` controlado, si no hay
     PG disponible en CI).

4. `tests/integration/test_sync_job.py`
   - Mock del `IngestionRouter.ingest()` retornando 3 movimientos canónicos.
   - Verifica que se insertan con `categorization_status='pending'`.
   - Verifica que `arq_pool.enqueue_job("categorize_pending_job")` se llama.
   - Verifica que segundo run no duplica (ON CONFLICT DO NOTHING).
   - Verifica que `bank_accounts` se actualiza (last_sync_at, last_balance,
     consecutive_errors=0).

5. **GATES §3 — todos exit code 0** (ver §"Gates" más abajo).

6. **Aplicar migration 002 en Supabase** — pedir al usuario que la ejecute en el SQL Editor.
   No intentar aplicarla con `psql` ni con el cliente de Supabase desde aquí.

7. `backend-python/docs/MIGRATION_13_PHASES.md` — agregar `### Estado: ✅ Cerrada (YYYY-MM-DD)`
   en la sección de Fase 6, listar archivos y gates marcados.

8. **Commit de cierre Fase 6**:
   ```
   Fase 6 cerrada: queue ARQ, categorizer 3 capas, sync orchestrator con advisory lock

   Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
   ```

### 🔴 Fase 7 — TODO STUB, hay que implementar de cero

**Antes de escribir código, crear `backend-python/docs/FASE7_CLOSURE_PLAN.md`**
siguiendo el template de `FASE6_CLOSURE_PLAN.md`. Sin plan no se escribe código.

Stubs actuales (todos ~4-8 LOC, hay que reemplazarlos):
- `src/sky/api/routers/transactions.py` · `schemas/transactions.py`
- `src/sky/api/routers/summary.py` · `schemas/summary.py`
- `src/sky/api/routers/goals.py` · `schemas/goals.py`
- `src/sky/api/routers/challenges.py` · `schemas/challenges.py`
- `src/sky/api/routers/chat.py` · `schemas/chat.py`
- `src/sky/api/routers/simulate.py`
- `src/sky/api/routers/webhooks.py`
- `src/sky/api/routers/internal.py`
- `src/sky/api/routers/health.py` (verificar)
- `src/sky/domain/mr_money.py` · `finance.py` · `goals.py` · `challenges.py` · `simulations.py`

**JWT auth (P0-1)**: ya existe `src/sky/api/middleware/jwt_auth.py` y
`api/deps.py::require_user_id`. Usarlo en cada endpoint con
`user_id: str = Depends(require_user_id)`. Cierra P0-1 cuando se cubra todo.

**Endpoints a implementar (paridad con Node `backend/routes/*`):**

| Endpoint                           | Método | Schema                       |
|-----------------------------------|--------|------------------------------|
| `/api/transactions`                | GET    | lista paginada               |
| `/api/transactions/:id`            | PATCH  | recategorizar                |
| `/api/transactions/:id`            | DELETE | soft delete                  |
| `/api/summary`                     | GET    | balance, ingresos, gastos    |
| `/api/summary/by-category`         | GET    | breakdown                    |
| `/api/banking/accounts`            | GET    | lista cuentas + estado       |
| `/api/banking/accounts/:id`        | DELETE | desconectar                  |
| `/api/goals`                       | GET/POST | metas de ahorro            |
| `/api/goals/:id`                   | PATCH/DELETE |                       |
| `/api/challenges`                  | GET    | desafíos activos             |
| `/api/challenges/:id/accept`       | POST   | confirmar propuesta          |
| `/api/challenges/:id/decline`      | POST   |                              |
| `/api/chat`                        | POST   | Mr. Money — texto / propose  |
| `/api/simulate/projection`         | POST   | simulación financiera        |
| `/api/webhooks/fintoc`             | POST   | (stub si Fintoc no activo)   |
| `/api/internal/cron/sync-due`      | POST   | scheduler — `x-cron-secret`  |

**Mr. Money (`domain/mr_money.py`)**:
- Detección local primero (saludos, "qué tal mi desafío X", deep-links).
- Si no matchea → construir contexto financiero (balance, ingresos/gastos por
  categoría, tasa ahorro, metas, desafíos, cuentas) → `claude-sonnet-4-5`
  (NO confundir con Sonnet usándose ahora — modelo de Anthropic API).
- Tipos de respuesta: texto · `propose_challenge` (estructurada) · navegación.
- Tools (Anthropic tool use): `compute_projection`, `evaluate_goal_realism`.
- Prompt caching activado en system + tools (TTL 5min default, 1h en tools si
  son grandes).
- NUNCA llamar a Anthropic desde frontend. Aquí, solo backend.
- NO da asesoría de inversión específica, NO recomienda activos puntuales.

**ARIA (`domain/aria.py`)**:
- Pipeline 5 pasos: extracción → categorización (rangos) → eliminación
  identidad → randomización intra-bucket → ruptura correlaciones (jitter ±36h,
  batch_id propio).
- **Guard**: leer `profiles.aria_consent`; si `false`, return early sin escribir.
- Service_role exclusivo. Schema `aria.*` (no `public.*`).
- Llamada desde `worker/banking_sync.py` post-insert (con feature flag
  `settings.sync_aria_enabled`).
- Cierra **P0-2** cuando se cubra el guard.

**Tests Fase 7**:
- `tests/unit/test_mr_money.py` — detección local, construcción de contexto.
- `tests/unit/test_aria.py` — guard de consentimiento, anonimización.
- `tests/unit/test_finance.py` — cálculos de balance, agregación.
- `tests/integration/test_api_transactions.py` — CRUD con DB mock.
- `tests/integration/test_api_chat.py` — Mr. Money con Anthropic mockeado.

**Commit de cierre Fase 7**:
```
Fase 7 cerrada: API endpoints, Mr. Money con tool use, ARIA con consent guard

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

---

## GATES §3 (todos exit code 0 — bloqueantes para commit de cierre)

```powershell
cd C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL\backend-python
.venv\Scripts\activate

ruff check src/sky/ tests/
mypy src/sky/
pytest tests/ -v --cov=src/sky --cov-report=term-missing

# Smoke router (requiere Redis local)
docker run -d --rm -p 6379:6379 --name sky-redis-smoke redis:7-alpine
$env:REDIS_URL = "redis://localhost:6379"
python scripts/smoke_router.py
docker stop sky-redis-smoke

# Health check
$env:REDIS_URL = "redis://localhost:6379"
Start-Process -NoNewWindow uvicorn -ArgumentList "sky.api.main:app","--port","8000"
Start-Sleep -Seconds 3
Invoke-WebRequest http://localhost:8000/api/health -UseBasicParsing
# Stop con Ctrl+C o: Get-Process uvicorn | Stop-Process
```

Coverage mínimo aceptable Fase 6: **75%** del módulo `sky.domain.categorizer`,
`sky.worker.*`, `sky.core.locks`. Fase 7: **70%** de `sky.api.routers`,
`sky.domain.mr_money`, `sky.domain.aria`.

---

## DEUDA QUE CIERRAS CON ESTE SPRINT

| ID    | Item                                          | Cierra en              |
|-------|-----------------------------------------------|------------------------|
| P0-1  | JWT auth en backend                           | Fase 7 (todos endpoints) |
| P0-2  | Consent ARIA inconsistente                    | Fase 7 (`domain/aria.py` guard) |
| BUG-1 | `external_id` inconsistente entre 2 impls    | Fase 6 (única `build_external_id` en `categorizer.py` + `banking_sync.py`) |
| BUG-2 | Upsert apunta a UNIQUE INDEX inexistente      | Fase 6 (`002_indexes_and_constraints.sql`) |
| BUG-3 | Lock en memoria del proceso                   | Fase 6 (`pg_try_advisory_lock`) |
| BUG-4 | Sync secuencial entre bancos                  | Fase 6 (`sync_all_user_accounts_job` encola N jobs paralelos) |

Verificar uno por uno antes del commit de cierre. Listar en el mensaje del commit
qué cerró efectivamente.

---

## CONVENCIONES POWERSHELL (no bash)

```powershell
# Set env var:
$env:REDIS_URL = "redis://localhost:6379"   # NO: REDIS_URL=... cmd
# Chaining condicional:
ruff check src/; if ($?) { mypy src/ }      # NO: ruff && mypy
# Heredoc:
git commit -m @'
Mensaje multilínea aquí.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
'@
# El cierre '@ DEBE ir en columna 0, sin indentar.
```

Cuando llames a `Bash` tool: lee la nota de PowerShell — **no usar `&&` ni
`echo`**. En este repo `Bash` corre en Git Bash (ruta `/usr/bin/bash`) si está
disponible, pero por defecto **prefiere `PowerShell`** (el usuario está en Windows).

---

## REGLAS DE OPERACIÓN CON CLAUDE

- **Trabajamos directo en `main`.** Sin worktrees, sin PRs en flujo normal.
- **El usuario hace `git push`.** Solo commit local.
- **Nunca `--force` push a main.** Si parece necesario, algo está mal — diagnosticar.
- **Ante ambigüedad o conflicto**: parar y preguntar. No tomar acciones
  destructivas (`reset --hard`, merge, force) sin OK explícito.
- **Plan-first para Fase 7**: nunca empezar a escribir código sin primero el
  `FASE7_CLOSURE_PLAN.md`.
- **No tocar `backend/` (Node)** salvo solicitud explícita.
- **Si encuentras deuda fuera de scope**: documentar como TODO referenciando
  fase del v5, no arreglar en el momento.
- **Reportes finos, no épicos.** Sin "completado exitosamente con éxito". Datos:
  archivos tocados, tests añadidos (X verdes / Y), gates pasados.

---

## ORDEN SUGERIDO DE EJECUCIÓN

```
1. Leer CLAUDE.md + MIGRATION_13_PHASES.md + FASE6_CLOSURE_PLAN.md
2. git status + git log -5  (entender estado del repo)
3. FASE 6 — cierre:
   3.1 migrations/002_indexes_and_constraints.sql
   3.2 tests/unit/test_categorizer.py
   3.3 tests/unit/test_advisory_lock.py
   3.4 tests/integration/test_sync_job.py
   3.5 Gates §3 (todos verdes)
   3.6 Pedir al usuario aplicar migration 002 en Supabase
   3.7 Update MIGRATION_13_PHASES.md
   3.8 Commit "Fase 6 cerrada: ..."
4. FASE 7 — preparación:
   4.1 Escribir docs/FASE7_CLOSURE_PLAN.md (template = FASE6_CLOSURE_PLAN.md)
   4.2 Pasar plan al usuario para aprobación antes de codear
5. FASE 7 — implementación (sólo tras aprobación):
   5.1 domain/finance.py (cálculos puros)
   5.2 schemas/* (Pydantic)
   5.3 routers/transactions.py + tests
   5.4 routers/summary.py + tests
   5.5 routers/banking.py extender (GET /accounts) + tests
   5.6 routers/goals.py + domain/goals.py + tests
   5.7 routers/challenges.py + domain/challenges.py + tests
   5.8 domain/mr_money.py (detección local + Claude tool use con caching)
   5.9 routers/chat.py + tests
   5.10 routers/simulate.py + domain/simulations.py + tests
   5.11 domain/aria.py con consent guard + tests
   5.12 worker/banking_sync.py: invocar ARIA post-insert (feature flag)
   5.13 routers/webhooks.py + routers/internal.py
   5.14 Gates §3 verdes
   5.15 Update MIGRATION_13_PHASES.md
   5.16 Commit "Fase 7 cerrada: ..."
```

---

## OUTPUT ESPERADO AL FINAL

Mensaje breve al usuario con:
- ✅/❌ por cada gate
- Tests añadidos: N
- Coverage delta
- P/BUG cerrados
- 2 commits listos para push (`git log --oneline -5`)
- Pendientes (si los hay) con fase v5 referenciada

**Sin disculpas, sin "perfecto", sin emojis decorativos.** Datos.

---

## STARTUP CHECK

Apenas arranques, antes de leer nada más, ejecuta:

```powershell
cd C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL
git status
git log --oneline -5
ls backend-python/docs/
```

Si `git status` muestra mucho staged/modificado que no entiendes, **para y pregunta**
antes de tocar archivos. Si alguno de los archivos listados como "ya implementados"
no existe o es un stub, **para y pregunta** — el estado verificado fue 2026-05-05.

Andá.
