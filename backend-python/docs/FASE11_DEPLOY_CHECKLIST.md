# Fase 11 — Deploy Checklist (Railway)

> Este checklist es para el primer deploy del backend Python en Railway.
> NO toca producción Node.js ni DNS de api.skyfinanzas.com (eso es Fase 13).

---

## Pre-requisitos

- [ ] Railway account con acceso al proyecto Sky
- [ ] Supabase: migration 004_audit_log.sql aplicada
- [ ] Variables de entorno listas (ver §ENV vars)

---

## Paso 1: Aplicar migration 004_audit_log.sql

En Supabase Dashboard > SQL Editor > New Query:
```
Pegar contenido de migrations/004_audit_log.sql
```
Verificar:
```sql
SELECT COUNT(*) FROM public.audit_log;  -- debe ser 0 (tabla vacía)
```

---

## Paso 2: Crear servicio Railway — API

1. Railway > New Service > From GitHub
2. Seleccionar repo `sky_OFFICIAL` > raíz `backend-python/`
3. Build method: Dockerfile → `docker/api.Dockerfile`
4. Configurar ENV vars (ver tabla abajo)
5. Domain: asignar subdominio temporal Railway (ej: `sky-api-staging.up.railway.app`)
6. Deploy y verificar:
   ```
   curl https://sky-api-staging.up.railway.app/api/health
   → {"status": "ok", "app": "sky-backend-python"}
   curl https://sky-api-staging.up.railway.app/api/health/deep
   → {"status": "ok", "db": "ok", "redis": "ok", "anthropic": "ok"}
   ```

---

## Paso 3: Crear servicio Railway — Worker

1. Railway > New Service > From same repo
2. Dockerfile → `docker/worker.Dockerfile`
3. Las mismas ENV vars que el API (excepto PORT)
4. Sin domain público (worker no expone HTTP)

---

## Paso 4: Crear servicio Railway — Redis

1. Railway > Add Plugin > Redis
2. Copiar `REDIS_URL` generado → agregar a ENV de API y Worker

---

## ENV vars requeridas (ambos servicios)

| Variable | Fuente | Requerido |
|----------|--------|-----------|
| `SUPABASE_URL` | Supabase > Settings > API | ✅ |
| `SUPABASE_ANON_KEY` | Supabase > Settings > API | ✅ |
| `SUPABASE_SERVICE_KEY` | Supabase > Settings > API | ✅ |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:<password>@db.<ref>.supabase.co:5432/postgres` | ✅ |
| `ANTHROPIC_API_KEY` | console.anthropic.com | ✅ |
| `BANK_ENCRYPTION_KEY` | Misma que Node.js prod | ✅ |
| `REDIS_URL` | Plugin Redis Railway | ✅ |
| `NODE_ENV` | `production` | ✅ |
| `CORS_ORIGINS` | `https://app.skyfinanzas.com` | ✅ (prod) |
| `SENTRY_DSN` | sentry.io > Project > DSN | ✅ (prod) |
| `PROMETHEUS_SECRET` | `openssl rand -hex 32` | ✅ (prod) |
| `CRON_SECRET` | Misma que Node.js prod | ✅ |
| `API_RATE_LIMIT_PER_MINUTE` | `60` | opcional |
| `IDEMPOTENCY_TTL_SECONDS` | `86400` | opcional |

---

## Verificaciones post-deploy

- [ ] `/api/health` → 200
- [ ] `/api/health/deep` → `{"status": "ok", "db": "ok", "redis": "ok"}`
- [ ] `/metrics` sin header → 401 (en prod)
- [ ] `/metrics` con `x-prometheus-secret` correcto → 200
- [ ] Logs en Railway no contienen `ERROR` durante startup
- [ ] `audit_log` recibe eventos tras primer sync manual

---

## Rollback

Si algo falla: suspender servicio Railway (no delete — preservar logs).
Node.js en producción no se toca. Sky sigue funcionando desde backend Node.
