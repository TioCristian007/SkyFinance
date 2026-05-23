# 04 — Arquitectura Técnica

[← Volver al índice](../ESTADO_DEL_ARTE.md)

---

## Regla de oro

```
Frontend  → solo muestra, captura input, llama al backend
Backend   → calcula, decide, guarda, llama a la IA
IA        → solo desde el backend, nunca desde el browser
ARIA      → solo escribe analytics anónimos
Cifrado   → solo el backend conoce BANK_ENCRYPTION_KEY
```

## Monorepo — tres patas

| Carpeta | Rol | Estado |
|---|---|---|
| `backend/` | Node.js + Express — backend legacy | Archivado post-cutover (referencia) |
| `backend-python/` | Python 3.12 + FastAPI + ARQ + Playwright | **Producción** |
| `frontend/` | React 18.3 + Vite 5.4 | **Producción** |

## Stack por capa

| Capa | Tecnología |
|---|---|
| Frontend | React 18.3, Vite 5.4 |
| API | FastAPI + Uvicorn (Python 3.12, async) |
| Worker / colas | ARQ + Redis |
| Ingestión | Playwright + Chromium |
| DB | Postgres 15 (Supabase), SQLAlchemy 2.0 async |
| IA | Anthropic Claude (Sonnet 4.6, Haiku 4.5) |
| Observabilidad | Sentry, Prometheus, structlog |

## Procesos deployables (separación dura)

La **API nunca importa Playwright**. Solo el **worker** arranca el browser pool. Son dos servicios independientes que comparten Postgres y Redis.

```
                      Usuario (browser)
                            │ HTTPS (TLS 1.2+)
            ┌───────────────┴───────────────┐
   app.skyfinanzas.com               api.skyfinanzas.com
   (React/Vite · SkyFinance)         (FastAPI · sky-api-python)
                                            │ encola jobs (ARQ)
                                            ▼
                                      Redis (cola sky:default)
                                            │
                                      sky-worker-python  ── Playwright ──► Bancos
                                            │
                          ┌─────────────────┼─────────────────┐
                      Supabase          Anthropic         (cron: sky-cron-sync)
                   (Postgres + Auth)     (Claude)
                   public (RLS) / aria (service_role)
```

## API — FastAPI (`sky.api`)

- Entry: `sky.api.main:create_app()`. Lifespan arranca el router de ingesta (sin browser), Redis y el pool de ARQ (`default_queue_name="sky:default"`).
- **Middleware stack** (orden de request): CORS → SecurityHeaders → JWTContext → SlowAPI (rate limit) → Idempotency → RequestTiming → handler.
- **Routers**: `banking`, `transactions`, `summary`, `goals`, `challenges`, `simulate`, `chat` (Mr. Money), `webhooks`, `internal` (cron), `audit`, `account` (export), `health`.
- **Fail-fast en producción**: arranca solo si `CORS_ORIGINS`, `PROMETHEUS_SECRET` y `SENTRY_DSN` están seteados.
- Auth: `JWTContextMiddleware` verifica el JWT de Supabase (HS256, audience `authenticated`) una vez por request; `require_user_id` (deps) rechaza 401 si falta.

## Worker — ARQ (`sky.worker`)

- Entry: `sky.worker.main:WorkerSettings`. `queue_name = "sky:default"`.
- Arranque: inicia browser pool, construye router **con** browser sources, crea pool ARQ interno.
- **Jobs**: `sync_bank_account_job`, `sync_all_user_accounts_job`, `categorize_pending_job`, `scheduled_sync_job`, `audit_purge_job`, `process_export_request_job`.
- **Cron**: `scheduled_sync_job` cada hora a los :05; `audit_purge_job` diario 03:00 UTC.
- `max_jobs = browser_pool_size * 2`, `job_timeout = 600s`.

> **Lección de cola** (corregida mayo 2026): el pool ARQ interno del worker debe crearse con `default_queue_name="sky:default"`. Sin eso, `categorize_pending_job` se encolaba en `arq:queue` (cola fantasma) y nunca corría. Ver [08](08_ESTADO_Y_DEUDA.md).

## Sync bancario (`banking_sync.py`)

1. `pg_try_advisory_lock` por `bank_account_id` (evita syncs duplicados — cierra BUG-3).
2. Descifra credenciales **solo en memoria**; `del` inmediato tras el sync.
3. `router.ingest()` trae movimientos.
4. `_persist_movements` con `INSERT ... ON CONFLICT (user_id, bank_account_id, external_id) DO NOTHING` (idempotencia — cierra BUG-1, BUG-2). Inserta con `status='pending'`, `description='Procesando...'`.
5. Si `inserted > 0` → encola `categorize_pending_job` + dispara ARIA (si hay consent).

## IngestionRouter (`routing/router.py`)

- **Cadena de proveedores por banco** ordenada en `public.ingestion_routing_rules` — editable sin redeploy.
- **Rollout %**: hash determinístico de `user_id + bank_id` para canary releases.
- **Circuit breaker en Redis** (`cb:<source_id>`): abre tras 5 fallos en 60s, mantiene 120s, cierra tras 3 éxitos en half-open.
- **Rate limit en Redis** (`rl:<source_id>`): sliding window log atómico (Lua), namespace separado del CB.
- **Política de failover**: circuit OPEN → salta al siguiente; `RecoverableIngestionError` → siguiente; `AuthenticationError` → propaga sin failover (la credencial es el problema); rate limit → skip; toda la cadena falla → `AllSourcesFailedError`.

## Frontend (`frontend/src`)

- `Sky.jsx` — componente principal (god-component, ~1.600 LOC — deuda P1-1).
- `services/api.js` — único canal al backend. `VITE_API_URL` define el base; `Authorization: Bearer <token>` en cada request.
- `components/BankConnect.jsx` — onboarding y gestión de cuentas. Usa `Promise.allSettled` para que la lista de bancos no se rompa si `/accounts` falla.
- Display ingreso/gasto: por **signo del monto** (`tx.amount > 0`), no por categoría.
