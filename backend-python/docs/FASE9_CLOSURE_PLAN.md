# FASE 9 — Scheduler ARQ cron: Plan de cierre

> Plan-first obligatorio. Sin plan aprobado no se escribe código.
> Template: `FASE6_CLOSURE_PLAN.md` / `FASE7_CLOSURE_PLAN.md`.
> Fecha: 2026-05-06

---

## 1. Contexto

### Objetivo
Reemplazar el endpoint externo `/api/internal/cron/sync-due` (que dependía de Railway cron /
GitHub Actions) por un **cron nativo de ARQ** corriendo dentro del propio worker.
Cada hora (a los :05 min) el worker dispara `scheduled_sync_job`, que selecciona
cuentas elegibles con backoff exponencial y encola `sync_bank_account_job` por cada una.

### Equivalente Node
`backend/services/schedulerService.js` → `runScheduledSync()`.
El archivo Python replica la misma lógica de query + filtro backoff + enqueue.

### Paridad con Node
| Aspecto | Node (`schedulerService.js`) | Python |
|---|---|---|
| Query base | `bank_accounts` + `profiles!inner`, `auto_sync_enabled=true` | Igual — JOIN profiles |
| Campo de backoff | `last_scheduled_at` | `last_scheduled_at` (mismo campo) |
| Fórmula backoff | `min(1 * 2^errors, 24)` horas | `min(base * factor^errors, max_hours)` (idéntico) |
| null → due | `last_scheduled_at=null → lastScheduledMs=0 → siempre due` | `last is None → due.append` |
| Cap errores | sin límite en query (filtra todos hasta 24h) | `consecutive_errors < max_errors` en SQL (skip en 5+) |
| Max por tick | `MAX_ACCOUNTS_PER_TICK = 20` | `scheduler_max_per_tick: int = 20` |
| Enqueue | `syncBankAccount()` inline | `enqueue_job("sync_bank_account_job")` → ARQ |
| Categorización al final | `processQueue()` call | ya se encola en `banking_sync.py` por cuenta |
| Secret check | `===` (JS) | `secrets.compare_digest()` en `internal.py` |

> **Nota:** el comentario del .js dice "4+ errores: 24h" pero la fórmula real da
> `1 * 2^4 = 16h` (no 24h). Python replica la fórmula, no el comentario.

### Deuda que se cierra en este commit
Ninguna P/BUG nueva — los grandes (P0-1, P0-2, BUG-1..4) ya están cerrados.

Se aprovecha el commit para fixear 6 TODOs menores que están en los archivos que
se tocan (§4 de este plan).

---

## 2. Archivos involucrados

### Nuevos
```
src/sky/worker/jobs/scheduled.py          ← cron job principal
tests/unit/test_scheduled_job.py          ← suite de tests
```

### Modificados
```
src/sky/core/config.py                    ← 3 settings nuevos
src/sky/worker/main.py                    ← registrar scheduled_sync_job + cron_jobs
src/sky/api/routers/internal.py           ← DEPRECATED comment + secrets.compare_digest
src/sky/domain/aria.py                    ← 2 TODOs (import random al top, rename param)
src/sky/worker/banking_sync.py            ← 2 TODOs (movements slice, asyncio.create_task)
src/sky/api/routers/chat.py               ← 1 TODO (BackgroundTasks)
docs/MIGRATION_13_PHASES.md              ← marcar Fase 9 ✅ Cerrada
```

---

## 3. Cambios detallados

### 3.1 `src/sky/core/config.py`

Agregar 3 settings bajo la sección `# ── Scheduler`:

```python
# ── Scheduler / cron ARQ (Fase 9) ────────────────────────────────────────────
scheduler_backoff_factor: int = 2        # factor exponencial por error (Node: BACKOFF_FACTOR=2)
scheduler_max_backoff_hours: float = 24.0  # techo del backoff (Node: MAX_BACKOFF_HOURS=24)
scheduler_max_per_tick: int = 20         # máx cuentas a encolar por tick (Node: MAX_ACCOUNTS_PER_TICK=20)
```

`scheduler_base_interval_hours`, `scheduler_due_threshold_hours` y
`scheduler_max_consecutive_errors` ya existen — no se tocan.

### 3.2 `src/sky/worker/jobs/scheduled.py` (NUEVO)

```
from __future__ import annotations
import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("scheduler")


async def scheduled_sync_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Cron ARQ: encola sync de cuentas elegibles con backoff exponencial.
    Corre cada hora a los :05 minutos. No lanza syncs directamente — solo
    encola 'sync_bank_account_job'; el advisory lock evita duplicados.
    """
    started_at = datetime.now(UTC)
    logger.info("scheduler_tick_start")

    # 1. Candidatos: status activo/error, auto_sync_enabled, bajo el umbral de errores.
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT ba.id, ba.user_id, ba.consecutive_errors, ba.last_scheduled_at
                  FROM public.bank_accounts ba
                  JOIN public.profiles p ON p.id = ba.user_id
                 WHERE ba.status IN ('active', 'error')
                   AND p.auto_sync_enabled = true
                   AND COALESCE(ba.consecutive_errors, 0) < :max_errors
                 ORDER BY ba.last_scheduled_at ASC NULLS FIRST
                 LIMIT :limit
            """),
            {
                "max_errors": settings.scheduler_max_consecutive_errors,
                "limit": settings.scheduler_max_per_tick * 3,  # sobre-pedimos para filtrar
            },
        )
        candidates = rs.mappings().all()

    if not candidates:
        logger.info("scheduler_no_candidates")
        return {"processed": 0}

    # 2. Filtro de backoff exponencial en Python (replica runScheduledSync de Node).
    now = datetime.now(UTC)
    due = []
    for acc in candidates:
        errors = int(acc["consecutive_errors"] or 0)
        interval_hours = min(
            settings.scheduler_base_interval_hours * (settings.scheduler_backoff_factor ** errors),
            settings.scheduler_max_backoff_hours,
        )
        last = acc["last_scheduled_at"]
        if last is None:
            due.append(acc)
        else:
            # last puede venir con tzinfo desde asyncpg; normalizamos.
            last_aware = last if last.tzinfo else last.replace(tzinfo=UTC)
            elapsed_hours = (now - last_aware).total_seconds() / 3600
            if elapsed_hours >= interval_hours:
                due.append(acc)

    to_process = due[: settings.scheduler_max_per_tick]
    logger.info(
        "scheduler_candidates",
        candidates=len(candidates), due=len(due), to_process=len(to_process),
    )

    if not to_process:
        return {"processed": 0, "skipped": len(candidates)}

    # 3. Encolar sync por cuenta. Advisory lock en banking_sync evita race.
    arq_pool = ctx["arq_pool"]
    ok, fail = 0, 0
    for acc in to_process:
        job = await arq_pool.enqueue_job(
            "sync_bank_account_job", str(acc["id"]), str(acc["user_id"]),
        )
        if job:
            ok += 1
        else:
            fail += 1

    elapsed_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
    logger.info("scheduler_tick_done", ok=ok, fail=fail, elapsed_ms=elapsed_ms)
    return {"processed": ok + fail, "ok": ok, "fail": fail, "elapsed_ms": elapsed_ms}
```

**Notas de diseño:**
- No corre sync inline — solo encola. El advisory lock en `banking_sync.py` garantiza que
  si el cron y un sync manual se pisan, uno simplemente devuelve `{"skipped": True}`.
- No llama `categorize_pending_job` al final: `banking_sync.py` lo encola por cada cuenta.
- `COALESCE(ba.consecutive_errors, 0) < :max_errors` excluye cuentas con 5+ errors en SQL
  (fail rápido, no en Python).

### 3.3 `src/sky/worker/main.py`

Tres cambios:

```python
# a) Agregar import al top
from arq import cron
from sky.worker.jobs.scheduled import scheduled_sync_job

# b) Agregar a functions list
functions = [
    sync_bank_account_job,
    sync_all_user_accounts_job,
    categorize_pending_job,
    scheduled_sync_job,       # ← NUEVO
]

# c) Reemplazar cron_jobs vacío
cron_jobs = [
    cron(scheduled_sync_job, minute=5),  # cada hora a los :05 min
]
```

`minute=5` → ARQ lo dispara a 00:05, 01:05, 02:05 … 23:05.

### 3.4 `src/sky/api/routers/internal.py`

Dos cambios:

**a) Fix TODO #6** — reemplazar `==` por `secrets.compare_digest`:
```python
import secrets
# ...
if not secret or not secrets.compare_digest(secret, settings.cron_secret):
    raise HTTPException(status_code=401, detail="Cron secret inválido")
```

**b) Marcar endpoint como DEPRECATED** — agregar comentario y campo en response:
```python
@router.post("/cron/sync-due")
async def cron_sync_due(request: Request) -> dict[str, int]:
    """
    [DEPRECATED — Fase 9] Endpoint externo de cron. Reemplazado por el cron
    nativo ARQ (scheduled_sync_job en worker/jobs/scheduled.py).
    Se mantiene por compatibilidad mientras se valida el cron ARQ.
    """
    ...
```

No se borra el endpoint (Opción A del HANDOVER). Se borra en Fase 11 durante cleanup pre-deploy.

---

## 4. TODOs menores a fixear en el mismo commit

| # | Archivo | Cambio |
|---|---------|--------|
| 1 | `domain/aria.py:93` | Mover `import random` del cuerpo de `_random_in_bucket` al top del módulo |
| 2 | `domain/aria.py:232` | Renombrar param `text` → `content` en `has_significant_content(text: str)` (shadowea `text` de sqlalchemy) |
| 3 | `worker/banking_sync.py:117` | Reemplazar `result.movements[:inserted]` → `result.movements` (todos los movimientos del result, no un slice por orden de inserción) |
| 4 | `worker/banking_sync.py:114-125` | Mover la llamada ARIA a `asyncio.create_task(_track_aria_events(...))` para no bloquear el sync en el loop |
| 5 | `api/routers/chat.py:24` | Migrar `asyncio.ensure_future` → `BackgroundTasks` de FastAPI |
| 6 | `api/routers/internal.py:22` | `==` → `secrets.compare_digest()` (ya cubierto en §3.4) |

### Detalle TODO 4 (banking_sync.py)

Extraer helper:
```python
async def _track_aria_events(user_id: str, movements: list[Any]) -> None:
    """Fire-and-forget: registrar eventos ARIA post-insert."""
    try:
        from sky.domain.aria import track_spending_event
        anon_profile = await _load_anon_profile(user_id)
        for m in movements:
            await track_spending_event(
                anon_profile,
                {"amount": m.amount_clp, "category": "other", "source": "bank_sync"},
                user_id,
            )
    except Exception as exc:
        logger.warning("aria_track_failed", error=str(exc))
```

En `sync_bank_account`:
```python
if settings.sync_aria_enabled and inserted > 0:
    asyncio.create_task(_track_aria_events(user_id, result.movements))
```

Se necesita `import asyncio` al top de `banking_sync.py` (ya debería estar, verificar).

### Detalle TODO 5 (chat.py)

```python
from fastapi import APIRouter, BackgroundTasks, Depends, Request

@router.post("", response_model=ChatTextResponse | ProposeChallenge | NavigationResponse)
async def chat_endpoint(
    body: ChatRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(require_user_id),
) -> ChatTextResponse | ProposeChallenge | NavigationResponse:
    from sky.domain.mr_money import MrMoney
    response = await MrMoney().respond(user_id=user_id, message=body.message)
    background_tasks.add_task(_fire_aria, user_id, body.message, response)
    return response
```

Eliminar `import asyncio` si ya no se usa en el archivo.

---

## 5. Tests — `tests/unit/test_scheduled_job.py` (NUEVO)

### Casos de test

| # | Nombre | Qué verifica |
|---|--------|-------------|
| 1 | `test_no_candidates_returns_zero` | Query vacía → `{"processed": 0}` sin enqueue |
| 2 | `test_all_due_no_last_scheduled` | last_scheduled_at=None → siempre due → N encolas |
| 3 | `test_backoff_filters_recent_account` | Cuenta con 1 error sincronizada hace 1h → NO due (intervalo = 2h) |
| 4 | `test_backoff_allows_overdue_account` | Cuenta con 1 error sincronizada hace 3h → SÍ due |
| 5 | `test_max_per_tick_limits_enqueue` | 200 due → solo encola `scheduler_max_per_tick` (20) |
| 6 | `test_enqueue_returns_none_counts_fail` | arq_pool.enqueue_job devuelve None → fail += 1 |
| 7 | `test_backoff_exponential_3_errors` | 3 errors, intervalo = 8h, 7h elapsed → NO due |
| 8 | `test_backoff_max_cap_respected` | 10 errors, cap=24h → no espera 1024h |

### Patrón de mocking (consistente con `test_sync_job.py`)

```python
def _make_engine_with_candidates(rows: list[dict]) -> MagicMock:
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = rows  # .mappings().all()
    mock_rs = MagicMock()
    mock_rs.mappings.return_value = mock_mappings

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx
    return mock_engine
```

---

## 6. Definition of Done (gates §3)

Todos deben pasar con exit code 0 antes del commit:

- [ ] `ruff check src/sky/ tests/` → 0 errores
- [ ] `mypy src/sky/` → 0 errores
- [ ] `pytest tests/ -v --cov=src/sky/worker/jobs/scheduled --cov-report=term-missing`
      → todos los tests pasan, coverage ≥ 75% en `scheduled.py`
- [ ] `pytest tests/ -v` completo → ≥ 275 passed (baseline), 1 skipped
- [ ] `arq sky.worker.main.WorkerSettings` arranca limpio (gate manual con Redis local)
      → logs muestran `worker_ready` sin errores de import

---

## 7. Mensaje de commit

```
Fase 9 cerrada: scheduler ARQ cron con backoff exponencial

- scheduled_sync_job: cron ARQ que corre cada hora (:05 min), encola
  sync_bank_account_job por cuenta elegible con backoff exponencial.
  Replica runScheduledSync() de Node (paridad de lógica y backoff).
- worker/main.py: registra scheduled_sync_job en functions + cron_jobs.
- config.py: scheduler_backoff_factor=2, max_backoff_hours=24, max_per_tick=100.
- internal.py: /cron/sync-due marcado DEPRECATED + secrets.compare_digest().
- 6 TODOs menores: aria.py (import random, rename param), banking_sync.py
  (asyncio.create_task para ARIA, movements slice), chat.py (BackgroundTasks).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## 8. Update final — `docs/MIGRATION_13_PHASES.md`

Agregar bajo la sección FASE 9:

```markdown
### Estado: ✅ Cerrada (2026-05-06)

### Archivos finales
- `src/sky/worker/jobs/scheduled.py`    (scheduled_sync_job — NUEVO)
- `src/sky/worker/main.py`              (functions + cron_jobs)
- `src/sky/core/config.py`              (3 settings scheduler)
- `src/sky/api/routers/internal.py`     (DEPRECATED + secrets.compare_digest)
- `tests/unit/test_scheduled_job.py`   (8 casos — NUEVO)
- TODOs menores en aria.py, banking_sync.py, chat.py

### Gates verificados
- [x] ruff check → 0
- [x] mypy → 0
- [x] pytest → ≥ 275 passed, coverage ≥ 75% en scheduled.py
- [ ] arq arranca limpio (gate manual — pendiente)
```

---

## 9. Siguiente fase

**Fase 10** — Observabilidad (Prometheus, Sentry, `/api/health/deep`). Cierra P2-1..4.
