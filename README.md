> **Propiedad intelectual registrada ante INAPI Chile — Estado del Arte v5, Abril 2026.**
> Source-available, uso educativo únicamente. Ver [LICENSE](./LICENSE).

---

# Sky Finanzas

Sistema operativo financiero personal impulsado por IA. Conecta cuentas bancarias, categoriza transacciones automáticamente y pone a **Mr. Money** — agente financiero con contexto completo — a disposición del usuario para dar claridad, aterrizar metas y reducir ansiedad financiera.

> La premisa: las personas no fallan financieramente por falta de conocimiento, sino porque el dinero genera ansiedad, evasión y fricción cognitiva. Sky absorbe esa complejidad y devuelve claridad.

**Producción:** [app.skyfinanzas.com](https://app.skyfinanzas.com) · [skyfinanzas.com](https://skyfinanzas.com)  
**Repositorio:** github.com/TioCristian007/SkyFinance  
**Stack actual:** Node.js + Express · React + Vite · Anthropic Claude · Supabase · AES-256-GCM  
**Stack objetivo (en migración):** Python 3.12 + FastAPI · ARQ + Redis · Playwright · structlog · Prometheus

---

## Contexto: dos backends, una migración activa

Este monorepo contiene **dos backends en paralelo**:

| Directorio | Estado | Rol |
|---|---|---|
| `backend/` | **En producción** en Railway | Node.js + Express. Backend original. Toda la lógica de negocio operativa. |
| `backend-python/` | **En migración activa** (Fase 4 completada) | FastAPI + Playwright. Rewrite para escala, resiliencia multiproveedor y deuda técnica. |
| `frontend/` | **En producción** | React + Vite. No cambia en la migración. |

La migración a Python no es un rewrite desde cero: es una transición por fases con parity tests y cutover gradual. El frontend consume el mismo contrato de API en ambos backends. El backend Node sigue siendo la fuente de verdad en producción hasta que la migración esté completa y validada.

---

## Reglas doctrinales (no negociables)

```
Frontend     →  solo muestra, captura y llama al backend
Backend      →  calcula, decide, guarda, llama a la IA
IA           →  solo desde el backend, nunca desde el browser
ARIA         →  solo escribe en analytics, nunca lee datos de usuarios
Cifrado      →  solo el backend conoce BANK_ENCRYPTION_KEY
Mr. Money    →  guía y propone; el usuario ejecuta — nunca decide
DataSource   →  nada en el dominio puede preguntar de qué proveedor vino un movimiento
```

---

## Estructura del monorepo

```
SkyFinance/
├── backend/                        ← Backend Node.js — EN PRODUCCIÓN
│   ├── server.js                   ← entry point + verificación de cifrado
│   ├── middleware/
│   │   └── auth.js                 ← extrae userId del header (P0-1: sin JWT verify)
│   ├── routes/
│   │   ├── banking.js              ← /api/banking — conectar, sync, cuentas
│   │   ├── chat.js                 ← /api/chat → Mr. Money
│   │   ├── transactions.js         ← CRUD /api/transactions
│   │   ├── summary.js              ← /api/summary
│   │   ├── goals.js                ← CRUD /api/goals
│   │   ├── challenges.js           ← /api/challenges — activar, completar
│   │   ├── simulate.js             ← /api/simulate
│   │   └── internal.js             ← /api/internal — cron secret-protected
│   └── services/
│       ├── aiService.js            ← Mr. Money: detección local + Claude SDK
│       ├── ariaService.js          ← pipeline ARIA: anonimización + analytics
│       ├── bankingAdapter.js       ← abstracción de proveedor (único punto de cambio)
│       ├── bankSyncService.js      ← orquestador de sync bancario
│       ├── categorizerService.js   ← categorización 3 capas: reglas + caché + Claude
│       ├── dbService.js            ← helpers Supabase
│       ├── encryptionService.js    ← AES-256-GCM para credenciales bancarias
│       ├── financeService.js       ← summary, metas, desafíos, simulaciones
│       └── supabaseClient.js       ← clientes anon / admin / aria
│
├── backend-python/                 ← Backend Python — EN MIGRACIÓN (Fase 4/13)
│   ├── src/sky/
│   │   ├── core/                   ← config, db, encryption, locks, logging, metrics
│   │   ├── ingestion/              ← contrato DataSource + scrapers + router + circuit breaker
│   │   │   ├── contracts.py        ← DataSource, CanonicalMovement — pieza más protegida
│   │   │   ├── browser_pool.py     ← pool reutilizable de Playwright (stealth activo)
│   │   │   ├── circuit_breaker.py  ← Redis — open/closed/half-open por source
│   │   │   ├── rate_limiter.py     ← token bucket por proveedor
│   │   │   ├── routing/            ← IngestionRouter con failover automático
│   │   │   └── sources/            ← scrapers: BChile, Falabella, BCI, Fintoc...
│   │   ├── domain/                 ← lógica de negocio (agnóstica de proveedor)
│   │   │   ├── mr_money.py         ← agente Mr. Money — Claude Python SDK
│   │   │   ├── aria.py             ← pipeline anonimización con consent guard
│   │   │   ├── categorizer.py      ← 3 capas: reglas + caché + Claude
│   │   │   ├── finance.py          ← summary, balance, tasa de ahorro
│   │   │   ├── goals.py
│   │   │   ├── challenges.py
│   │   │   └── simulations.py
│   │   ├── api/                    ← FastAPI — paridad 1:1 con endpoints Node
│   │   │   ├── main.py             ← create_app + CORS + lifespan
│   │   │   ├── middleware/         ← jwt_auth (P0-1 resuelto), rate_limit, tracing
│   │   │   ├── schemas/            ← Pydantic v2
│   │   │   └── routers/            ← banking, chat, goals, transactions...
│   │   └── worker/                 ← ARQ — separado del API, maneja Playwright
│   │       ├── main.py             ← WorkerSettings + browser pool lifecycle
│   │       ├── banking_sync.py     ← orquestador con pg_try_advisory_lock
│   │       └── jobs/               ← sync, categorize, scheduled, webhook
│   ├── tests/
│   │   ├── unit/                   ← encryption_compat, contracts, router, circuit_breaker
│   │   ├── integration/
│   │   └── parity/                 ← diff de responses Node ↔ Python durante cutover
│   └── scripts/
│       ├── test_bchile_scraper.py
│       ├── test_bci_scraper.py
│       └── verify_encryption_compat.py
│
└── frontend/                       ← React + Vite — EN PRODUCCIÓN
    └── src/
        ├── App.jsx                 ← auth gate: loading | auth | onboarding | app
        ├── Sky.jsx                 ← coordinador principal (P1-1: 1678 líneas, pendiente split)
        ├── components/             ← AuthScreen, BankConnect, ChatComponents, Goals...
        ├── services/
        │   ├── api.js              ← único canal frontend → backend
        │   └── supabase.js         ← Supabase Auth client
        └── utils/format.js         ← formateo CLP, fechas
```

---

## Bancos soportados

| Banco | Estado | Backend | Método |
|---|---|---|---|
| Banco de Chile | Activo | Node.js + Python | Scraper Playwright + 2FA app |
| Banco Falabella | Activo | Node.js + Python | Scraper Playwright |
| BCI | En desarrollo | Python | Scraper Playwright (scraper completado, stealth + captcha handler activo) |
| Santander Chile | Planificado Fase 2 | Python | API directa (bajo negociación) |
| Banco Estado | Planificado Fase 2 | Python | Por definir |
| Itaú / Scotiabank | Planificado Fase posterior | Python | Por definir |
| Fintoc (agregador) | Planificado Mes 1-2 post-migración | Python | FintocSource via DataSource |

### Flujo de conexión bancaria (arquitectura actual)

1. Usuario ingresa RUT y clave en `BankConnect.jsx`
2. Backend cifra ambos con AES-256-GCM → solo el ciphertext toca Supabase
3. En cada sync: descifra en memoria → scraper extrae movimientos → normaliza a modelo canónico → deduplica → inserta → ARIA en background
4. Para Banco de Chile: detecta pantalla 2FA → reporta estado en tiempo real → frontend hace polling → usuario aprueba en app bancaria → scraper continúa
5. El sync es fire-and-forget: responde `{started: true}` inmediato, el frontend refresca datos via `useLiveData` (cada 15s + visibilitychange + online)

### Cambiar de proveedor bancario

En el backend Node: `bankingAdapter.js` es la única capa que conoce el proveedor. Migrar = modificar solo ese archivo.

En el backend Python: cada banco es una clase que implementa `DataSource` en `ingestion/sources/`. Agregar un banco = agregar un archivo + una regla en `ingestion_routing_rules`. El dominio nunca toca esa capa.

---

## API endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/summary` | Resumen financiero + perfil + badges + bancos conectados |
| GET | `/api/transactions` | Lista de transacciones |
| POST | `/api/transactions` | Agrega transacción manual |
| DELETE | `/api/transactions/:id` | Elimina transacción |
| POST | `/api/chat` | Chat con Mr. Money |
| GET | `/api/challenges` | Estado de desafíos |
| POST | `/api/challenges/:id/activate` | Activa desafío |
| POST | `/api/challenges/:id/complete` | Completa desafío |
| POST | `/api/simulate` | Simulación de escenario de ahorro |
| GET | `/api/goals` | Lista de metas con proyección temporal |
| POST | `/api/goals` | Crea meta |
| PATCH | `/api/goals/:id` | Actualiza ahorro de meta |
| DELETE | `/api/goals/:id` | Elimina meta |
| GET | `/api/banking/accounts` | Cuentas bancarias conectadas |
| POST | `/api/banking/accounts` | Conecta nueva cuenta |
| POST | `/api/banking/accounts/:id/sync` | Dispara sync bancario |
| DELETE | `/api/banking/accounts/:id` | Desconecta cuenta |
| POST | `/api/internal/scheduled-sync` | Cron interno (auth por secret) |

---

## Setup local

### Backend Node.js (producción actual)

```bash
cd backend
cp .env.example .env
# Completar con las keys reales (ver tabla de variables abajo)
npm install
npm run dev
# Servidor en http://localhost:3001
```

### Backend Python (en migración)

```bash
cd backend-python
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium

# Para levantar el API:
uvicorn sky.api.main:app --reload --port 8000

# Para levantar el worker ARQ:
arq sky.worker.main.WorkerSettings

# Para correr tests de scrapers:
python scripts/test_bchile_scraper.py TU_RUT TU_CLAVE
python scripts/test_bci_scraper.py TU_RUT TU_CLAVE        # browser visible por defecto
python scripts/test_bci_scraper.py TU_RUT TU_CLAVE --headless
```

### Frontend

```bash
cd frontend
cp .env.example .env
# Completar VITE_API_URL, VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY
npm install
npm run dev
# App en http://localhost:5173
```

### Verificar

```
http://localhost:5173              → pantalla de login
http://localhost:3001/api/health   → {"status":"ok","app":"sky-backend"}
http://localhost:8000/api/health   → FastAPI health (cuando esté levantado)
```

---

## Variables de entorno

### `backend/.env` (Node.js)

| Variable | Descripción | Nivel de seguridad |
|---|---|---|
| `ANTHROPIC_API_KEY` | API key Anthropic (Mr. Money) | Solo backend |
| `SUPABASE_URL` | URL del proyecto Supabase | — |
| `SUPABASE_ANON_KEY` | Anon key de Supabase | — |
| `SUPABASE_SERVICE_KEY` | Service role key — **nunca en frontend** | Solo backend |
| `BANK_ENCRYPTION_KEY` | Clave maestra AES-256-GCM para credenciales bancarias | **Crítica — solo backend** |
| `BCHILE_2FA_TIMEOUT_SEC` | Timeout de espera 2FA Banco de Chile (default: 120) | — |
| `CHROME_PATH` | Ruta a Chromium (auto-detecta; en Linux: `/usr/bin/google-chrome`) | — |
| `PORT` | Puerto del servidor (default: 3001) | — |
| `CORS_ORIGINS` | Allowlist CORS separada por comas — **requerida en producción** | — |

### `backend-python/.env`

| Variable | Descripción |
|---|---|
| `ANTHROPIC_API_KEY` | API key Anthropic |
| `SUPABASE_URL` | URL del proyecto Supabase |
| `SUPABASE_SERVICE_KEY` | Service role key |
| `BANK_ENCRYPTION_KEY` | Misma clave que Node.js — compatibilidad binaria garantizada |
| `REDIS_URL` | URL de Redis para ARQ y circuit breaker |
| `DATABASE_URL` | PostgreSQL URL para SQLAlchemy async |

### `frontend/.env`

| Variable | Descripción |
|---|---|
| `VITE_API_URL` | URL del backend (default: `http://localhost:3001/api`) |
| `VITE_SUPABASE_URL` | URL del proyecto Supabase |
| `VITE_SUPABASE_ANON_KEY` | Anon key de Supabase |

---

## Base de datos (Supabase)

Los archivos SQL de migración están en el repositorio separado `SupabaseSQLQuerys/`. Aplicar en orden en Supabase SQL Editor. Todos son re-ejecutables (`IF NOT EXISTS`).

Para el backend Python, las migraciones adicionales están en `backend-python/migrations/`:

```
001_routing_rules.sql         ← tabla ingestion_routing_rules (IngestionRouter)
002_indexes_and_constraints.sql ← uniq_tx_identity + índices de performance
003_webhook_events_seen.sql   ← idempotencia de webhooks (futuro)
004_bank_tokens.sql           ← token vault OAuth (futuro)
```

### Esquema `public` (con RLS)

| Tabla | Propósito |
|---|---|
| `profiles` | UUID + preferencias. Sin nombre real, email, RUT ni documento. |
| `transactions` | Movimientos manuales y bancarios. `external_id` para deduplicación. |
| `bank_accounts` | Cuentas conectadas. `encrypted_rut` y `encrypted_pass` AES-256-GCM. |
| `goals` | Metas financieras con proyección temporal. |
| `challenge_states` | Estado de desafíos por usuario. |
| `earned_badges` | Badges. `UNIQUE(user_id, badge_id)`. |
| `merchant_categories` | Caché global de categorías. Solo `service_role` escribe. |
| `ingestion_routing_rules` | Cadena de proveedores por banco, editable sin redeploy. |

### Esquema `aria` (bloqueado a clientes)

| Tabla | Contenido |
|---|---|
| `spending_patterns` | Patrones de gasto por bucket y segmento. Sin UUID. |
| `goal_signals` | Tipo, tier y completion rate de metas. Sin UUID. |
| `behavioral_signals` | Motivaciones y bloqueos detectados por Mr. Money. Sin UUID. |
| `session_insights` | Comportamiento de navegación y uso. Sin UUID. |
| `v_motivation_by_cohort` | Vista analítica (mínimo 10 registros). |
| `v_spending_by_segment` | Vista analítica (mínimo 10 registros). |

---

## ARIA — Anonymized Randomized Intelligence Architecture

Pipeline de anonimización que genera un dataset de comportamiento financiero chileno sin posibilidad de reidentificación. Solo activo si `aria_consent = true` en el perfil del usuario.

**5 pasos del pipeline:**
1. Extracción: evento real → señal estructurada
2. Categorización: valor exacto → rango (monto → bucket, fecha → trimestre)
3. Eliminación de identidad: UUID descartado antes de escribir en `aria.*`
4. Randomización intra-bucket: valor guardado = random dentro del rango, no el real
5. Ruptura de correlaciones: jitter temporal ±36h, `batch_id` propio por registro

**Valor estratégico:** dataset de comportamiento financiero chileno para bancos, gobierno, fondos de inversión y aseguradoras. La monetización, si ocurre, es consecuencia de la confianza.

---

## Seguridad

**Controles activos:**
- Credenciales bancarias cifradas AES-256-GCM con IV único por campo
- `SUPABASE_SERVICE_KEY` y `BANK_ENCRYPTION_KEY` solo en el backend — nunca en el frontend
- RLS en todas las tablas de usuario
- Esquema `aria.*` bloqueado a clientes — solo `service_role` escribe
- Mr. Money llama a Anthropic solo desde el backend
- Verificación de integridad de cifrado al arrancar (`verifyEncryptionReady`)
- Credenciales bancarias nunca se logean, ni en debug
- Errores de scraper sanitizados antes de mostrarse al usuario
- HTTPS end-to-end en producción (Railway + Squarespace DNS)
- Backend Python: JWT verificado en middleware (`jwt_auth.py`) — resuelve P0-1

**Deuda de seguridad abierta (ver sección siguiente):**
- P0-1: backend Node no verifica JWT (lee header `x-user-id` sin verificar token Supabase)
- P0-2: consentimiento ARIA no se aplica en el flujo bancario de Node

---

## Deuda técnica documentada

La deuda se documenta, no se oculta. Estado a Abril 2026.

### P0 — Bloqueantes para escala pública

| ID | Descripción | Estado | ETA |
|---|---|---|---|
| P0-1 | Backend Node no verifica JWT — lee `x-user-id` sin validar token Supabase | Abierto | Migración Python (resuelto en `jwt_auth.py`) |
| P0-2 | Consentimiento ARIA no se evalúa en flujo de sync bancario (Node) | Abierto | 30 min de trabajo — próximo sprint |
| P0-3 | Refresh en vivo de datos post-sync | **Resuelto** Abril 2026 | — |

### P1 — Fragilidad estructural

| ID | Descripción | Estado |
|---|---|---|
| P1-1 | `Sky.jsx` god-component — 1678 líneas | Abierto — extraer hooks + TanStack Query |
| P1-2 | CORS permisivo por fallback si `CORS_ORIGINS` está vacío en producción | Abierto |

### P2 — Higiene operacional

| ID | Descripción | Estado |
|---|---|---|
| P2-1 | Sin tests automatizados en Node | Abierto — cubierto en Python (unit + parity) |
| P2-2 | Sin CI/CD (GitHub Actions) | Abierto — `ci.yml` en backend-python, pendiente Node |
| P2-3 | Sin rate limiting | Abierto — `rate_limit.py` en Python, pendiente Node |
| P2-4 | Sin monitoring (Sentry / Prometheus) | Abierto — Prometheus en Python (Fase 10) |
| P2-5 | Paralelismo Puppeteer sin límite (sync secuencial como mitigación) | Mitigado — browser pool en Python |
| P2-6 | Sin procedimiento de rotación de `BANK_ENCRYPTION_KEY` | Abierto — key versioning en Python |

### Bugs estructurales

| ID | Descripción | Estado |
|---|---|---|
| BUG-1 | `external_id` inconsistente — dos implementaciones en Node | Resuelto en Python (única función `build_external_id`) |
| BUG-2 | Upsert apunta a UNIQUE INDEX inexistente en transactions | Resuelto en Python (`002_indexes_and_constraints.sql`) |
| BUG-3 | Locks en memoria del proceso (no escala con múltiples workers) | Resuelto en Python (`pg_try_advisory_lock`) |
| BUG-4 | Sync secuencial entre bancos del mismo usuario (~5 min para 6 bancos) | Resuelto en Python (browser pool paralelo, ~90s) |

---

## Plan de migración Python (13 fases)

| Fase | Objetivo | Estado |
|---|---|---|
| Fase 0 | Scaffolding del repo Python | Completada |
| Fase 1 | Contrato DataSource y modelo canónico | Completada |
| Fase 2 | Core infrastructure: config, DB, logging, errors | Completada |
| Fase 3 | EncryptionService compatible binario con Node | Completada |
| Fase 4 | BChileScraperSource + BCIScraperSource con Playwright + browser pool | **Completada** |
| Fase 5 | IngestionRouter, circuit breaker, rate limit | En progreso |
| Fase 6 | Queue system con ARQ | Pendiente |
| Fase 7 | FastAPI con paridad 1:1 de endpoints Node | Pendiente |
| Fase 8 | Dominio: Mr. Money, ARIA, finance service | Pendiente |
| Fase 9 | Scheduler como ARQ cron | Pendiente |
| Fase 10 | Observabilidad: métricas + tracing + healthchecks | Pendiente |
| Fase 11 | Dockerización y despliegue | Pendiente |
| Fase 12 | Migraciones SQL e índices faltantes | Pendiente |
| Fase 13 | Parity tests y cutover gradual | Pendiente |

No se avanza a la siguiente fase sin validar la anterior.

---

## Roadmap estratégico

| Fase de negocio | Objetivo | Estado |
|---|---|---|
| **Fase 1 — Demostrar alivio** | Usuario que evitaba mirar sus finanzas siente claridad en una semana. Deploy estable, JWT, cierre de P0, migración Python. | En ejecución |
| **Fase 2 — Consolidar hábito** | Uso útil → recomendación entre pares. Más bancos. Fintoc + APIs directas. | Planificado |
| **Fase 3 — Capa institucional** | Con masa crítica, ARIA genera valor para bancos, gobierno, aseguradoras. B2B. | Planificado |
| **Fase 4 — Infraestructura** | Sky como plataforma. DataSource como API pública. | Futuro |
| **Fase 5 — Categoría regional** | Expansión a Perú, México, Colombia. | Futuro |

---

## Repositorios del ecosistema

| Repositorio | Rol |
|---|---|
| `github.com/TioCristian007/SkyFinance` | Este repo — monorepo principal (backend Node + backend Python + frontend) |
| `github.com/TioCristian007/SkyFinancWebSite` | Landing pública — HTML estático, GitHub Pages, skyfinanzas.com |
| `SupabaseSQLQuerys/` | Migraciones SQL del schema public y aria, aplicadas en Supabase |

---

*Sky Finanzas · v5 · Chile · Abril 2026 · Registro INAPI*
