# 05 — Infraestructura

[← Volver al índice](../ESTADO_DEL_ARTE.md)

---

## Servicios en Railway (proyecto **SkyFinanzas**)

Cuenta operativa: `cristovasq464@gmail.com`. Entorno: `production`.

| Servicio | Rol | Dominio / URL | Estado |
|---|---|---|---|
| **sky-api-python** | API FastAPI | `api.skyfinanzas.com` (+ `api-v2.skyfinanzas.com` legacy de canary) | Online · escucha en `$PORT` (8080) |
| **sky-worker-python** | Worker ARQ + Playwright | (sin dominio público) | Online · browser pool 4 |
| **sky-cron-sync** | Cron de syncs programados | — | Online · corre cada hora |
| **Redis** | Cola ARQ + circuit breaker + rate limit | interno (`.railway.internal`) | Online · con volumen |
| **SkyFinance** | Frontend React/Vite | `app.skyfinanzas.com` | Online |
| **appealing-benevolence** | **Backend Node legacy** | `appealing-benevolence-*.up.railway.app` | ⚠️ Online — **pendiente de decomisionar** post-cutover |

> **Deuda de infraestructura**: `appealing-benevolence` (Node viejo) sigue corriendo y consumiendo recursos. El custom domain `api-v2.skyfinanzas.com` quedó como leftover del cutover canary y devuelve 502 (su servicio backing murió). Ver [08](08_ESTADO_Y_DEUDA.md).

### Lección de routing Railway (mayo 2026)
- Railway asigna `$PORT` dinámicamente (8080). El Dockerfile usa `uvicorn --port ${PORT:-8000}`.
- El "Target Port" del custom domain debe coincidir con `$PORT`. Un mismatch produce 502 "Application failed to respond" aunque el servicio arranque bien.
- El frontend (`VITE_API_URL`) debe apuntar a `https://api.skyfinanzas.com/api` (NO al `api-v2` de canary).

## Base de datos — Supabase

- **Postgres 15**. Esquemas: `public` (RLS habilitado en todas las tablas) y `aria` (analytics, sin UUID, solo `service_role` escribe).
- **Supabase Auth** como IDP: email+password y Google OAuth. UUID estable por usuario (`auth.users.id = profiles.id`).
- **Storage**: bucket privado `data-exports` (Ley 19.628).
- **PITR**: Supabase Pro, 7 días.
- Región: US-East-1. Certificación SOC2 Type II.
- Tres clientes: anon (RLS), service (bypassa RLS, solo backend), aria (service, solo escribe `aria.*`).

## IA — Anthropic

- Claude **Sonnet 4.6** (Mr. Money) y **Haiku 4.5** (categorización capa 3).
- Invocado **solo desde el backend**. `ANTHROPIC_API_KEY` nunca en frontend.
- Sin persistencia de datos del lado de Anthropic (API calls).

## DNS y dominios

- **`skyfinanzas.com`** — landing pública. Repo separado `SkyFinancWebSite`, servida por GitHub Pages (CNAME).
- **`app.skyfinanzas.com`** — frontend (Railway · SkyFinance).
- **`api.skyfinanzas.com`** — API (Railway · sky-api-python), CNAME → `sky-api-python-production.up.railway.app`.
- Gestión DNS: registrador del dominio (CNAMEs apuntando a Railway).
- TLS: gestionado por Railway (Let's Encrypt). HSTS forzado.

## Repositorios

| Repo | Contenido |
|---|---|
| `sky_OFFICIAL` (monorepo) | backend/, backend-python/, frontend/, docs/ |
| `SkyFinancWebSite` (separado) | Landing pública (GitHub Pages, CNAME `skyfinanzas.com`) |
| `SupabaseSQLQuerys` (separado) | Migraciones SQL versionadas |

## Disaster Recovery (resumen — ver `backend-python/docs/DR_RUNBOOK.md`)

- **Supabase down** (RTO 15-30 min): maintenance mode, esperar restauración, PITR si corrupción.
- **Railway down** (RTO 30-60 min): deploy de emergencia en **Render o Fly.io**, reapuntar CNAME (TTL 5 min). *Recomendación pendiente: warm standby en Fly.io.*
- **Brecha de `BANK_ENCRYPTION_KEY`** (RTO 2-4h): revocar, rotar (`RUNBOOK_KEY_ROTATION.md`), comunicar (incl. CMF si hay clientes).

## Incidentes conocidos recientes

- **2026-05-19/21**: outage de edge network de Railway (plataforma), luego mismatch de Target Port y `VITE_API_URL` apuntando al `api-v2` muerto. Resuelto. Reforzó la necesidad de runbook de deploy y warm standby.
