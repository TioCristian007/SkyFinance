# Sky Finanzas — Dossier Integral

> Documento único consolidado a partir de `ESTADO_DEL_ARTE.md`, sus 9 secciones modulares (`estado-del-arte/01..09`) y `SECURITY_INFRASTRUCTURE.md`.
> Formato: Markdown plano, denso, sin imágenes, pensado para ser **leído por otro LLM** como contexto previo a reuniones con bancos.
> Fuente de verdad legal: `Estados del Arte/SkyFinanzas_EstadoDelArte_v5_Documentado.pdf` (registrado ante INAPI, Chile). Si algo aquí contradice al v5, gana el v5.
> Fecha de consolidación: 2026-05-25. Última actualización de fuentes: 2026-05-25.

---

## 0. Cómo usar este documento

Cinco bloques:

1. **Empresa y producto** (§1–§2) — quiénes somos, qué construimos, por qué.
2. **Ecosistema y arquitectura** (§3–§4) — bancos, modelo canónico, stack, procesos.
3. **Infraestructura, configuración y seguridad** (§5–§7) — operación real, controles activos.
4. **Estado real y deuda** (§8) — qué funciona, qué no, qué se está cerrando.
5. **Doctrina** (§9) — 23 reglas inviolables firmadas por los cofundadores.

Apéndice A: contexto para reunión con bancos (SFA, tesis comercial, fragilidad honesta del scraping).
Apéndice B: glosario.

---

## 1. Empresa

### 1.1 Identidad legal

- **Razón social:** SkyFinanzas SpA
- **RUT:** 78.395.382-K
- **País:** Chile
- **Marca:** Sky / Sky Finanzas. Personaje IA: **Mr. Money**.
- **Dominios:** `skyfinanzas.com` (landing), `app.skyfinanzas.com` (aplicación), `api.skyfinanzas.com` (backend).
- **Contacto:** info@skyfinanzas.com · vulnerabilidades: fintyinc@gmail.com

### 1.2 Cofundadores

| Nombre | RUT | Rol |
|---|---|---|
| Cristian Cristóbal Amaru Vásquez Guevara | 22.141.522-1 | Arquitectura técnica y producto |
| Juan José Latorre Pérez | 22.003.365-1 | Estrategia, operación y diseño conductual |

### 1.3 Propiedad intelectual

Modelo arquitectónico, doctrina y visión consolidados en **`SkyFinanzas_EstadoDelArte_v5_Documentado.pdf`**, registrado ante INAPI. Estructura:

- **Parte I** — Estado verificado (lo implementado en producción).
- **Parte II** — Arquitectura objetivo (migración Python — Fases 0-13). *Completada a mayo 2026.*
- **Parte III** — Plan de remediación de deuda (P0/P1/P2 + BUG-1..4).
- **Parte IV** — Visión, gobierno, doctrina permanente.
- **Anexo A** — Estructura de repositorios.

> El v5 fue registrado cuando la migración Python era *futuro*. A mayo 2026 está completa. Cuando se actualice el registro INAPI, la Parte II debe reescribirse como estado actual.

### 1.4 Tesis del producto

La gente no falla en sus finanzas por falta de conocimiento, sino por **ansiedad, evasión y fricción**. La tecnología debe **absorber complejidad**, no exigir expertise. Sky es la capa cognitiva entre la persona y su vida financiera.

Promesa central **respiratoria antes que cognitiva**: la landing dice *"Respira. Tus finanzas están en las mejores manos"*. Primer entregable emocional: alivio.

### 1.5 Tres pilares

1. **Automatización bancaria** — conexión y consolidación sin esfuerzo del usuario.
2. **Interpretación inteligente** — Mr. Money traduce datos en claridad accionable.
3. **Diseño conductual** — metas, desafíos, simulaciones que cambian comportamiento.

### 1.6 Visión estratégica — 5 fases de negocio

(No confundir con las 13 fases técnicas de migración, ya cerradas.)

| Fase | Objetivo |
|---|---|
| **F1 — Demostrar alivio** | Que un usuario sienta más claridad en una semana. Cierre de deuda P0 + migración Python. **← etapa actual** |
| **F2 — Consolidar hábito** | Recomendación entre pares. Más bancos. Fintoc + APIs directas. Entrada universitaria. |
| **F3 — Capa institucional** | ARIA genera valor B2B (bancos, gobierno, aseguradoras). |
| **F4 — Infraestructura** | Sky como plataforma. Contrato `DataSource` como API pública. |
| **F5 — Categoría regional** | Expansión Perú, México, Colombia. |

### 1.7 Riesgos estratégicos vivos (v5 Parte IV §25)

Onboarding · complejidad acumulada · traición de datos · dependencia de proveedor · regulación (SFA) · sobrehype · talento · deuda técnica · ejecución de migración.

### 1.8 Contexto de mercado

- **Open Banking chileno (SFA)** desplegado por la **CMF**. Los bancos invierten en APIs sin tener aún consumers maduros que las usen con volumen. Sky se posiciona como ese consumer.
- Competidores adyacentes (no directos): Fintual (inversión), Mach/Tenpo (cuenta+pagos), RebajaTusCuentas. Sky **lee** esas cuentas; no compite como producto financiero, sino como capa de inteligencia y consolidación.

---

## 2. Producto

### 2.1 Qué es Sky (y qué NO es)

Sky **no** es una app de gastos con IA pegada encima. Es un **sistema operativo financiero personal**: una capa cognitiva que absorbe la complejidad financiera del usuario y devuelve claridad. Regla de oro: **el producto debe sentirse ligero**. La ligereza es feature, no limitación.

### 2.2 Flujo del usuario

1. **Onboarding** — el usuario conecta su banco (RUT + clave, cifradas). Hoy vía scraping.
2. **Consolidación** — Sky sincroniza saldos y movimientos, los normaliza a `CanonicalMovement`.
3. **Categorización** — cada movimiento recibe una categoría (3 capas).
4. **Interpretación** — Mr. Money construye contexto financiero y conversa.
5. **Acción conductual** — metas, desafíos y simulaciones para cambiar hábitos.

### 2.3 Mr. Money — arquitectura de respuesta

Asistente conversacional sobre **Claude (Anthropic)**. Principios:

1. **Detección local primero** — patrones simples (saludos, consultas de desafíos) se responden **sin gastar tokens**. ~60-70% de las consultas se resuelven localmente.
2. Si no hay match local → construye **contexto financiero** (balance, ingresos/gastos por categoría, tasa de ahorro, metas, desafíos, cuentas) → eleva a `claude-sonnet`.
3. **Tipos de respuesta**: texto simple · `propose_challenge` (propuesta estructurada con render interactivo y confirmación explícita) · navegación (deep-link).
4. **Tool use** de Anthropic para proyecciones financieras y evaluar realismo de metas.

**Doctrina de Mr. Money:** *guía, no decide*. NO da asesoría de inversión específica, NO recomienda activos puntuales, NO actúa como asesor licenciado, NO garantiza resultados. Toda propuesta estructurada requiere confirmación del usuario.

Configuración (`sky.core.config`): modelo `claude-sonnet-4-6`, `mr_money_max_tokens=4096`, `temperature=0.7`, prompt caching 5m.

### 2.4 Categorización en 3 capas

Orden estricto; cada capa solo invoca la siguiente si falla:

1. **Reglas deterministas** — ~25 regex. Sin tokens. (`categorizer.py`)
2. **Caché de comercios** — tabla `merchant_categories`, lookup por prefijo progresivo (`"jumbo las condes" → "jumbo las" → "jumbo"`). Compartida entre todos los usuarios.
3. **Claude API** — solo si las dos capas anteriores fallan. Modelo `claude-haiku-4-5`. Resultado se guarda en caché.

**Categoría especial `income`:** se asigna por reglas (monto positivo + glosa que matchea `abono|remuner|sueldo|salario|honorario|liquidaci|traspaso de:|...`). El display de ingreso/gasto en el frontend usa el **signo del monto**, no la categoría, para robustez.

**Estado de categorización (post-fix):** las transacciones se insertan con `categorization_status='pending'` y descripción `'Procesando...'`, y un job ARQ (`categorize_pending_job`) las procesa async, reemplazando descripción y categoría.

### 2.5 Metas, desafíos y simulaciones

- **Metas** (`goals`): el usuario define objetivos de ahorro. Sky calcula *capacity* = `max(0, ingreso − gastos)` de los últimos 30 días y evalúa realismo.
- **Desafíos** (`challenges`): retos de comportamiento (ej. "Ahorra $60K este mes"). Estados: propuesto → aceptado/activo → completado.
- **Simulaciones:** proyecciones financieras ("¿qué pasa si reduzco X gasto?").

### 2.6 Resumen financiero (`finance.py`)

- `income` = suma de montos positivos.
- `expenses` = suma de `abs(monto)` donde `category != "income"` y monto negativo.
- `balance`, `savings_rate = max(0, (income − expenses)/income)`, `net_flow`.

### 2.7 Marca y diseño

- **Paleta:** verde `#00C853`, navy `#0D1B2A`, blanco `#FFFFFF`.
- **Tipografías:** Instrument Serif (display) + Geist (texto) + Geist Mono (datos).
- **Tono:** cálido, calmo, sin jerga financiera. Empático antes que técnico.

---

## 3. Ecosistema bancario

### 3.1 Contrato `DataSource` (pieza más protegida del diseño)

Toda fuente de datos bancarios implementa el contrato abstracto `DataSource`. Modificarlo requiere RFC interno. Vive en `backend-python/src/sky/ingestion/contracts.py`.

**`kind` — 5 tipos**

| Kind | Significado |
|---|---|
| `SCRAPER` | Browser automation (BChile, Falabella, BCI) |
| `AGGREGATOR` | Fintoc, Belvo |
| `BANK_API_DIRECT` | API propia del banco con acuerdo bilateral |
| `SFA` | Open Banking regulado chileno (CMF) |
| `MANUAL_UPLOAD` | Archivo subido por el usuario, fallback humano |

**`auth_mode` — 4 modos**

| Modo | Para |
|---|---|
| `PASSWORD` | RUT + clave (scraping) |
| `OAUTH` | Tokens access/refresh (Fintoc, bancos) |
| `API_KEY` | Clave institucional |
| `CONSENT_TOKEN` | Token de consentimiento explícito (SFA) |

### 3.2 Modelo canónico — `CanonicalMovement`

Todo proveedor, sin importar su `kind`, devuelve movimientos en este shape único. Categorización, Mr. Money, ARIA, summary y reporting consumen el mismo modelo.

```
external_id      :: SHA-256 determinístico
                    f"{bank_id}_{sha256(f'{date}|{amount}|{desc.lower()}')[:16]}"
amount_clp       :: int (CLP, sin decimales). Positivo = ingreso, negativo = gasto.
raw_description  :: str
occurred_at      :: date
movement_source  :: enum(ACCOUNT/CUENTA, CREDIT_CARD/TARJETA, LINE/LÍNEA)
source_kind      :: SourceKind
source_metadata  :: dict (debug libre — el dominio NO lo lee)
```

**Determinismo del `external_id`:** el mismo movimiento real produce siempre el mismo id → idempotencia natural en `INSERT ... ON CONFLICT`. Consecuencia clave: al migrar un banco de scraping a SFA, **no se duplica histórico** — el id une los movimientos.

**Regla doctrinal:** `sky.domain` jamás pregunta de qué `source` vino un movimiento. Si una capa superior necesita distinguir origen, el modelo canónico está incompleto — se enriquece, no se rompe la abstracción.

### 3.3 Bancos soportados (`SUPPORTED_BANKS`)

Definido en `backend-python/src/sky/ingestion/sources/__init__.py`. Estado a mayo 2026:

| Identifier | Banco | Capa · Auth | Estado | Notas |
|---|---|---|---|---|
| `bchile` | Banco de Chile | SCRAPER · PASSWORD | **active** | Validado desde IP residencial. Bloqueado por anti-bot (Incapsula) desde datacenter Railway. 2FA app. |
| `bci` | BCI | SCRAPER · PASSWORD | **pending** | Scraper roto: `portalpersonas.bci.cl` ya no resuelve. Requiere rework. 2FA. |
| `falabella` | Banco Falabella | SCRAPER · PASSWORD | (removido del listado) | Skeleton, no operativo. |
| `mercadopago`, `fintoc`, `santander.direct`, `bci.direct`, `sfa.<bank>`, `manual` | varios | AGGREGATOR / DIRECT / SFA / MANUAL | Futuro | No implementados. |

El frontend solo muestra como conectables los bancos `active`. Por decisión del equipo, el listado expone solo BChile y BCI.

### 3.4 Scrapers — cómo funcionan

- **BChile** (`bchile_scraper.py`): login en portal → detecta 2FA (app BancoChile) → usa las **APIs REST internas** de BChile vía `page.evaluate()` con token XSRF de cookies. Más estable que scrapear HTML. Extrae balance + cartola (cuenta) + movimientos de tarjeta. Soporta sync incremental (`since`).
- **BCI** (`bci_direct.py`): login → intercepta JWT Bearer del tráfico a `apilocal.bci.cl` → llama directo a la API interna. **Actualmente roto** por cambio de dominio del portal.

### 3.5 Open Banking — SFA (dirección estratégica)

La **CMF** despliega el **Sistema Financiero Abierto**. Sky está diseñado para consumirlo: el SFA es simplemente un nuevo `DataSource` de `kind=SFA`, `auth_mode=CONSENT_TOKEN`. La capa de negocio no cambia.

**Tesis comercial:** cuando un banco libere su SFA, Sky migra a sus usuarios desde scraping a SFA sin que lo noten, generando volumen y métricas de adopción que el banco necesita para justificar la inversión ante CMF y directorio. La fragilidad del scraping (anti-bot, cambios de portal) es el argumento técnico honesto para el SFA.

### 3.6 Scraper como fallback permanente

Incluso tras integrar APIs directas o SFA, el scraper queda como **última línea**. Solo se elimina si un contrato bancario lo exige. La cadena de proveedores por banco es configurable en runtime (ver §4 — IngestionRouter).

---

## 4. Arquitectura técnica

### 4.1 Regla de oro

```
Frontend  → solo muestra, captura input, llama al backend
Backend   → calcula, decide, guarda, llama a la IA
IA        → solo desde el backend, nunca desde el browser
ARIA      → solo escribe analytics anónimos
Cifrado   → solo el backend conoce BANK_ENCRYPTION_KEY
```

### 4.2 Monorepo — tres patas

| Carpeta | Rol | Estado |
|---|---|---|
| `backend/` | Node.js + Express — backend legacy | Archivado post-cutover (referencia) |
| `backend-python/` | Python 3.12 + FastAPI + ARQ + Playwright | **Producción** |
| `frontend/` | React 18.3 + Vite 5.4 | **Producción** |

### 4.3 Stack por capa

| Capa | Tecnología |
|---|---|
| Frontend | React 18.3, Vite 5.4 |
| API | FastAPI + Uvicorn (Python 3.12, async) |
| Worker / colas | ARQ + Redis |
| Ingestión | Playwright + Chromium |
| DB | Postgres 15 (Supabase), SQLAlchemy 2.0 async |
| IA | Anthropic Claude (Sonnet 4.6, Haiku 4.5) |
| Observabilidad | Sentry, Prometheus, structlog |

### 4.4 Procesos deployables — separación dura

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

### 4.5 API — FastAPI (`sky.api`)

- Entry: `sky.api.main:create_app()`. Lifespan arranca router de ingesta (sin browser), Redis y el pool de ARQ (`default_queue_name="sky:default"`).
- **Middleware stack** (orden de request): CORS → SecurityHeaders → JWTContext → SlowAPI (rate limit) → Idempotency → RequestTiming → handler.
- **Routers:** `banking`, `transactions`, `summary`, `goals`, `challenges`, `simulate`, `chat` (Mr. Money), `webhooks`, `internal` (cron), `audit`, `account` (export), `health`.
- **Fail-fast en producción:** arranca solo si `CORS_ORIGINS`, `PROMETHEUS_SECRET` y `SENTRY_DSN` están seteados.
- **Auth:** `JWTContextMiddleware` verifica JWT de Supabase (HS256, audience `authenticated`) una vez por request; `require_user_id` (deps) rechaza 401 si falta.

### 4.6 Worker — ARQ (`sky.worker`)

- Entry: `sky.worker.main:WorkerSettings`. `queue_name = "sky:default"`.
- Arranque: inicia browser pool, construye router **con** browser sources, crea pool ARQ interno.
- **Jobs:** `sync_bank_account_job`, `sync_all_user_accounts_job`, `categorize_pending_job`, `scheduled_sync_job`, `audit_purge_job`, `process_export_request_job`.
- **Cron:** `scheduled_sync_job` cada hora a los :05; `audit_purge_job` diario 03:00 UTC.
- `max_jobs = browser_pool_size * 2`, `job_timeout = 600s`.

> **Lección de cola (corregida mayo 2026):** el pool ARQ interno del worker debe crearse con `default_queue_name="sky:default"`. Sin eso, `categorize_pending_job` se encolaba en `arq:queue` (cola fantasma) y nunca corría.

### 4.7 Sync bancario (`banking_sync.py`)

1. `pg_try_advisory_lock` por `bank_account_id` (evita syncs duplicados — cierra BUG-3).
2. Descifra credenciales **solo en memoria**; `del` inmediato tras el sync.
3. `router.ingest()` trae movimientos.
4. `_persist_movements` con `INSERT ... ON CONFLICT (user_id, bank_account_id, external_id) DO NOTHING` (idempotencia — cierra BUG-1, BUG-2). Inserta con `status='pending'`, `description='Procesando...'`.
5. Si `inserted > 0` → encola `categorize_pending_job` + dispara ARIA (si hay consent).

### 4.8 IngestionRouter (`routing/router.py`)

- **Cadena de proveedores por banco** ordenada en `public.ingestion_routing_rules` — editable sin redeploy.
- **Rollout %:** hash determinístico de `user_id + bank_id` para canary releases.
- **Circuit breaker en Redis** (`cb:<source_id>`): abre tras 5 fallos en 60s, mantiene 120s, cierra tras 3 éxitos en half-open.
- **Rate limit en Redis** (`rl:<source_id>`): sliding window log atómico (Lua), namespace separado del CB.
- **Política de failover:** circuit OPEN → salta al siguiente; `RecoverableIngestionError` → siguiente; `AuthenticationError` → propaga sin failover (la credencial es el problema); rate limit → skip; toda la cadena falla → `AllSourcesFailedError`.

### 4.9 Frontend (`frontend/src`)

- `Sky.jsx` — componente principal (god-component, ~1.600 LOC — deuda P1-1).
- `services/api.js` — único canal al backend. `VITE_API_URL` define el base; `Authorization: Bearer <token>` en cada request.
- `components/BankConnect.jsx` — onboarding y gestión de cuentas. Usa `Promise.allSettled` para que la lista no se rompa si `/accounts` falla.
- Display ingreso/gasto: por **signo del monto** (`tx.amount > 0`), no por categoría.

---

## 5. Infraestructura

### 5.1 Servicios en Railway (proyecto **SkyFinanzas**)

Cuenta operativa: `cristovasq464@gmail.com`. Entorno: `production`.

| Servicio | Rol | Dominio / URL | Estado |
|---|---|---|---|
| **sky-api-python** | API FastAPI | `api.skyfinanzas.com` (+ `api-v2.skyfinanzas.com` legacy de canary) | Online · escucha en `$PORT` (8080) |
| **sky-worker-python** | Worker ARQ + Playwright | (sin dominio público) | Online · browser pool 4 |
| **sky-cron-sync** | Cron de syncs programados | — | Online · corre cada hora |
| **Redis** | Cola ARQ + circuit breaker + rate limit | interno (`.railway.internal`) | Online · con volumen |
| **SkyFinance** | Frontend React/Vite | `app.skyfinanzas.com` | Online |
| **appealing-benevolence** | **Backend Node legacy** | `appealing-benevolence-*.up.railway.app` | ⚠️ Online — **pendiente de decomisionar** post-cutover |

> **Deuda de infraestructura:** `appealing-benevolence` (Node viejo) sigue corriendo y consumiendo recursos. El custom domain `api-v2.skyfinanzas.com` quedó como leftover del cutover canary y devuelve 502.

### 5.2 Lección de routing Railway (mayo 2026)

- Railway asigna `$PORT` dinámicamente (8080). Dockerfile usa `uvicorn --port ${PORT:-8000}`.
- El "Target Port" del custom domain debe coincidir con `$PORT`. Mismatch produce 502 "Application failed to respond" aunque el servicio arranque bien.
- Frontend (`VITE_API_URL`) debe apuntar a `https://api.skyfinanzas.com/api` (NO al `api-v2` de canary).

### 5.3 Base de datos — Supabase

- **Postgres 15.** Esquemas: `public` (RLS habilitado en todas las tablas) y `aria` (analytics, sin UUID, solo `service_role` escribe).
- **Supabase Auth** como IDP: email+password y Google OAuth. UUID estable por usuario (`auth.users.id = profiles.id`).
- **Storage:** bucket privado `data-exports` (Ley 19.628).
- **PITR:** Supabase Pro, 7 días.
- **Región:** US-East-1. Certificación SOC2 Type II.
- Tres clientes: anon (RLS), service (bypassa RLS, solo backend), aria (service, solo escribe `aria.*`).

### 5.4 IA — Anthropic

- Claude **Sonnet 4.6** (Mr. Money) y **Haiku 4.5** (categorización capa 3).
- Invocado **solo desde el backend**. `ANTHROPIC_API_KEY` nunca en frontend.
- Sin persistencia de datos del lado de Anthropic (API calls).

### 5.5 DNS y dominios

- **`skyfinanzas.com`** — landing pública. Repo separado `SkyFinancWebSite`, servida por GitHub Pages (CNAME).
- **`app.skyfinanzas.com`** — frontend (Railway · SkyFinance).
- **`api.skyfinanzas.com`** — API (Railway · sky-api-python), CNAME → `sky-api-python-production.up.railway.app`.
- Gestión DNS: registrador del dominio (CNAMEs apuntando a Railway).
- TLS: gestionado por Railway (Let's Encrypt). HSTS forzado.

### 5.6 Repositorios

| Repo | Contenido |
|---|---|
| `sky_OFFICIAL` (monorepo) | backend/, backend-python/, frontend/, docs/ |
| `SkyFinancWebSite` (separado) | Landing pública (GitHub Pages, CNAME `skyfinanzas.com`) |
| `SupabaseSQLQuerys` (separado) | Migraciones SQL versionadas |

### 5.7 Disaster Recovery (resumen — ver `backend-python/docs/DR_RUNBOOK.md`)

- **Supabase down** (RTO 15-30 min): maintenance mode, esperar restauración, PITR si corrupción.
- **Railway down** (RTO 30-60 min): deploy de emergencia en **Render o Fly.io**, reapuntar CNAME (TTL 5 min). *Recomendación pendiente: warm standby en Fly.io.*
- **Brecha de `BANK_ENCRYPTION_KEY`** (RTO 2-4h): revocar, rotar (`RUNBOOK_KEY_ROTATION.md`), comunicar (incl. CMF si hay clientes).

### 5.8 Incidentes recientes

- **2026-05-19/21:** outage de edge network de Railway (plataforma), luego mismatch de Target Port y `VITE_API_URL` apuntando al `api-v2` muerto. Resuelto. Reforzó la necesidad de runbook de deploy y warm standby.

---

## 6. Configuración

### 6.1 Variables de entorno (backend Python)

Centralizadas en `sky.core.config:Settings` (pydantic-settings). Fail-fast: si falta una requerida, el servidor no arranca. Plantilla en `backend-python/.env.example`.

**Críticas (secretos — solo backend)**

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

**Operativas (con defaults)**

| Var | Default | Nota |
|---|---|---|
| `REDIS_URL` | `redis://127.0.0.1:6379` | En Windows usar `127.0.0.1`, no `localhost` (WSL2/IPv6). |
| `PORT` | 8000 | Railway lo setea a 8080. |
| `NODE_ENV` | development | `production` activa fail-fast. |
| `CORS_ORIGINS` | "" | Comma-separated. Requerido en prod. |
| `CHROME_PATH` | `/usr/bin/chromium` | |
| `BROWSER_POOL_SIZE` | 4 | |
| `BCHILE_2FA_TIMEOUT_SEC` | 120 | |
| `BROWSER_HEADLESS` | `true` | `false` = browser visible, útil para diagnóstico local. Cambio sin redeploy. |
| `SCRAPER_DEBUG_CAPTURE` | `false` | `true` = guarda screenshot+HTML al fallar `_fill_rut`/`_fill_password` (sin PII). Solo en diagnóstico. |
| `SCRAPER_DEBUG_DIR` | `""` | Vacío = `tempfile.gettempdir()`. |
| `API_RATE_LIMIT_PER_MINUTE` | 60 | |
| `IDEMPOTENCY_TTL_SECONDS` | 86400 | 24h |
| `AUDIT_LOG_RETENTION_DAYS` | 90 | Ajustable sin redeploy. |
| `CATEGORIZE_BATCH_SIZE` | 50 | |
| `SYNC_ADVISORY_LOCK_TIMEOUT_SEC` | 600 | |

**Frontend**

| Var | Valor correcto |
|---|---|
| `VITE_API_URL` | `https://api.skyfinanzas.com/api` (NO `api-v2`) |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | Públicas (anon key es segura por diseño) |

### 6.2 Gestión de secretos

**Decisión actual** (ADR `DECISION_SECRETS_MANAGER.md`): **variables de entorno en Railway** para el MVP. Cero complejidad, suficiente para la etapa. Acceso al dashboard con 2FA.

**Condición de escalada a AWS Secrets Manager:** si un banco exige due diligence técnico, auditoría ISO27001, o el equipo supera 5 personas con acceso a prod. Estimación: 2-3 días.

### 6.3 Colas ARQ

- Cola única: **`sky:default`**. Tanto la API como el worker deben usar este nombre al crear sus pools (`create_pool(..., default_queue_name="sky:default")`).
- El worker consume de `sky:default`. Jobs encolados sin nombre de cola caen en `arq:queue` y **no se ejecutan** (bug histórico, corregido).

### 6.4 Despliegue

- **Railway con auto-deploy por push de GitHub.** Push a `main` → Railway buildea y deploya los servicios afectados.
- Dockerfiles: `backend-python/Dockerfile` (raíz) y `backend-python/docker/api.Dockerfile`. `CMD` usa `uvicorn --port ${PORT:-8000}`.
- `railway.json`: `restartPolicyType: ON_FAILURE`, `restartPolicyMaxRetries: 3`.
- **Verificar siempre** que el servicio correcto redeploye: un fix de worker requiere redeploy de `sky-worker-python`, no de la API.

### 6.5 CI / calidad

- Gates por cambio: `ruff check`, `mypy`, `pytest` (386 tests). `asyncio_mode=auto`. `fakeredis[lua]` para tests de Redis.
- RLS audit antes de cada migración SQL: `python scripts/audit_rls_policies.py` (exit 1 bloquea deploy).

### 6.6 Comandos comunes (PowerShell, Windows)

```powershell
cd backend-python; .venv\Scripts\activate
pytest tests/unit/ -v --cov=src/sky
ruff check src/sky/ ; mypy src/sky/
uvicorn sky.api.main:app --reload --port 8000
arq sky.worker.main.WorkerSettings
```

---

## 7. Seguridad

> Referencia detallada: `backend-python/docs/SECURITY.md`, `docs/SECURITY_INFRASTRUCTURE.md` (parcialmente desactualizado: escrito pre-cutover Node, conserva valor conceptual en modelo de amenaza), `DR_RUNBOOK.md`, `RUNBOOK_KEY_ROTATION.md`.

### 7.1 Modelo de amenaza — qué protege Sky

| Activo | Sensibilidad | Dónde vive |
|---|---|---|
| Credenciales bancarias (RUT + clave) | **Crítica** | `bank_accounts.encrypted_rut/pass` (cifradas) |
| Movimientos financieros | Alta | `transactions` (Postgres, RLS) |
| Saldos | Alta | `bank_accounts.last_balance` |
| Patrones de gasto | Media (anonimizada) | schema `aria.*` |
| Identidad (UUID) | Media | `auth.users` / `profiles.id` |
| Conversaciones con Mr. Money | Media (contexto financiero) | flujo a Anthropic, no persistido en DB |

`profiles` **no** guarda nombre, email ni RUT — solo UUID y preferencias. La PII la administra Supabase Auth.

### 7.2 Adversarios contemplados

- **Atacante con acceso a la DB** (filtración Supabase, dump comprometido). Las credenciales bancarias deben quedar inservibles.
- **Atacante con UUID válido** de un usuario. No debe poder leer ni mutar datos (cerrado por verificación JWT en Python).
- **Atacante con acceso al frontend o al browser** (XSS, devtools). No debe poder llamar a Anthropic, Supabase con `service_role`, ni ver claves del backend.
- **Atacante en la red** (MITM). Todo tránsito debe ser TLS.
- **Insider con acceso a logs.** Logs no deben contener passwords, RUTs, tokens.
- **Bots y abuso** disparando syncs en loop para quemar recursos.
- **Caída de un proveedor bancario** (riesgo de disponibilidad). Failover automático.

**Fuera de scope:** acceso físico a infra de Railway/Supabase, side-channels en Chromium, compromisos del SDK de Anthropic/Supabase publicados en PyPI.

### 7.3 Cifrado de credenciales

- **AES-256-GCM** con IV único (128 bits) por cifrado.
- Clave `BANK_ENCRYPTION_KEY` (hex 64 = 32 bytes), derivada por SHA-256 (compat binaria Node↔Python).
- Formato en DB: `iv:authTag:ciphertext` base64, o `v2:...` post-rotación.
- Segunda capa: Supabase cifra disco en reposo.
- Credenciales descifradas **solo en memoria del worker**; `del rut, password, creds` inmediato.
- Verificación al arranque: round-trip `verify_encryption_ready()`. Si falla, el proceso **falla en arranque** (Python).

### 7.4 Ciclo de vida de credenciales

1. Usuario ingresa RUT + clave en frontend.
2. Frontend llama `POST /api/banking/connect` (HTTPS).
3. Backend cifra **inmediatamente** — el plaintext **muere ahí**.
4. Ciphertext va a `bank_accounts.encrypted_rut` y `encrypted_pass`.
5. En cada sync: `decrypt()` en memoria → uso por el scraper → variable se descarta. **Nunca** se logea.
6. Disconnect: el endpoint sobrescribe `encrypted_rut/pass = "REMOVED"` y marca `status = "disconnected"`.

### 7.5 Transporte

- TLS 1.2+ end-to-end (Railway / Let's Encrypt). Sin HTTP plain en prod.
- HSTS: `max-age=63072000; includeSubDomains; preload`.

### 7.6 Autenticación y autorización

- JWT de Supabase verificado criptográficamente en `JWTContextMiddleware` (HS256, audience `authenticated`, firma + expiración).
- **RLS habilitado en todas las tablas `public.*`.** Schema `aria.*` solo `service_role`.
- `SUPABASE_SERVICE_KEY` nunca al frontend ni a logs.
- Endpoints internos (`/api/internal/*`) protegidos por `x-cron-secret`; sin `CRON_SECRET` → 503 fail-safe.

### 7.7 ARIA — anonimización en 5 pasos

Solo activo con `profiles.aria_consent = true`:

1. **Extracción** — evento real → señal estructurada.
2. **Categorización** — valor exacto → rango (monto → bucket, fecha → trimestre).
3. **Eliminación de identidad** — UUID descartado antes de escribir.
4. **Randomización intra-bucket** — valor guardado = random dentro del rango.
5. **Ruptura de correlaciones** — jitter temporal ±36h, batch_id propio.

Vistas analíticas con **k-anonymity ≥ 10** (mínimo 10 registros por agregado). Tablas: `aria.spending_patterns`, `goal_signals`, `behavioral_signals`, `session_insights`.

### 7.8 Audit log

- `public.audit_log` inmutable (solo INSERT). Eventos: `sync.start/success/error`, `account.connected/disconnected`, export, delete.
- `user_hash = SHA-256(user_id + AUDIT_LOG_SALT)` — correlación sin PII. Sin PII en metadata.
- Retención `AUDIT_LOG_RETENTION_DAYS` (90), purgado por `audit_purge_job` diario 03:00 UTC.
- ✅ **Bug corregido 2026-05-25:** `:detail::jsonb` rompía asyncpg con named params → 0 filas escritas históricamente. Fix: `CAST(:detail AS jsonb)`. Test de regresión agregado.

### 7.9 Rate limiting

- slowapi Redis-backed por `user_id` verificado (no IP). Default 60/min. Multi-instancia seguro.

### 7.10 Observabilidad protegida

- `/metrics` requiere `x-prometheus-secret` en prod (fail-fast si vacío).
- Sentry `before_send` con pipeline de dos pasos:
  1. `_scrub` recursivo: claves en `_SCRUB_KEYS` → `[REDACTED]`. Strings que matchean regex de tokens (`sk-ant-...`, `sk-proj-...`) o RUT chileno → `[REDACTED]`. Profundidad cap 10.
  2. `_event_contains_sensitive` post-scrub: serializa a JSON y reaplica regex. Si todavía detecta PII, **descarta el evento entero**.
  3. Fail-safe: excepción en cualquier paso → descarta el evento. Preferible perder telemetría que filtrar PII.
- Fail-fast si `SENTRY_DSN` vacío en prod.
- **Logging:** structlog con filter regex `(password|clave|rut|secret|token|api_key|authorization)` sobre claves de cada log dict → reemplazado por `***REDACTED***`. Convención: nunca pasar el valor sensible como mensaje — usar key=value.

### 7.11 Privacidad y cumplimiento

| Marco | Aplicabilidad | Estado en Sky |
|---|---|---|
| **Ley 19.628** (Protección de Datos Personales, Chile) | Aplica | Derecho al olvido en `profiles.deletion_requested_at` |
| **SFA** (CMF Chile) | Aplicará cuando esté activo | Arquitectura objetivo soporta `SFA` como `SourceKind` |
| **ISO/IEC 27001** | Referencia (no certificación) | Guía de gestión |
| **PCI-DSS** | **No aplica** | Sky no procesa pagos con tarjeta |

**Data export (art. 11):** `POST /api/account/export-request` → worker genera ZIP (transactions, goals, challenges, badges, audit propio) → signed URL 7d. Excluye `bank_accounts` (credenciales). Rate limit 5/min.

**Borrado de cuenta:** usuario solicita → `profiles.deletion_requested_at = now()` → job programado ejecuta hard-delete post periodo legal: `DELETE` en `transactions`, `bank_accounts`, `goals`, `challenge_states`, `earned_badges` por `user_id`; `DELETE` en `profiles` por `id`; `auth.users` vía Supabase admin API. `aria.*` no requiere acción (no contiene UUID).

### 7.12 Idempotencia

- Header `Idempotency-Key` (UUID v4) en POST con side-effects (`/banking/sync`, `/sync-all`, `/accounts`). Replay devuelve respuesta cacheada (TTL 24h).

### 7.13 Dependencias de terceros

| Vendor | Certificación | Riesgo |
|---|---|---|
| Supabase | SOC2 Type II | DB en US-East-1 |
| Railway | SOC2 | Infra US |
| Anthropic | Privacidad comercial | API calls, sin persistencia |

### 7.14 Runbooks de seguridad

- **Rotación de `BANK_ENCRYPTION_KEY`** (`RUNBOOK_KEY_ROTATION.md`): dual-decrypt → `rekey_bank_accounts.py --apply` → verificar prefijo `v2:` → retirar v1. Sin downtime, rollback seguro.
- **DR** (`DR_RUNBOOK.md`): 3 escenarios (Supabase down, Railway down, brecha de clave).
- **RLS verification:** `scripts/audit_rls_policies.py` antes de cada migración (exit 1 bloquea deploy).

### 7.15 Escenarios de amenaza y mitigaciones

- **Filtración de la DB Supabase:** movimientos legibles (no cifrados a nivel de campo); credenciales bancarias inservibles sin `BANK_ENCRYPTION_KEY` (que vive en Railway); `aria.*` no reidentificable. Acción: rotar `SUPABASE_SERVICE_KEY`, forzar logout, comunicar.
- **Filtración de `BANK_ENCRYPTION_KEY`:** worst case. Invalidar sesiones bancarias, borrar `encrypted_rut/pass` masivamente, comunicar, rotar. Estructural pendiente: key versioning automatizado.
- **JWT robado / replay:** access tokens cortos (1h Supabase default). Verificación criptográfica nativa en Python.
- **Compromise del SDK Anthropic/supabase-js:** mitigación parcial vía lock files. Pendiente: Dependabot + auditoría automática.
- **Phishing simulando Sky:** dominio único `app.skyfinanzas.com`, comunicación en producto, OAuth/SFA elimina necesidad de password.
- **Banco bloquea cuenta del usuario por scraping:** rate limit por proveedor, retry con backoff, failover a agregador/API directa cuando exista.

### 7.16 Deuda de seguridad reconocida

- P0-1 (JWT en Node) — **cerrado** por el cutover a Python (verificación criptográfica nativa).
- Gestión de secretos en Railway ENV (no Secrets Manager) — aceptable para MVP, escala documentada.
- Rotación de `BANK_ENCRYPTION_KEY` sin automatizar (procedimiento manual documentado).

---

## 8. Estado real y deuda viva

> Sección operada bajo doctrina §22: "la deuda se documenta, no se oculta".
> Referencia de deuda formal: `backend-python/docs/REMEDIATION_P0_P3.md`.
> **Última actualización:** 2026-05-25.

### 8.1 ✅ Lo que funciona (verificado)

- **Producción viva:** `app.skyfinanzas.com` + `api.skyfinanzas.com` responden 200.
- **Migración Python completa:** 13 fases cerradas, cutover hecho, Node archivado.
- **Categorización:** 3 capas funcionando. ~1.283 transacciones, 0 en `pending`, ~1.231 `done`, ~52 `failed` (fallback "other").
- **Display ingreso/gasto:** por signo del monto.
- **Cifrado, RLS, audit (parcial), data export, rate limit, idempotencia:** implementados.
- **Scraper BChile:** validado funcionando **desde IP residencial** — login + 2FA + 175 movimientos + balance, signos correctos.
- **Cola ARQ:** corregida.

### 8.2 ❌ Lo que NO funciona / bloqueadores

#### B-1 · Scraping bloqueado desde datacenter (anti-bot) — crítico arquitectónico

BChile está detrás de **Imperva Incapsula**. El scraper headless desde la **IP de datacenter de Railway** es detectado como bot y recibe una página-desafío sin formulario de login → falla con "No se encontró el campo de RUT". Desde IP residencial (laptop, browser visible) funciona.

**Causa raíz confirmada:** Incapsula detecta Playwright headless sin stealth (navigator.webdriver expuesto, User-Agent con "HeadlessChrome", fingerprint de Chromium bundled). Sirve challenge JS que bloquea el formulario → `_fill_rut` no encuentra el campo → `RecoverableIngestionError`.

**Palancas agregadas (2026-05-25):**
- `browser_headless=True/False` (setting, no redeploy).
- Stealth básico en `browser_pool.py`: `--disable-blink-features=AutomationControlled`, User-Agent realista de Chrome/Windows, `navigator.webdriver=undefined` via init_script, intentar `channel="chrome"` (Chrome de sistema).
- `scraper_debug_capture=True` (setting) + `scraper_debug_dir` — guarda screenshot + HTML al fallar (sin PII).

**Implicación:** el scraping en producción sigue siendo frágil. Stealth básico puede ayudar pero no es garantía (Incapsula es sofisticado). Para demo, el camino confiable es local-first (laptop). Fix real arquitectónico: proxy residencial o migración a SFA. **Refuerza la tesis SFA.**

#### B-2 · Scraper BCI roto — dominio cambiado

`portalpersonas.bci.cl` ya no resuelve (NXDOMAIN desde toda red probada; antes funcionaba). BCI cambió el dominio de su portal. Requiere rework: nuevo dominio + probablemente nuevos selectores y endpoints de API interna. BCI está en `pending`. Sprint propio pendiente.

#### ✅ B-3 · Auditoría — bug de runtime corregido (2026-05-25)

**Bug:** el INSERT en `sky/core/audit.py` usaba `:detail::jsonb`. Con SQLAlchemy `text()` + asyncpg, el cast `::jsonb` rompe el parseo del bind param nombrado `:detail` → asyncpg lanza `PostgresSyntaxError` en runtime. **Ningún evento de auditoría se escribía en Postgres real** desde el inicio del sistema.

**Fix:** `CAST(:detail AS jsonb)`. Test de regresión en `tests/unit/test_audit.py` (`test_sql_uses_cast_not_postgres_cast_syntax`).

**Estado:** ✅ corregido y cubierto por test. Verificación de runtime con Postgres de staging sigue siendo recomendable.

#### B-4 · Balance visible tras desconectar cuenta

`handleDisconnect` en `BankConnect.jsx` llamaba `loadAccounts()` pero no llamaba `onSyncComplete?.()`, que es el callback que refresca `bankBalances` en `Sky.jsx`. **Corregido** (2026-05-23): se agregó `onSyncComplete?.()` tras `loadAccounts()`. Verificación visual de QA manual pendiente.

#### B-5 · Lentitud general

La app se siente lenta. Sin profiling aún. Sospechas: cold-start de Railway, queries de `/summary`/`/transactions`, re-renders del god-component `Sky.jsx`, polling de `BankConnect` cada 5s. **Medir antes de optimizar.**

### 8.3 ✅ Corregido recientemente (mayo 2026)

| Fix | Detalle |
|---|---|
| **Cola ARQ** | `worker/main.py` ahora crea el pool con `default_queue_name="sky:default"`. Antes, `categorize_pending_job` caía en `arq:queue` (fantasma) y nunca corría → "Procesando..." eterno + todo rojo. Causa raíz de dos síntomas. |
| **Income display** | `Sky.jsx` usa `tx.amount > 0` (3 lugares) en vez de `category === "income"`. |
| **BankConnect** | `Promise.allSettled` — la lista de bancos no se rompe si `/accounts` falla. |
| **VITE_API_URL** | Reapuntado de `api-v2` (canary muerto) a `api.skyfinanzas.com`. |
| **Listado bancos** | `SUPPORTED_BANKS` solo expone BChile + BCI. |
| **SyntaxWarning `\S`** | Docstrings de scripts como raw strings. |
| **PII en logs scraper** (2026-05-23) | Eliminados dos `logger.info` que registraban RUT, nombre y nº de cuenta a nivel INFO en `bchile_scraper.py`. Doctrina §16. |
| **Transparencia de errores de sync** (2026-05-23) | `AllSourcesFailedError` conserva la causa; mensaje al usuario por tipo de error; no se reintentan fallos terminales (ARQ). |
| **propose_challenge roto** (2026-05-23) | La tool generaba desafíos freeform sin `challenge_id`; el frontend esperaba `{type, input:{challenge_id, reasoning}}` y crasheaba. Restaurada la paridad con `MOCK_CHALLENGES`. |
| **Tests de chat rotos** (2026-05-23) | 4 tests de `test_api_chat.py` asertaban el contrato viejo (`type/text/route`) ya reemplazado por `ChatUnifiedResponse`. Actualizados. |
| **ruff verde** (2026-05-23) | Limpiadas 17 violaciones preexistentes. Gate `ruff check exit 0` se cumple. |
| **audit INSERT roto (B-3)** (2026-05-25) | `:detail::jsonb` rompía asyncpg con named params → 0 filas escritas. Corregido con `CAST(:detail AS jsonb)`. Test de regresión. |
| **Mr. Money: logging silencioso en errores Anthropic** (2026-05-25) | `except` usaba `logger.warning` sin traceback. Cambiado a `logger.error(exc_info=True)` con detección explícita de `AuthenticationError`/`APIStatusError`. |
| **Stealth anti-bot básico en browser_pool** (2026-05-25) | `--disable-blink-features=AutomationControlled`, UA realista, `navigator.webdriver=undefined`. Palancas `browser_headless` + `scraper_debug_capture`. |
| **Validators fail-fast en Settings** (2026-05-25) | `field_validator` en pydantic v2 para secrets críticos: vacío/espacios → error al arrancar. `anthropic_api_key` valida además prefijo `sk-ant`. |

### 8.4 🧹 Rastrilleo de deuda menor (2026-05-23)

Hallazgos del barrido de calidad. No bloquean, pero se documentan para no acumularse (doctrina §22):

| ID | Item | Nota |
|---|---|---|
| ✅ **R-1** | ~~Lista de bancos duplicada en 4+ lugares~~ | **Cerrado 2026-05-23.** `SUPPORTED_BANKS` (incl. `account_type`) es la fuente única. `_DEFAULT_ACCOUNT_TYPE` eliminado de `banking.py` y `summary.py`. `DEFAULT_RULES` alineado a bchile+bci. |
| **R-2** | Naming engañoso de BCI | `BCIDirectSource` (archivo `bci_direct.py`) tiene `source_identifier == "scraper.bci"` y BCI es un scraper (no API directa). Renombrar a `BCIScraperSource`/`bci_scraper.py` cuando se haga el rework B-2. |
| ✅ **R-3** | ~~`FalabellaScraperSource` muerto~~ | **Cerrado 2026-05-23.** Dejó de registrarse en `build_all_sources`. |
| ✅ **R-4** | ~~`RuntimeWarning: coroutine never awaited`~~ | **Cerrado 2026-05-24.** Fixture autouse en `test_sync_job` deshabilita la tarea fire-and-forget de ARIA. Suite sin warnings. |
| **R-5** | Webhooks sin verificación de firma | `webhooks.py`: TODO de validar HMAC-SHA256 nunca implementado. Cerrar cuando se cablee Fintoc (agregar HMAC primero). |
| ✅ **R-6** | ~~Sin gate automático~~ | **Cerrado 2026-05-23.** `.githooks/pre-push` corre ruff+mypy+pytest antes de cada push. |
| ✅ **R-7** | ~~BOM en 3 mensajes de commit~~ | **Cerrado 2026-05-24.** Removido el BOM UTF-8 vía `git filter-branch --msg-filter`. |

### 8.5 Deuda de infraestructura

- **`appealing-benevolence`** (Node legacy) sigue online en Railway — decomisionar.
- **`api-v2.skyfinanzas.com`** — custom domain leftover del canary, devuelve 502. Limpiar.
- **Warm standby** en Fly.io recomendado (DR Railway).

### 8.6 Inventario de deuda P0-P3 (de `REMEDIATION_P0_P3.md`)

| ID | Item | Estado |
|---|---|---|
| P0-1 | JWT auth verificado | ✅ Cerrado por cutover Python |
| P0-2 | Consent ARIA | ✅ Resuelto |
| P0-3 | Refresh post-sync | ✅ Resuelto |
| P1-1 | `Sky.jsx` god-component (1.600 LOC) | Abierto — refactor frontend |
| P1-2 | CORS permisivo | ✅ Cerrado (fail-fast en prod) |
| P2-1..4 | Tests/CI/rate limit/monitoring | Mayormente cerrados (Fase 10-11) |
| P2-6 | Rotación `BANK_ENCRYPTION_KEY` | Procedimiento manual documentado |
| BUG-1..4 | external_id / upsert / lock / sync secuencial | ✅ Cerrados en Python |

### 8.7 Prioridades sugeridas (orden)

1. **Prep del pitch BCI** (objetivo de negocio inmediato — ver `Documentacion_Externa_Reuniones_Bancos/`).
2. **B-3** ✅ cerrado — correr `log_event(...)` contra Postgres staging para confirmar que `resource_id uuid` acepta `str` (asyncpg cast). 10 min.
3. **B-4** ~~balance post-disconnect~~ — código corregido; pendiente QA visual.
4. **B-2** rework scraper BCI (sprint propio).
5. **B-1** resiliencia anti-bot datacenter — stealth básico agregado; evaluar si es suficiente o se necesita proxy residencial.
6. **B-5** performance (profiling primero).
7. Decomisionar Node legacy + limpiar `api-v2`.

---

## 9. Doctrina — 23 reglas inviolables

> Decisiones doctrinales firmadas por los cofundadores **antes** de la primera línea de código en producción. Sobreescriben conveniencia de corto plazo. No se negocian durante construcción.
> Fuente: v5 §26 + §13.2 + §14.4 + §15.4 + Parte III §20 (registrado ante INAPI).

### I. Producto

1. **El producto debe sentirse ligero.** La ligereza es feature, no limitación.
2. **Mr. Money guía; no decide.** Toda propuesta estructurada requiere confirmación explícita del usuario.
3. **La confianza vale más que cualquier monetización rápida.**
4. **El frontend NO es la fuente de verdad.** Toda lógica crítica vive en el backend.
5. **Los datos del usuario existen primero para servir al usuario.**

### II. Arquitectura

6. **La arquitectura desacopla** proveedor bancario, lógica de negocio y analytics.
7. **El dominio jamás pregunta de qué `source` vino un movimiento.** Si necesita distinguir origen, el modelo canónico está incompleto — se enriquece, no se rompe la abstracción.
8. **Modelo canónico único:** todo proveedor devuelve `CanonicalMovement`.
9. **La arquitectura tolera pivotes estratégicos.** Ningún proveedor/banco/integración es inamovible.
10. **La API Python NUNCA importa Playwright.** El worker es el único con browser pool. API y worker son procesos deployables independientes.

### III. Ingestión y resiliencia

11. **Scraper como fallback permanente.** Incluso tras APIs directas/SFA, queda como última línea. Solo se elimina si un contrato lo exige.
12. **`AuthenticationError` NO dispara failover.** La credencial es el problema; todos los proveedores la rechazarían.
13. **Rate limit = `skip`, no `fail`.** El siguiente provider de la cadena se intenta.
14. **Configuración como palanca operativa:** cambios de estrategia (activar BCI directo al 5%, mover Fintoc a primera línea) son `UPDATE` a `ingestion_routing_rules`, no deploys.

### IV. Seguridad

15. **`SUPABASE_SERVICE_KEY` y `BANK_ENCRYPTION_KEY` solo en backend.** Nunca en frontend, repo, ni logs.
16. **Credenciales bancarias = AES-256-GCM con IV único** (formato `iv:authTag:ciphertext`, compat binaria Node↔Python).
17. **IA (Anthropic) solo desde el backend.** Nunca desde el browser.
18. **RLS habilitado en TODAS las tablas de `public`.** Schema `aria` bloqueado a clientes (solo service_role escribe).
19. **Frontend NUNCA llama a Supabase con `service_role` ni a Anthropic directo.**
20. **Errores de scraper sanitizados** antes de mostrarse (eliminar password, rut, stack, timeouts).

### V. Privacidad

21. **ARIA solo se activa con `aria_consent = true`.** Sin UUID en `aria.*`. Service_role exclusivo.

### VI. Operación

22. **La deuda técnica se documenta, no se oculta.** Honestidad narrativa.
23. **La ambición debe merecerse con ejecución disciplinada.** Cada fase tiene gate de verificación; si el gate falla, la fase no está completa.

### Cómo se aplica

Estas reglas son **auditables contra el código**. Cuando un cambio propuesto contradice una de ellas, se rechaza en code review, sin negociación. Si una regla necesita cambiar, primero se actualiza el v5 (registro INAPI), después este documento. Nunca al revés.

**Firmado por:**
**Cristian Cristóbal Amaru Vásquez Guevara** — RUT 22.141.522-1
**Juan José Latorre Pérez** — RUT 22.003.365-1
Cofundadores · SkyFinanzas SpA · RUT 78.395.382-K

---

## Apéndice A — Contexto para reunión con bancos

### A.1 Qué somos para el banco

Sky es **un consumer de datos bancarios** (no compite con el banco como producto financiero). Hoy lee cuentas vía scraping autorizado por el usuario; mañana las leerá vía SFA cuando el banco lo libere. El banco gana:

- **Volumen de uso** de su SFA con un consumer maduro y técnico (justifica inversión ante CMF y directorio).
- **Migración silenciosa** scraping → SFA sin re-onboarding del usuario, gracias al `external_id` determinístico que une historial.
- **Métricas de adopción** y telemetría de calidad de su API (latencia, tasa de error, brechas de cobertura).
- **Reducción de carga de scraping** sobre su portal web — lo que hoy llega como tráfico automatizado pasa a la API con auth proper.

### A.2 Honestidad técnica que conviene poner en la mesa

- **El scraping es frágil** y los bancos lo saben. Sky no esconde esto: lo argumenta como la razón para el SFA (B-1, B-2).
- **Sky ya está construido para el SFA** desde el contrato `DataSource` (kind=SFA, auth_mode=CONSENT_TOKEN). Migrar un banco es un `UPDATE` a `ingestion_routing_rules`, no un rewrite (regla doctrinal §14).
- **Seguridad seria desde el día uno:** AES-256-GCM con IV único, RLS en toda `public.*`, JWT verificado criptográficamente, audit log inmutable, PII scrubbing en Sentry y logs, data export Ley 19.628 implementado, runbook de rotación de clave maestra documentado.
- **ARIA es un activo institucional:** dataset de comportamiento financiero chileno anonimizado con k-anonymity ≥ 10, sin UUID, randomización intra-bucket. Posible base para productos B2B futuros (gobierno, aseguradoras, el propio banco como inteligencia agregada).

### A.3 Lo que pediríamos / negociaríamos

- **Acceso temprano al SFA** del banco antes de su release público — Sky aporta volumen y QA.
- **Identificación como consumer registrado** (no como tráfico anónimo) para sacar al scraping de la lista de cargas no deseadas mientras coexiste el periodo de transición.
- **Acuerdo bilateral de pre-SFA** (API directa) si el SFA tarda — modelo `BANK_API_DIRECT` ya en el contrato.

### A.4 Lo que el banco va a preguntar (anticipar)

- **¿Cómo guardan las claves bancarias?** → AES-256-GCM, clave maestra solo en backend, descifrado en memoria volátil, ciclo de vida documentado (§7.3, §7.4).
- **¿Qué pasa si los hackean?** → modelo de amenaza explícito (§7.2, §7.15). En filtración de DB las credenciales quedan inservibles; en filtración de la clave hay runbook de invalidación masiva. Próximo paso: key versioning automatizado.
- **¿Tienen certificación?** → No ISO27001/SOC2 propia hoy. Stack apoyado en Supabase (SOC2 Type II) y Railway (SOC2). Disposición a iniciar proceso si el banco lo exige como condición. Decisión de secretos manager documentada con condición de escalada explícita.
- **¿Cuánto tráfico nos generan hoy?** → BChile: scraping ocasional por usuario, frecuencia configurable, rate limit por proveedor (sliding window log atómico en Redis). BCI: 0 (scraper roto).
- **¿Dónde están los datos?** → Postgres en Supabase US-East-1, RLS, PITR 7 días. Cumple Ley 19.628; arquitectura compatible con CMF SFA (consent tokens, scopes).
- **¿Quién opera esto?** → dos cofundadores, doctrina firmada (registrada INAPI), 386 tests automatizados, gates de calidad pre-push.

### A.5 Documentación complementaria para enviar al banco

- `backend-python/docs/SECURITY.md` — controles activos detallados.
- `backend-python/docs/DR_RUNBOOK.md` — escenarios de DR.
- `backend-python/docs/RUNBOOK_KEY_ROTATION.md` — procedimiento de rotación.
- `backend-python/docs/API_CONTRACT.md` — contrato de la API.
- `SkyFinanzas_EstadoDelArte_v5_Documentado.pdf` (registrado INAPI) — doctrina y modelo arquitectónico.

---

## Apéndice B — Glosario

| Término | Significado |
|---|---|
| **Mr. Money** | Asistente financiero conversacional de Sky, sobre Claude. Guía, no decide. |
| **ARIA** | Anonymized Randomized Intelligence Architecture. Capa de analytics anónimos agregados. Consent explícito, sin UUID. |
| **DataSource** | Contrato abstracto de toda fuente de datos bancarios (5 tipos). |
| **CanonicalMovement** | Modelo único al que se normaliza todo movimiento, sin importar el origen. |
| **SFA** | Sistema Financiero Abierto — Open Banking regulado chileno (CMF). |
| **IngestionRouter** | Orquestador de proveedores con failover, circuit breaker y rate limit. |
| **v5** | El PDF doctrinal registrado ante INAPI; fuente de verdad legal. |
| **AEAD** | Authenticated Encryption with Associated Data. AES-GCM lo provee. |
| **RLS** | Row Level Security de Postgres. |
| **PITR** | Point-In-Time Recovery (Supabase Pro, 7 días). |
| **k-anonymity** | Garantía de que cada registro agregado es indistinguible de al menos k-1 otros (Sky usa k=10). |

---

*Fin del dossier.*
