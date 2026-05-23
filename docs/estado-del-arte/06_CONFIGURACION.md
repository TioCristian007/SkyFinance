# 06 — Configuración

[← Volver al índice](../ESTADO_DEL_ARTE.md)

---

## Variables de entorno (backend Python)

Centralizadas en `sky.core.config:Settings` (pydantic-settings). Fail-fast: si falta una requerida, el servidor no arranca. Plantilla en `backend-python/.env.example`.

### Críticas (secretos — solo backend)

| Var | Uso |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` | DB + Auth. `SERVICE_KEY` bypassa RLS, nunca al frontend. |
| `DATABASE_URL` | Postgres (`postgresql+asyncpg://...`). |
| `ANTHROPIC_API_KEY` | Claude. Formato `sk-ant-...`. |
| `BANK_ENCRYPTION_KEY` | AES-256-GCM (hex 64 chars). **Idéntica a la del Node legacy** para compat binaria. |
| `BANK_ENCRYPTION_KEY_V2` | Solo durante rotación activa. |
| `CRON_SECRET` | Protege `/api/internal/*`. Sin esta var → 503 fail-safe. |
| `PROMETHEUS_SECRET` | Protege `/metrics`. Requerido en prod. |
| `AUDIT_LOG_SALT` | SHA-256(user_id+salt) → user_hash en audit_log. Nunca rotar en prod. |
| `SENTRY_DSN` | Requerido en prod. |

### Operativas (con defaults)

| Var | Default | Nota |
|---|---|---|
| `REDIS_URL` | `redis://127.0.0.1:6379` | En Windows usar `127.0.0.1`, no `localhost` (WSL2/IPv6). |
| `PORT` | 8000 | Railway lo setea a 8080. |
| `NODE_ENV` | development | `production` activa fail-fast. |
| `CORS_ORIGINS` | "" | Comma-separated. Requerido en prod. |
| `CHROME_PATH` | `/usr/bin/chromium` | |
| `BROWSER_POOL_SIZE` | 4 | |
| `BCHILE_2FA_TIMEOUT_SEC` | 120 | |
| `API_RATE_LIMIT_PER_MINUTE` | 60 | |
| `IDEMPOTENCY_TTL_SECONDS` | 86400 | 24h |
| `AUDIT_LOG_RETENTION_DAYS` | 90 | Ajustable sin redeploy. |
| `CATEGORIZE_BATCH_SIZE` | 50 | |
| `SYNC_ADVISORY_LOCK_TIMEOUT_SEC` | 600 | |

### Frontend

| Var | Valor correcto |
|---|---|
| `VITE_API_URL` | `https://api.skyfinanzas.com/api` (NO `api-v2`) |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | Públicas (anon key es segura por diseño) |

## Gestión de secretos

**Decisión actual** (ADR `DECISION_SECRETS_MANAGER.md`): **variables de entorno en Railway** para el MVP. Cero complejidad, suficiente para la etapa. Acceso al dashboard con 2FA.

**Condición de escalada a AWS Secrets Manager**: si un banco exige due diligence técnico, auditoría ISO27001, o el equipo supera 5 personas con acceso a prod. Estimación: 2-3 días.

## Colas ARQ

- Cola única: **`sky:default`**. Tanto la API como el worker deben usar este nombre al crear sus pools (`create_pool(..., default_queue_name="sky:default")`).
- El worker consume de `sky:default`. Jobs encolados sin nombre de cola caen en `arq:queue` y **no se ejecutan** (bug histórico, corregido).

## Despliegue

- **Railway con auto-deploy por push de GitHub.** Push a `main` → Railway buildea y deploya los servicios afectados.
- Dockerfiles: `backend-python/Dockerfile` (raíz) y `backend-python/docker/api.Dockerfile`. `CMD` usa `uvicorn --port ${PORT:-8000}`.
- `railway.json`: `restartPolicyType: ON_FAILURE`, `restartPolicyMaxRetries: 3`.
- **Verificar siempre** que el servicio correcto redeploye: un fix de worker requiere redeploy de `sky-worker-python`, no de la API.

## CI / calidad

- Gates por cambio: `ruff check`, `mypy`, `pytest` (376 tests). `asyncio_mode=auto`. `fakeredis[lua]` para tests de Redis.
- RLS audit antes de cada migración SQL: `python scripts/audit_rls_policies.py` (exit 1 bloquea deploy).

## Comandos comunes (PowerShell, Windows)

```powershell
cd backend-python; .venv\Scripts\activate
pytest tests/unit/ -v --cov=src/sky
ruff check src/sky/ ; mypy src/sky/
uvicorn sky.api.main:app --reload --port 8000
arq sky.worker.main.WorkerSettings
```
