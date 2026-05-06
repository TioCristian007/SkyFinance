# Handover — Fase 9 (Scheduler ARQ)

> Documento de contexto para abrir una sesión NUEVA de Claude Code y continuar
> con la migración Python. Self-contained — la sesión nueva no necesita ver
> esta conversación previa.
>
> **Última actualización**: 2026-05-06 · tras cerrar Fase 7 (commit 8122394)

---

## 0. Cómo usar este doc

1. Abrir nueva sesión de Claude Code en `C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL`.
2. Modelo recomendado para Claude Code: **Sonnet 4.6** (default — suficiente para Fase 9).
   Para Mr. Money en runtime el alias en config es `claude-sonnet-4-6`.
3. Pegar el prompt de §10 al final como primer mensaje.
4. Sonnet leerá este archivo + `CLAUDE.md` + `MIGRATION_13_PHASES.md` y procederá.

---

## 1. Qué es Sky (resumen para arrancar rápido)

Sky Finance — **sistema operativo financiero personal**. Capa cognitiva entre la
persona y su vida financiera. Tres pilares: automatización bancaria · Mr. Money
(IA conversacional con tool use) · diseño conductual (metas, desafíos).

**Cofundadores**: Cristian Vásquez (22.141.522-1) + Juan José Latorre (22.003.365-1).
SkyFinanzas SpA (RUT 78.395.382-K).

**Fuente de verdad doctrinal**: `Estados del Arte/SkyFinanzas_EstadoDelArte_v5_Documentado.pdf`
(registrado en INAPI). Si algo en otros docs contradice al v5, gana el v5.

---

## 2. Estado del repo (verificado 2026-05-06)

### Commits locales (9 ahead de origin/main)

```
8122394  Fase 7 cerrada: Mr. Money tool use con caching, ARIA pipeline 5 pasos…
becc80f  feat(fase7): goals, challenges, simulations, webhooks, internal cron, ARIA client
c96694d  docs(fase7): aplicar 4 ajustes pre-aprobados antes de implementar
07c85ea  docs(fase7): plan de cierre — API endpoints, Mr. Money tool use, ARIA…
f28fbc6  test(fase6): completar suite de tests — 131 passed, coverage ≥ 95%…
434be75  Fase 6 cerrada: Queue ARQ con sync_bank_account_job, advisory lock…
0ed3ae9  docs(fase6): plan completo de cierre — Queue ARQ + categorización 3 capas
50950d0  docs(CLAUDE.md): integrar Estado del Arte v5 (registro INAPI) como…
904a63a  docs: agregar CLAUDE.md raíz y reescribir README de backend-python
```

### Fases del plan de 13

| Fase | Nombre | Estado |
|------|--------|--------|
| 0 | Scaffolding | ✅ |
| 1 | Contrato DataSource | ✅ |
| 2 | Core infra | ✅ |
| 3 | Encryption Node↔Python (binario) | ✅ — fixtures Node validados |
| 4 | BChile/Falabella scrapers Playwright | ✅ |
| 5 | IngestionRouter + circuit breaker + rate limiter | ✅ |
| 6 | Queue ARQ + categorizer 3 capas + advisory lock | ✅ |
| 7 | FastAPI endpoints + dominio (Mr. Money, ARIA, finance, goals, challenges, simulations) | ✅ — fusionada con Fase 8 |
| 8 | Dominio | ✅ — implícitamente cerrada con Fase 7 |
| **9** | **Scheduler ARQ cron** | 🔴 **PRÓXIMA** |
| 10 | Observabilidad (Prometheus, Sentry, /health/deep) | 🔴 |
| 11 | Docker + deploy en Railway | 🔴 |
| 12 | Migraciones SQL definitivas + RLS verification | 🔴 |
| 13 | Parity tests + canary 48h + cutover gradual | 🔴 |

### Tests

```
275 passed, 1 skipped
ruff: 0 errores
mypy: 0 issues (71 archivos)
coverage:
  domain/categorizer.py    99%
  domain/finance.py       100%
  domain/aria.py           78%
  domain/mr_money.py       78%
  worker/banking_sync.py   95%
  core/locks.py           100%
  worker/jobs/*           100%
```

### Deuda técnica cerrada en este sprint

- ✅ **P0-1** — JWT criptográfico en TODOS los endpoints (eliminado header `x-user-id`)
- ✅ **P0-2** — ARIA consent guard estricto (`_has_aria_consent` fail-safe)
- ✅ **BUG-1** — `external_id` determinístico (única `build_external_id`)
- ✅ **BUG-2** — UNIQUE INDEX `uniq_tx_external` (migration 002)
- ✅ **BUG-3** — `pg_try_advisory_lock` (no más Set en memoria)
- ✅ **BUG-4** — Browser pool paralelo (sync_all_user_accounts_job encola N jobs)

### Deuda técnica activa (Parte III v5)

| ID | Item | Cierra en |
|----|------|-----------|
| P1-1 | `Sky.jsx` god-component (1 678 LOC) | Refactor frontend, paralelo a migración |
| P1-2 | CORS permisivo por fallback | Cerrado en Python pero verificar al deploy |
| P2-1..4 | Tests / CI / rate limiting / monitoring | Fase 10 |
| P2-5 | Paralelismo Puppeteer sin límite | Mitigado en Python (browser pool default 4) |
| P2-6 | Rotación `BANK_ENCRYPTION_KEY` sin procedimiento | Documentar en Fase 11 |

---

## 3. Pendientes inmediatos antes de Fase 9

### 3.1. Aplicar migration 002 en Supabase (manual del usuario)

Abrir SQL Editor en Supabase, pegar contenido de
`backend-python/migrations/002_indexes_and_constraints.sql`, ejecutar. Verificar:

```sql
SELECT indexname FROM pg_indexes
 WHERE tablename = 'transactions'
   AND (indexname LIKE 'uniq_%' OR indexname LIKE 'idx_%')
 ORDER BY indexname;
-- Esperado: idx_transactions_pending, idx_tx_bank_account, idx_tx_user_date,
--           uniq_tx_external
```

Esta migración no es bloqueante para Fase 9 técnicamente, pero
`idx_transactions_pending` es lo que evita que `categorize_pending_job` escanee
toda la tabla cuando hay volumen real.

### 3.2. Push a origin (manual del usuario)

```powershell
git push origin main
```

9 commits locales pendientes de push. No bloquea Fase 9 técnicamente, pero
conviene tener el origen sincronizado antes de seguir.

### 3.3. TODOs menores documentados (no bloqueantes — pueden hacerse en Fase 9 cuando se toquen los archivos)

| # | Archivo | Línea | Issue | Severidad |
|---|---------|-------|-------|-----------|
| 1 | `domain/aria.py` | 232 | `has_significant_content(text)` shadowea `text` de sqlalchemy. Renombrar param a `content`. | trivial |
| 2 | `domain/aria.py` | 93 | `import random` dentro de `_random_in_bucket`. Mover al top. | trivial |
| 3 | `worker/banking_sync.py` | 117 | `result.movements[:inserted]` asume orden. ON CONFLICT puede saltar duplicados intercalados. No afecta buckets ARIA pero es semánticamente flojo. | minor |
| 4 | `worker/banking_sync.py` | 114-125 | `await track_spending_event` en loop bloquea el sync. No es realmente fire-and-forget. Usar `asyncio.create_task(...)` o batch. | minor |
| 5 | `api/routers/chat.py` | 24 | `asyncio.ensure_future` puede ser GC'd. Migrar a `BackgroundTasks` de FastAPI. | minor |
| 6 | `api/routers/internal.py` | 22 | `==` para cron secret. Conviene `secrets.compare_digest()` para timing-safe. | trivial |
| 7 | `core/db.py` | 31 | `os.getenv("DATABASE_URL")` directo no lee `.env` — depende del shell environment. `core/config.py::Settings` no declara `database_url`, así que pydantic-settings ignora la var del `.env`. Fix: agregar `database_url: str` al Settings y que `db.py` use `settings.database_url`. | **bloqueante DX local** |

Ninguno de estos justifica un commit aparte. Cuando Fase 9 toque alguno de estos
archivos, aprovechar para fixearlo dentro del mismo commit.

---

## 4. Plan Fase 9 — Scheduler ARQ cron

### 4.1. Objetivo

Reemplazar el `internal.py::cron_sync_due` (que requiere Railway cron / GitHub
Actions externo) por un **cron nativo de ARQ** corriendo en el worker. Cada hora
el worker dispara `scheduled_sync_job` que selecciona cuentas elegibles y encola
`sync_bank_account_job` para cada una.

Equivalente Node: `backend/services/schedulerService.js`. Leer ese archivo
**antes de implementar** para paridad.

### 4.2. Lo que se hace

1. **`src/sky/worker/jobs/scheduled.py`** (NUEVO):
   - `scheduled_sync_job(ctx)`: query bank_accounts due → encolar
     `sync_bank_account_job` por cada uno → log resumen.
   - Reusar lógica de `routers/internal.py::cron_sync_due` (idéntica).
   - Backoff exponencial sobre `consecutive_errors`:
     - 0 errores → cada 1h
     - 1 error → 2h
     - 2 errores → 4h
     - 3+ errores → 8h
     - 5+ errores → skip (queda en `error` permanente hasta intervención)

2. **`src/sky/worker/main.py`** (MODIFICAR):
   - Importar `scheduled_sync_job`.
   - Agregar a `WorkerSettings.functions`.
   - Agregar `cron_jobs = [cron(scheduled_sync_job, hour={0..23}, minute=5)]`
     usando `arq.cron`. Cada hora a los 5 min del minuto.

3. **`src/sky/core/config.py`** (MODIFICAR):
   - Mantener `scheduler_due_threshold_hours` (ya existe).
   - Agregar `scheduler_backoff_factor: int = 2` y
     `scheduler_max_per_tick: int = 100` (lo que ya hace internal.py).

4. **`src/sky/api/routers/internal.py`** (DECISIÓN):
   - Opción A: deprecar `/cron/sync-due` (DEPRECATED comment, mantener por
     compatibilidad mientras se prueba el cron ARQ).
   - Opción B: borrarlo.
   - **Recomendado**: Opción A. Mantener 2 ciclos de prueba, después borrar.

5. **`tests/unit/test_scheduled_job.py`** (NUEVO):
   - Mock get_engine + arq_pool.
   - Verificar query con backoff aplicado.
   - Verificar enqueue por cuenta.
   - Verificar skip cuando no hay due.
   - Verificar respeto de `scheduler_max_consecutive_errors`.

6. **`docs/MIGRATION_13_PHASES.md`** (MODIFICAR):
   - Marcar Fase 9 como `### Estado: ✅ Cerrada (2026-05-XX)`.

### 4.3. Definition of Done

- `pytest tests/ -v` → todos pasan + tests nuevos del scheduled job
- `ruff check src/sky/ tests/` → 0
- `mypy src/sky/` → 0
- `arq sky.worker.main.WorkerSettings` arranca limpio (gate manual con Redis local)
- Logs muestran `[scheduler] tick start` cada hora
- Coverage ≥ 75% en `worker/jobs/scheduled.py`

### 4.4. Estimación

2-3 días con Claude Code. La fase es mecánicamente simple — el reto es validar
que el cron de ARQ no se pisa con jobs en curso (advisory lock ya lo resuelve a
nivel `bank_account_id`).

---

## 5. Doctrinas inviolables (resumen — ver `CLAUDE.md` para detalle)

1. API Python NUNCA importa Playwright. Solo el worker.
2. `sky.domain` no pregunta de qué `source` vino un movimiento.
3. Scraper como fallback permanente.
4. `AuthenticationError` no dispara failover.
5. Rate limit = `skip`, no `fail`.
6. `SUPABASE_SERVICE_KEY` y `BANK_ENCRYPTION_KEY` solo en backend.
7. Mr. Money guía; NO decide. propose_challenge requiere confirmación explícita.
8. ARIA solo con `aria_consent = true`. Sin UUID en `aria.*`. Service_role.
9. `from __future__ import annotations` siempre.
10. `StrEnum` (3.11+), no `(str, Enum)`.
11. Async-first. Sin `print`. Usar `structlog.get_logger`.
12. Excepciones tipadas en `sky.core.errors`.
13. `pydantic-settings` `Settings` con fail-fast.

---

## 6. Convenciones PowerShell (Windows)

```powershell
# Activar venv:
.venv\Scripts\activate

# Set env var:
$env:REDIS_URL = "redis://localhost:6379"   # NO bash style

# Chain condicional:
ruff check src/; if ($?) { mypy src/ }      # NO &&

# Heredoc:
git commit -m @'
Mensaje multilínea.

Co-Authored-By: Claude Sonnet 4.7 <noreply@anthropic.com>
'@
# Cierre '@ en columna 0, sin indentar.
```

`Bash` tool en Windows puede romperse — preferir `PowerShell` cuando sea posible.

---

## 7. Comandos útiles

### Setup (si la venv no está activa)

```powershell
cd C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL\backend-python
.venv\Scripts\activate
```

### Loop dev

```powershell
ruff check src/sky/ tests/
mypy src/sky/
pytest tests/ -v --cov=src/sky --cov-report=term-missing
```

### Smoke contra Redis real

```powershell
docker run -d --rm -p 6379:6379 --name sky-redis-smoke redis:7-alpine
$env:REDIS_URL = "redis://localhost:6379"
python scripts/smoke_router.py
docker stop sky-redis-smoke
```

### Levantar API + worker

```powershell
$env:REDIS_URL = "redis://localhost:6379"
# Windows necesita asyncio loop:
uvicorn sky.api.main:app --loop asyncio --port 8000
# o usar el helper:
python scripts/run_dev.py

# Worker (otra terminal):
arq sky.worker.main.WorkerSettings
```

### Verificar health

```powershell
Invoke-WebRequest http://localhost:8000/api/health -UseBasicParsing
```

---

## 8. Cierre de fase — proceso estándar

1. **Plan-first**: crear `docs/FASE9_CLOSURE_PLAN.md` antes de tocar código.
2. Implementación archivo por archivo según plan.
3. Gates §3 — todos exit code 0:
   - `ruff check src/sky/ tests/`
   - `mypy src/sky/`
   - `pytest tests/ -v --cov=...`
   - `arq sky.worker.main.WorkerSettings` arranca limpio
4. Verificar P/BUG cerrados (cruzar con tabla §19 del v5).
5. Commit: mensaje exacto del plan, en español. `Co-Authored-By: Claude`.
6. Update `docs/MIGRATION_13_PHASES.md` con `### Estado: ✅ Cerrada (YYYY-MM-DD)`.

---

## 9. Reglas de operación con Claude

- Trabajamos directo en `main`. Sin worktrees, sin PRs.
- El usuario hace `git push`. Yo solo commit local.
- Nunca `--force` push a main.
- Ante ambigüedad: parar y preguntar. Sin acciones destructivas (`reset --hard`,
  merge, force) sin OK explícito.
- Plan-first: nunca empezar a escribir código sin primero el `FASE<N>_CLOSURE_PLAN.md`.
- No tocar `backend/` (Node) salvo solicitud explícita.
- Si encuentro deuda fuera de scope: documentar como TODO referenciando fase v5.
- PowerShell por defecto.
- Reportes finos, no épicos. Sin "completado exitosamente con éxito". Datos.

---

## 10. PROMPT INICIAL para sesión nueva

> Pegar este bloque entero como primer mensaje en la nueva sesión de Claude Code.

```
Continuamos la migración Python de Sky Finance. Working dir:
C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL

Lee EN ESTE ORDEN antes de hacer nada:
1. backend-python/docs/HANDOVER_FASE_9.md (este archivo te da el contexto completo)
2. CLAUDE.md (raíz — doctrina inviolable)
3. backend-python/docs/MIGRATION_13_PHASES.md (plan maestro)

Estado actual:
- Fases 0-8 cerradas (8 implícita con 7)
- 9 commits locales ahead de origin (no pushear sin OK del usuario)
- 275 tests pasando, coverage en módulos clave 78-100%
- Deuda P0-1, P0-2, BUG-1..4 cerrada
- Migration 002 en Supabase pendiente (gate manual del usuario)

Tu tarea: cerrar Fase 9 (Scheduler ARQ cron).

Proceso obligatorio:
1. PRIMERO crear backend-python/docs/FASE9_CLOSURE_PLAN.md siguiendo el
   template de FASE6/FASE7. Sin plan no se escribe código.
2. Pasar el plan al usuario para aprobación.
3. SOLO tras aprobación → implementar archivo por archivo.
4. Aprovecha el commit para fixear los 6 TODOs menores documentados en
   §3.3 del HANDOVER si tocás esos archivos (aria.py:93, aria.py:232,
   banking_sync.py:117, banking_sync.py:114-125, chat.py:24, internal.py:22).
5. Gates §3 verdes antes de commit.
6. Update MIGRATION_13_PHASES.md con estado ✅ Cerrada.

Doctrinas inviolables que aplican aquí:
- API NUNCA importa Playwright. Solo el worker arranca browser pool.
- AuthenticationError no dispara failover.
- ARIA solo con aria_consent=true. Sin UUID en aria.*.
- Trabajamos en main directo. Sin PRs.
- El usuario pushea. Yo solo commit local.

Equivalente Node a leer para paridad: backend/services/schedulerService.js

Andá. Reportá cuando el plan esté listo.
```

---

## 11. Después de Fase 9

| Fase | Contenido | Estimación | Notas |
|------|-----------|------------|-------|
| 10 | Observabilidad (Prometheus, Sentry, /health/deep) | 3-5 días | Cierra P2-1..4 |
| 11 | Docker + deploy Railway (servicios nuevos) | 1-2 días | NO apuntar `api.skyfinanzas.com` aún |
| 12 | Migraciones SQL finales + RLS audit | medio día | RLS en todas las tablas nuevas |
| 13 | Parity tests + canary 48h + cutover 10/50/100% | 2-3 semanas | El frontend SOLO se toca aquí (feature flag VITE_API_URL) |

**El frontend React no se toca en Fases 9-12.** Solo en Fase 13 con feature flag.
Refactor de `Sky.jsx` (P1-1, 1678 LOC) va en paralelo, fuera del plan de 13 fases.

---

## 12. Riesgo a vigilar

**Scope creep durante migración.** Si alguien dice "ya que estamos
reescribiendo, agreguemos X", el plan se extiende indefinidamente. Regla:
**paridad primero, features después.** Python debe hacer exactamente lo mismo
que Node antes de hacer algo nuevo. Cualquier feature nuevo se agrega DESPUÉS
del cutover (Fase 13).
