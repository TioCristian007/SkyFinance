# FASE 12 — Audit Purge + RLS Audit + audit/me + Customer Data Export: Plan de cierre

> Plan-first obligatorio. Sin plan aprobado no se escribe código.
> Template: `FASE11_CLOSURE_PLAN.md`.
> Fecha: 2026-05-11
> Doctrina: production-grade desde día 1. Verificación de schema real antes de codear.
> **Aprobado con 4 ajustes (2026-05-11):**
> 1. `process_export_request_job`: `max_tries=1` — ARQ no auto-retry; si falla el user re-pide.
> 2. `audit_log_retention_days`: setting configurable en `config.py` (default 90); SQL usa `:days` bind param.
> 3. Purge en batches de 10 000 con loop (max 50 iter) para evitar lock prolongado.
> 4. Test explícito: worker failure → status='failed', error sanitizado, delivered_at=NULL, storage no tocado.

---

## 0. Outputs de verificación pre-plan (OBLIGATORIO)

Ejecutados con `scripts/verify_fase12_schema.py` contra producción:

### 0.1 pg_cron

```
name='pg_cron'  default_version='1.6.4'  installed_version=None
RESULTADO: pg_cron disponible pero NO instalado
```

**Decisión**: purge va en `worker/jobs/audit_purge.py` con cron ARQ daily 03:00 UTC.
La migración 005 crea la función SQL `purge_audit_log_old()` para invocación manual opcional,
pero el scheduling real es responsabilidad del worker ARQ, no de pg_cron.

### 0.2 Schema real `data_export_requests`

```
id               uuid           NOT NULL  gen_random_uuid()
user_id          uuid           NOT NULL  None
status           text           NOT NULL  default='pending'
format           text           NOT NULL  default='json'
download_url     text           YES       None
expires_at       timestamptz    YES       None
requested_at     timestamptz    NOT NULL  default=now()
delivered_at     timestamptz    YES       None
```

**Match exacto** con el scope descrito. No hay campos ocultos ni faltantes.

### 0.3 Schema real `earned_badges`

```
id              uuid           NOT NULL
user_id         uuid           NOT NULL
badge_id        text           NOT NULL
earned_at       timestamptz    YES   default=now()
```

### 0.4 Información adicional relevante

- **challenge_states** (la tabla real es `challenge_states`, NO `challenges`):
  `id, user_id, challenge_id, status, started_at, completed_at, points_earned, created_at`
- **transactions**: sin columnas encrypted (las encrypted_rut/pass están en `bank_accounts`)
- **Supabase Storage buckets**: NINGUNO creado aún → "data-exports" bucket es pre-requisito manual
- **supabase-py 2.28.3** instalado → storage client sync disponible
- **audit_log RLS**: dos policies `USING(false)` → servicio solo via service_role (correcto)

---

## 1. Contexto

### Objetivo

Cuatro entregables de seguridad + compliance en un solo commit:

1. **Audit log purge >90 días** — ARQ cron diario 03:00 UTC + función SQL idempotente.
2. **RLS audit completo** — script que verifica RLS en todas las tablas public.* y aria.*.
3. **GET /api/audit/me** — endpoint para que un usuario lea su propio historial de auditoría.
4. **Customer data export (Ley 19.628 art 11)** — flujo completo: solicitud API + worker ZIP + Supabase Storage.

### Deuda que se cierra

| ID | Descripción |
|----|-------------|
| TODO §4 (SECURITY.md) | Sección "Audit log → Retención: 90 días (TODO trigger Fase 12)" |
| TODO §8 (HANDOVER §3.3) | Integration tests con Redis (rate limiter en tests) |
| R8 (parcial) | RLS audit formal como script runnable |

### Lo que esta fase NO hace

- NO toca `backend/` (Node, producción viva).
- NO instala pg_cron (requiere Supabase Pro upgrade manual).
- NO crea el bucket "data-exports" en Supabase Storage (pre-requisito manual del usuario).
- NO implementa k-anonymity formal en aria.* (diferido post-Fase 13).
- NO implementa 2FA usuario (diferido post-cutover).

---

## 2. Pre-requisito de deploy (ANTES de activar en Railway)

### 2.1 Crear bucket "data-exports" en Supabase

Pasos en Supabase Dashboard > Storage > New Bucket:
- Name: `data-exports`
- Public: NO (private)
- File size limit: 50 MB
- Allowed MIME types: `application/zip`

Sin este bucket, `process_export_request_job` falla al intentar upload.
El job captura el error y actualiza `status='failed'` en `data_export_requests`.

### 2.2 Aplicar migration 005

```sql
-- Copiar contenido de migrations/005_audit_log_purge.sql en SQL Editor Supabase.
```

Verificar:
```sql
SELECT proname FROM pg_proc WHERE proname = 'purge_audit_log_old';
-- Debe devolver: purge_audit_log_old
```

---

## 3. Archivos involucrados

### Nuevos (13)

```
migrations/005_audit_log_purge.sql
src/sky/worker/jobs/audit_purge.py
src/sky/api/routers/audit.py
src/sky/api/schemas/audit.py
src/sky/api/routers/account.py
src/sky/api/schemas/account.py
src/sky/worker/jobs/data_export.py
scripts/audit_rls_policies.py
tests/unit/test_audit_purge.py
tests/integration/test_audit_endpoint.py
tests/integration/test_data_export.py
(scripts/verify_fase12_schema.py  ← ya creado en preparación)
```

### Modificados (5)

```
src/sky/worker/main.py              (registrar audit_purge_job + cron daily 03:00 UTC)
src/sky/api/main.py                 (montar audit.router + account.router)
docs/SECURITY.md                    (secciones: Data retention, RLS procedure, Data export)
docs/MIGRATION_13_PHASES.md         (marcar Fase 12 cerrada)
tests/conftest.py                   (fix TODO #8: monkeypatch rate limiter para tests)
```

---

## 4. Cambios detallados

### 4.1 `migrations/005_audit_log_purge.sql` (NUEVO)

```sql
-- Fase 12: función de purge del audit_log (retención 90 días)
-- pg_cron NO está instalado → esta función la invoca el worker ARQ.
-- Puede invocarse manualmente también: SELECT public.purge_audit_log_old();

CREATE OR REPLACE FUNCTION public.purge_audit_log_old()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  deleted_count integer;
BEGIN
  DELETE FROM public.audit_log
  WHERE occurred_at < NOW() - INTERVAL '90 days';
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$$;

COMMENT ON FUNCTION public.purge_audit_log_old() IS
  'Elimina registros de audit_log con occurred_at < NOW() - 90 días. '
  'Invocado por el worker ARQ diariamente a las 03:00 UTC. '
  'IDEMPOTENT: si no hay nada que purgar, retorna 0.';
```

**Seguridad**: `SECURITY DEFINER` permite que el caller sin permiso DELETE en audit_log
ejecute la función. Aceptable porque la función solo hace DELETE WHERE occurred_at < 90d.

**NO se loguea en audit_log**: el purge NO llama a `log_event()` — evitar recursión filosófica
(quién audita al auditor). Solo loguea en structlog del worker.

### 4.2 `src/sky/worker/jobs/audit_purge.py` (NUEVO)

```python
"""sky.worker.jobs.audit_purge — Purge diario del audit log (retención 90 días)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("audit_purge")


async def audit_purge_job(ctx: dict[str, Any]) -> dict[str, int]:
    """
    Elimina registros de public.audit_log con occurred_at < NOW() - 90 días.

    Cron ARQ: daily 03:00 UTC. Fire via worker ARQ, no pg_cron (no instalado).
    NO llama a log_event() — el purge no se auto-audita.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT public.purge_audit_log_old()"))
        deleted = result.scalar() or 0
    logger.info("audit_purge_completed", deleted=deleted, retention_days=90)
    return {"deleted": deleted}
```

### 4.3 `src/sky/worker/main.py` (MODIFICAR)

Agregar `audit_purge_job` a functions y cron_jobs:

```python
from sky.worker.jobs.audit_purge import audit_purge_job

# En WorkerSettings.functions:
functions = [
    sync_bank_account_job,
    sync_all_user_accounts_job,
    categorize_pending_job,
    scheduled_sync_job,
    audit_purge_job,            # Fase 12
]

# En WorkerSettings.cron_jobs:
cron_jobs = [
    cron(scheduled_sync_job, minute=5),           # cada hora a los :05
    cron(audit_purge_job, hour=3, minute=0),      # daily 03:00 UTC
]
```

### 4.4 `src/sky/api/schemas/audit.py` (NUEVO)

```python
"""sky.api.schemas.audit — Schemas Pydantic para /api/audit/me."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    event_type: str
    outcome: str
    resource_type: str | None
    resource_id: str | None
    detail: dict | None
    occurred_at: datetime


class AuditEventListResponse(BaseModel):
    events: list[AuditEventOut]
    total: int
    limit: int
    offset: int
```

### 4.5 `src/sky/api/routers/audit.py` (NUEVO)

```python
"""sky.api.routers.audit — GET /api/audit/me (lectura propia del audit log)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text

from sky.api.deps import require_user_id
from sky.api.middleware.rate_limit import limiter
from sky.api.schemas.audit import AuditEventListResponse, AuditEventOut
from sky.core.audit import _ACTION_MAP, _hash
from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("audit_router")
router = APIRouter(prefix="/api/audit", tags=["audit"])

# Valores de event_type conocidos (primeras partes de los tuples en _ACTION_MAP)
_KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    event_type for event_type, _ in _ACTION_MAP.values()
)


@router.get("/me", response_model=AuditEventListResponse)
@limiter.limit(f"{settings.api_rate_limit_per_minute}/minute")
async def get_audit_me(
    request: Request,
    user_id: str = Depends(require_user_id),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    event_type: str | None = Query(default=None),
) -> AuditEventListResponse:
    """
    Retorna el historial de eventos de auditoría del usuario autenticado.

    El backend calcula user_hash = sha256(user_id + AUDIT_LOG_SALT).
    Nunca expone el user_hash al cliente — es un detalle de implementación interno.
    """
    if event_type and event_type not in _KNOWN_EVENT_TYPES:
        # Valor desconocido — retornar lista vacía en lugar de error
        # (no revelar la estructura interna del mapa)
        return AuditEventListResponse(events=[], total=0, limit=limit, offset=offset)

    user_hash = _hash(user_id)

    engine = get_engine()
    async with engine.connect() as conn:
        # Query total
        count_q = "SELECT COUNT(*) FROM public.audit_log WHERE user_hash = :hash"
        params: dict = {"hash": user_hash}
        if event_type:
            count_q += " AND event_type = :event_type"
            params["event_type"] = event_type
        total_result = await conn.execute(text(count_q), params)
        total = total_result.scalar() or 0

        # Query data
        data_q = (
            "SELECT event_type, outcome, resource_type, resource_id, detail, occurred_at "
            "FROM public.audit_log WHERE user_hash = :hash"
        )
        if event_type:
            data_q += " AND event_type = :event_type"
        data_q += " ORDER BY occurred_at DESC LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset

        data_result = await conn.execute(text(data_q), params)
        rows = data_result.fetchall()

    events = [
        AuditEventOut(
            event_type=row[0],
            outcome=row[1],
            resource_type=row[2],
            resource_id=str(row[3]) if row[3] else None,
            detail=row[4] if row[4] else {},
            occurred_at=row[5],
        )
        for row in rows
    ]

    return AuditEventListResponse(events=events, total=total, limit=limit, offset=offset)
```

**Invariante de seguridad**:
- El user_hash se calcula en el backend; nunca se expone al cliente.
- El filtro `WHERE user_hash = :hash` usa exact match, sin LIKE ni wildcards → no hay riesgo de cross-user leakage.
- Parámetros son bind params → sin SQL injection.

### 4.6 `src/sky/api/schemas/account.py` (NUEVO)

```python
"""sky.api.schemas.account — Schemas para /api/account/export-request."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DataExportRequestCreate(BaseModel):
    format: Literal["json", "csv"] = "json"


class DataExportRequestOut(BaseModel):
    id: str
    status: str
    format: str
    download_url: str | None
    expires_at: datetime | None
    requested_at: datetime
    delivered_at: datetime | None
```

### 4.7 `src/sky/api/routers/account.py` (NUEVO)

```python
"""sky.api.routers.account — Customer data export (Ley 19.628 art 11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from sky.api.deps import require_user_id
from sky.api.middleware.rate_limit import limiter
from sky.api.schemas.account import DataExportRequestCreate, DataExportRequestOut
from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("account_router")
router = APIRouter(prefix="/api/account", tags=["account"])


@router.post("/export-request", response_model=DataExportRequestOut, status_code=201)
@limiter.limit("5/minute")  # abuse prevention — más restrictivo que el default
async def create_export_request(
    body: DataExportRequestCreate,
    request: Request,
    user_id: str = Depends(require_user_id),
) -> DataExportRequestOut:
    """
    Crea solicitud de exportación de datos del usuario (Ley 19.628 art 11).
    Encola job de procesamiento en el worker.
    expires_at = NOW() + 7 días (tiempo de disponibilidad del ZIP).
    """
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                INSERT INTO public.data_export_requests (user_id, format, expires_at)
                VALUES (:user_id, :format, NOW() + INTERVAL '7 days')
                RETURNING id, user_id, status, format, download_url,
                          expires_at, requested_at, delivered_at
            """),
            {"user_id": user_id, "format": body.format},
        )
        row = result.fetchone()

    # Encolar job en el worker (fire-and-forget)
    arq_pool = request.app.state.arq_pool
    await arq_pool.enqueue_job("process_export_request_job", str(row[0]))
    logger.info("export_request_created", request_id=str(row[0]), format=body.format)

    return DataExportRequestOut(
        id=str(row[0]),
        status=row[2],
        format=row[3],
        download_url=row[4],
        expires_at=row[5],
        requested_at=row[6],
        delivered_at=row[7],
    )


@router.get("/export-request", response_model=list[DataExportRequestOut])
@limiter.limit(f"{settings.api_rate_limit_per_minute}/minute")
async def list_export_requests(
    request: Request,
    user_id: str = Depends(require_user_id),
) -> list[DataExportRequestOut]:
    """Lista los últimos 10 export requests del usuario."""
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT id, user_id, status, format, download_url,
                       expires_at, requested_at, delivered_at
                FROM public.data_export_requests
                WHERE user_id = :user_id
                ORDER BY requested_at DESC LIMIT 10
            """),
            {"user_id": user_id},
        )
        rows = result.fetchall()

    return [
        DataExportRequestOut(
            id=str(r[0]), status=r[2], format=r[3], download_url=r[4],
            expires_at=r[5], requested_at=r[6], delivered_at=r[7],
        )
        for r in rows
    ]


@router.get("/export-request/{request_id}", response_model=DataExportRequestOut)
@limiter.limit(f"{settings.api_rate_limit_per_minute}/minute")
async def get_export_request(
    request_id: str,
    request: Request,
    user_id: str = Depends(require_user_id),
) -> DataExportRequestOut:
    """Poll status de un export request específico."""
    from sky.core.errors import NotFoundError

    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT id, user_id, status, format, download_url,
                       expires_at, requested_at, delivered_at
                FROM public.data_export_requests
                WHERE id = :request_id AND user_id = :user_id
            """),
            {"request_id": request_id, "user_id": user_id},
        )
        row = result.fetchone()

    if not row:
        raise NotFoundError("Export request no encontrado")

    return DataExportRequestOut(
        id=str(row[0]), status=row[2], format=row[3], download_url=row[4],
        expires_at=row[5], requested_at=row[6], delivered_at=row[7],
    )
```

### 4.8 `src/sky/worker/jobs/data_export.py` (NUEVO)

```python
"""sky.worker.jobs.data_export — Genera ZIP con datos del usuario (Ley 19.628)."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from sky.core.audit import _hash, log_event
from sky.core.db import get_aria_client, get_engine
from sky.core.logging import get_logger

logger = get_logger("data_export")

BUCKET = "data-exports"


async def process_export_request_job(ctx: dict[str, Any], request_id: str) -> dict[str, Any]:
    """
    Genera ZIP con datos del usuario y sube a Supabase Storage.
    Actualiza data_export_requests con status=completed y download_url (signed URL 7d).

    Datos incluidos: transactions, goals, challenge_states, earned_badges, audit_log propio.
    Datos EXCLUIDOS: bank_accounts (contiene encrypted_rut/pass), perfiles, secrets.
    """
    engine = get_engine()

    async with engine.connect() as conn:
        req_result = await conn.execute(
            text(
                "SELECT id, user_id, format FROM public.data_export_requests "
                "WHERE id = :id"
            ),
            {"id": request_id},
        )
        req = req_result.fetchone()

    if not req:
        logger.error("export_request_not_found", request_id=request_id)
        return {"error": "not_found"}

    user_id = str(req[1])
    export_format = req[2]

    try:
        # ── Recopilar datos ───────────────────────────────────────────────
        data = await _collect_user_data(engine, user_id)

        # ── Generar ZIP ───────────────────────────────────────────────────
        zip_bytes = _build_zip(data, export_format)
        size_bytes = len(zip_bytes)

        # ── Subir a Supabase Storage ──────────────────────────────────────
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        file_path = f"{user_id[:8]}/{request_id}_{timestamp}.zip"
        storage_client = get_aria_client()

        await asyncio.to_thread(
            storage_client.storage.from_(BUCKET).upload,
            file_path, zip_bytes, {"contentType": "application/zip"},
        )
        signed_result = await asyncio.to_thread(
            storage_client.storage.from_(BUCKET).create_signed_url,
            file_path, 604800,  # 7 días en segundos
        )
        download_url = signed_result.full_path if hasattr(signed_result, "full_path") \
            else signed_result.get("signedURL", "")

        # ── Actualizar registro ───────────────────────────────────────────
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE public.data_export_requests
                    SET status='completed', delivered_at=NOW(), download_url=:url
                    WHERE id=:id
                """),
                {"url": download_url, "id": request_id},
            )

        await log_event(
            action="export.completed",
            user_id=user_id,
            resource_type="data_export",
            resource_id=request_id,
            metadata={"format": export_format, "size_bytes": size_bytes},
        )
        logger.info("export_completed", request_id=request_id, size_bytes=size_bytes)
        return {"status": "completed", "size_bytes": size_bytes}

    except Exception as exc:
        error_type = type(exc).__name__
        logger.error("export_failed", request_id=request_id, error=error_type)

        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE public.data_export_requests
                    SET status='failed'
                    WHERE id=:id
                """),
                {"id": request_id},
            )
        return {"status": "failed", "error": error_type}


async def _collect_user_data(engine: Any, user_id: str) -> dict[str, list[dict]]:
    """Recopila todos los datos del usuario para exportar. Excluye bank_accounts."""
    user_hash = _hash(user_id)

    async with engine.connect() as conn:
        # transactions — sin encrypted fields (esos están en bank_accounts)
        txn_result = await conn.execute(
            text("""
                SELECT id, amount, category, description, date, created_at,
                       bank_account_id, external_id, source, movement_source,
                       raw_description, categorization_status
                FROM public.transactions WHERE user_id = :uid ORDER BY date DESC
            """),
            {"uid": user_id},
        )
        transactions = [dict(row._mapping) for row in txn_result.fetchall()]

        # goals
        goals_result = await conn.execute(
            text(
                "SELECT id, title, target_amount, saved_amount, deadline, icon, type, "
                "status, created_at, completed_at FROM public.goals WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        goals = [dict(row._mapping) for row in goals_result.fetchall()]

        # challenge_states (la tabla real — NO 'challenges')
        cs_result = await conn.execute(
            text(
                "SELECT id, challenge_id, status, started_at, completed_at, points_earned, "
                "created_at FROM public.challenge_states WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        challenge_states = [dict(row._mapping) for row in cs_result.fetchall()]

        # earned_badges
        badges_result = await conn.execute(
            text(
                "SELECT id, badge_id, earned_at FROM public.earned_badges WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        earned_badges = [dict(row._mapping) for row in badges_result.fetchall()]

        # audit_log — filtrado por user_hash (sin user_id raw en la tabla)
        audit_result = await conn.execute(
            text("""
                SELECT event_type, outcome, resource_type, resource_id, detail, occurred_at
                FROM public.audit_log WHERE user_hash = :hash ORDER BY occurred_at DESC
            """),
            {"hash": user_hash},
        )
        audit_log = [dict(row._mapping) for row in audit_result.fetchall()]

    # Serializar tipos no-JSON (uuid, datetime, date)
    return {
        "transactions": _serialize(transactions),
        "goals": _serialize(goals),
        "challenge_states": _serialize(challenge_states),
        "earned_badges": _serialize(earned_badges),
        "audit_log": _serialize(audit_log),
    }


def _serialize(rows: list[dict]) -> list[dict]:
    """Convierte uuid/datetime/date a str para serialización JSON/CSV."""
    import uuid
    from datetime import date, datetime

    def _val(v: Any) -> Any:
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    return [{k: _val(v) for k, v in row.items()} for row in rows]


def _build_zip(data: dict[str, list[dict]], export_format: str) -> bytes:
    """Genera ZIP con los datasets en el formato especificado (json o csv)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, rows in data.items():
            if export_format == "csv":
                content = _to_csv(rows)
                zf.writestr(f"{name}.csv", content)
            else:
                content = json.dumps(rows, ensure_ascii=False, indent=2, default=str)
                zf.writestr(f"{name}.json", content)
    return buf.getvalue()


def _to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()
```

**Invariantes de seguridad en el data export**:
- `bank_accounts` está explícitamente excluido → `encrypted_rut`/`encrypted_pass` nunca se exportan.
- `audit_log` se filtra por `user_hash` (no por `user_id` raw — la tabla no tiene `user_id`).
- El job corre en el worker → API nunca importa ni ejecuta lógica de storage.
- Signed URL TTL = 7 días, alineado con `expires_at` en `data_export_requests`.

### 4.9 `scripts/audit_rls_policies.py` (NUEVO)

```python
"""
scripts/audit_rls_policies.py — Verifica RLS en todas las tablas public.* y aria.*.

Conecta con service_role. SOLO SELECT — nunca modifica policies.

Uso:
    cd backend-python
    .venv\\Scripts\\activate
    python scripts/audit_rls_policies.py

Exit 0 = todas las tablas tienen RLS habilitado y policies restrictivas.
Exit 1 = hay tablas sin RLS o con policies potencialmente permisivas.

Output: report markdown impreso en stdout.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from sky.core.db import get_engine


async def main() -> int:
    engine = get_engine()
    issues: list[str] = []

    async with engine.connect() as conn:
        # Tablas en public y aria
        tables_result = await conn.execute(
            text("""
                SELECT t.schemaname, t.tablename, c.relrowsecurity
                FROM pg_tables t
                JOIN pg_class c ON c.relname = t.tablename
                JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.schemaname
                WHERE t.schemaname IN ('public', 'aria')
                ORDER BY t.schemaname, t.tablename
            """)
        )
        tables = tables_result.fetchall()

        # Policies por tabla
        policies_result = await conn.execute(
            text("""
                SELECT schemaname, tablename, policyname, cmd, roles, qual
                FROM pg_policies
                WHERE schemaname IN ('public', 'aria')
                ORDER BY schemaname, tablename, policyname
            """)
        )
        policies_by_table: dict[tuple, list] = {}
        for row in policies_result.fetchall():
            key = (row[0], row[1])
            policies_by_table.setdefault(key, []).append(row)

    print("\n# RLS Audit Report — Sky Finance")
    print(f"\n## Tablas auditadas: {len(tables)}\n")
    print(f"| Schema | Tabla | RLS habilitado | N policies | Evaluacion |")
    print(f"|--------|-------|----------------|------------|------------|")

    for schema, table, rls_enabled in tables:
        key = (schema, table)
        table_policies = policies_by_table.get(key, [])
        n_policies = len(table_policies)

        # Evaluar si hay al menos una policy restrictiva (USING(false))
        has_restrictive = any(
            p[5] == "false" or p[5] == "(false)"
            for p in table_policies
        )
        # Schema aria.* nunca debe tener policies para anon/authenticated
        aria_issue = schema == "aria" and any(
            "anon" in str(p[4]) or "authenticated" in str(p[4])
            for p in table_policies
        )

        if not rls_enabled:
            eval_str = "FAIL: RLS disabled"
            issues.append(f"{schema}.{table}: RLS not enabled")
        elif schema == "aria" and aria_issue:
            eval_str = "FAIL: aria.* expuesto a anon/authenticated"
            issues.append(f"{schema}.{table}: expuesto a clientes")
        elif n_policies == 0:
            eval_str = "WARN: RLS enabled pero sin policies (deny all implícito)"
        elif has_restrictive:
            eval_str = "OK: policy USING(false)"
        else:
            eval_str = "REVIEW: policies sin USING(false) — revisar manualmente"

        rls_str = "SI" if rls_enabled else "NO"
        print(f"| {schema} | {table} | {rls_str} | {n_policies} | {eval_str} |")

    print(f"\n## Resumen")
    if issues:
        print(f"\nISSUES ({len(issues)}):")
        for issue in issues:
            print(f"  - {issue}")
        print("\nExit 1 — hay tablas con problemas de RLS.")
        return 1
    else:
        print("\nTodas las tablas tienen RLS configurado. Exit 0.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

### 4.10 `src/sky/api/main.py` (MODIFICAR — agregar routers)

```python
from sky.api.routers import (
    audit,     # Fase 12
    account,   # Fase 12
    banking,
    challenges,
    chat,
    goals,
    health,
    internal,
    simulate,
    summary,
    transactions,
    webhooks,
)

# En la sección de routes:
app.include_router(audit.router)    # GET /api/audit/me
app.include_router(account.router)  # POST/GET /api/account/export-request
```

### 4.11 `tests/conftest.py` (MODIFICAR — fix TODO #8)

Agregar monkeypatch para slowapi rate limiter. Permite correr integration tests sin Redis real.
Usa `limits` memory storage, el mismo backend que slowapi en dev:

```python
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

# ... imports existentes ...

# Fixture autouse para tests de integración — evita requerir Redis real
@pytest.fixture(autouse=True)
def _memory_rate_limit(monkeypatch):
    """Redirige slowapi a in-memory storage para tests (evita necesitar Redis real)."""
    try:
        from limits.storage import MemoryStorage
        from sky.api.middleware.rate_limit import limiter
        monkeypatch.setattr(limiter, "_storage", MemoryStorage())
    except Exception:
        pass  # Si no aplica (tests que no usan la API), ignorar silenciosamente
```

### 4.12 `docs/SECURITY.md` (MODIFICAR)

Agregar 3 secciones después de la sección actual §9:

**§10 Data retention**:
- audit_log: 90 días. Purge via ARQ cron diario 03:00 UTC (`audit_purge_job`). Función: `public.purge_audit_log_old()`.
- data_export_requests: download_url signed URL expira en 7 días.

**§11 RLS verification procedure**:
- Script: `python scripts/audit_rls_policies.py`
- Expected output: todas las tablas con RLS habilitado y policy `USING(false)`.
- Correr antes de cada deploy de migración SQL.
- Exit 1 = bloquear deploy.

**§12 Customer data export (Ley 19.628 art 11)**:
- Endpoint: `POST /api/account/export-request`
- Worker genera ZIP con: transactions, goals, challenge_states, earned_badges, audit_log propio.
- Excluidos: bank_accounts (encrypted_rut/pass), perfiles.
- Formato: JSON o CSV.
- Disponibilidad: 7 días via Supabase Storage signed URL.
- Bucket: "data-exports" (privado).

---

## 5. Tests

### 5.1 `tests/unit/test_audit_purge.py` — 4+ casos

| # | Nombre | Qué verifica |
|---|--------|-------------|
| 1 | `test_audit_purge_returns_deleted_count` | mock engine, función SQL retorna 5 → job retorna `{"deleted": 5}` |
| 2 | `test_audit_purge_idempotent_zero` | función retorna 0 → job retorna `{"deleted": 0}` sin error |
| 3 | `test_audit_purge_no_log_event_called` | job no llama `log_event` (no auto-audit) |
| 4 | `test_audit_purge_db_error_propagates` | DB lanza excepción → job la propaga (no swallow) |

### 5.2 `tests/integration/test_audit_endpoint.py` — 5 casos

| # | Nombre | Qué verifica |
|---|--------|-------------|
| 1 | `test_get_audit_me_no_jwt_returns_401` | GET sin token → 401 |
| 2 | `test_get_audit_me_empty_returns_list` | JWT válido, user sin events → `{"events": [], "total": 0}` |
| 3 | `test_get_audit_me_returns_events` | mock audit_log rows → response correcta |
| 4 | `test_get_audit_me_event_type_filter` | `?event_type=sync` → solo eventos sync |
| 5 | `test_get_audit_me_unknown_event_type` | `?event_type=unknown` → lista vacía (no error) |

Tests de integración usan `httpx.AsyncClient(app=app)` con mocked engine/DB.

### 5.3 `tests/integration/test_data_export.py` — 5 casos

| # | Nombre | Qué verifica |
|---|--------|-------------|
| 1 | `test_create_export_no_jwt_returns_401` | POST sin token → 401 |
| 2 | `test_create_export_creates_pending` | POST válido → 201, status='pending', encola job |
| 3 | `test_export_job_generates_zip` | mock engine + mock storage → ZIP con archivos JSON |
| 4 | `test_export_excludes_encrypted_fields` | datos exportados no contienen encrypted_rut/pass |
| 5 | `test_get_export_request_status_poll` | GET /{id} → status correcto |

Usar `monkeypatch` para Supabase Storage client (no necesita storage real para tests).

---

## 6. Definition of Done (gates)

Todos con exit code 0 antes del commit:

- [ ] `ruff check src/sky/ tests/ scripts/` → 0 errores
- [ ] `mypy src/sky/` → 0 errores
- [ ] `pytest tests/ -v` → ≥ 333 baseline + nuevos (esperado ~350)
- [ ] coverage `worker/jobs/audit_purge.py` ≥ 85%
- [ ] coverage `api/routers/audit.py` ≥ 75%
- [ ] coverage `api/routers/account.py` ≥ 75%
- [ ] coverage `worker/jobs/data_export.py` ≥ 75%
- [ ] `python scripts/audit_rls_policies.py` → exit 0, report sin FAIL
- [ ] Migración 005 aplicada en Supabase: `SELECT proname FROM pg_proc WHERE proname = 'purge_audit_log_old'` devuelve 1 fila
- [ ] `uvicorn sky.api.main:app` arranca + `/api/health` → 200

---

## 7. Mensaje de commit

```
Fase 12 cerrada: audit purge + RLS audit + audit/me + customer data export (Ley 19.628)

Entregables:
- migrations/005_audit_log_purge.sql: función purge_audit_log_old() (retención 90 días)
- worker/jobs/audit_purge.py: ARQ job daily 03:00 UTC (pg_cron no instalado)
- worker/main.py: audit_purge_job en functions + cron_jobs
- scripts/audit_rls_policies.py: audit RLS public.* y aria.* (solo SELECT, exit 1 si issues)
- api/routers/audit.py + schemas/audit.py: GET /api/audit/me paginado con filtro event_type
  user_hash calculado en backend — nunca expuesto al cliente
- api/routers/account.py + schemas/account.py: POST/GET /api/account/export-request
  rate limit 5/min (abuse prevention)
- worker/jobs/data_export.py: genera ZIP (json/csv), sube a Supabase Storage bucket
  "data-exports", signed URL 7d. Excluye encrypted_rut/pass explícitamente.
  Tablas: transactions, goals, challenge_states, earned_badges, audit_log own.
- docs/SECURITY.md: secciones Data retention + RLS procedure + Customer data export
- tests/conftest.py: fix TODO #8 — monkeypatch slowapi memory storage para integration tests
- tests: 17+ nuevos casos en test_audit_purge, test_audit_endpoint, test_data_export

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## 8. Update `docs/MIGRATION_13_PHASES.md`

```markdown
## FASE 12 — Migraciones SQL e índices faltantes

### Estado: ✅ Cerrada (2026-05-11)

### Nota
Scope real de Fase 12 expandido vs. el plan original (que era solo índices SQL).
Fase 11 adelantó el audit_log (R18), dejando Fase 12 disponible para:
  - Audit purge (retención 90 días)
  - RLS audit script formal
  - GET /api/audit/me (lectura propia)
  - Customer data export (Ley 19.628)
Todos los índices SQL de BUG-2 se cerraron en Fase 6 (migration 002).

### Deuda cerrada
- TODO §4 SECURITY.md: retención 90 días implementada (audit_purge_job)
- TODO #8 HANDOVER: conftest.py monkeypatch rate limiter para integration tests
- R8 parcial: RLS audit formal con script runnable

### Pre-requisitos de deploy
1. Crear bucket "data-exports" en Supabase Dashboard (privado, ZIP only)
2. Aplicar migration 005 en Supabase SQL Editor

### Gates verificados
[completar después de implementación]
```

---

## 9. TODOs fuera de scope (documentar en HANDOVER/SECURITY)

- **k-anonymity formal en aria.*** (CHECK constraint o trigger): diferido post-Fase 13
  Razón: requiere benchmark de performance con datos reales.
- **Tabla bank_tokens para Fintoc OAuth**: cuando empiece integración Fintoc.
- **2FA usuario Sky (Supabase Auth TOTP)**: post-cutover Fase 13.
- **Pentest externo**: post-cutover, contratar auditor externo.
- **pg_cron install**: Supabase Pro feature. Si se activa, migrar cron de ARQ a pg_cron.
- **signed URL rotation automática**: si el user descarga y el URL expira antes de 7d,
  considerar refresh endpoint. Diferido.
