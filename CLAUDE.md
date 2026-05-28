# CLAUDE.md — Sky Finance

> Contexto persistente para sesiones de Claude Code. Léelo antes de tocar nada.
> Mantén este archivo conciso. La fuente de verdad detallada vive en otro lado (ver abajo).

---

## 📜 Fuentes de verdad (jerarquía)

Sky tiene **dos** fuentes de verdad complementarias. Entiéndelas antes de actuar:

1. **`Estados del Arte/SkyFinanzas_EstadoDelArte_v5_Documentado.pdf`** — fuente **doctrinal y legal**, registrada ante INAPI (propiedad intelectual, Chile). Manda en doctrina, visión y titularidad.
   - ⚠️ **Importante**: el v5 fue registrado cuando la migración Python era *futuro (Parte II)*. **A mayo 2026 esa migración está completa y en producción.** La Parte II del v5 describe el objetivo de entonces, no el estado actual. Cuando se reactualice el registro INAPI, la Parte II se reescribirá como estado vigente.

2. **`docs/ESTADO_DEL_ARTE.md`** (+ `docs/estado-del-arte/01..09`) — reflejo **técnico vigente y verificado**. Es el punto de entrada operativo y se mantiene al día continuamente. Léelo al inicio de cada sesión nueva.

**Reglas de precedencia**:
- En **doctrina/visión/legal** → gana el v5 PDF.
- En **estado técnico actual** (qué corre hoy, qué está roto, deuda viva) → gana `docs/ESTADO_DEL_ARTE.md`.
- Este `CLAUDE.md` es un **derivado conciso de ambos** para arrancar cada sesión rápido. Si contradice a cualquiera de los dos, este archivo está mal y se corrige.

**Disciplina de mantenimiento (no negociable)**: cuando algo de fondo cambie, el orden es **v5 PDF (si toca doctrina/legal) → `docs/ESTADO_DEL_ARTE.md` → este `CLAUDE.md`**. Esta pieza nunca debe quedarse atrás del Estado del Arte.

**Cofundadores y titularidad** — SkyFinanzas SpA (RUT 78.395.382-K):
- Cristian Cristóbal Amaru Vásquez Guevara · 22.141.522-1
- Juan José Latorre Pérez · 22.003.365-1

---

## 🎯 Qué es Sky (no perder esto de vista)

Sky NO es una app de gastos con IA. Es un **sistema operativo financiero personal**: capa cognitiva entre la persona y su vida financiera, que absorbe complejidad y devuelve **claridad**.

- **Promesa central**: alivio emocional. La landing dice "Respira. Tus finanzas están en las mejores manos". La promesa es respiratoria antes que cognitiva.
- **Tesis**: la gente no falla por falta de conocimiento, sino por ansiedad/evasión/fricción. La tecnología debe absorber complejidad, no exigir expertise.
- **Tres pilares**: automatización bancaria · interpretación inteligente (Mr. Money) · diseño conductual (metas, desafíos, simulaciones).
- **Mr. Money guía; no decide.** Toda propuesta estructurada (`propose_challenge`, etc.) requiere confirmación explícita del usuario antes de ejecutarse. NO da asesoría de inversión específica, NO recomienda activos puntuales, NO actúa como asesor licenciado, NO garantiza resultados.
- **Marca**: Sky / Sky Finanzas. Personaje IA = Mr. Money. Paleta verde `#00C853`, navy `#0D1B2A`, blanco `#FFFFFF`. Tipografías Instrument Serif + Geist + Geist Mono.

---

## ⚖️ Doctrina inviolable (23 reglas)

Detalle completo y firmado: **`docs/estado-del-arte/09_DOCTRINA.md`** (deriva del v5 §26 + §13.2 + §14.4 + §15.4 + Parte III §20). Sobrescriben conveniencia de corto plazo. No se negocian durante construcción; un cambio que contradice una de ellas se rechaza en review sin negociar.

**Producto**: (1) el producto debe sentirse ligero · (2) Mr. Money guía, no decide · (3) la confianza vale más que cualquier monetización rápida · (4) el frontend NO es la fuente de verdad · (5) los datos del usuario existen primero para servir al usuario.

**Arquitectura**: (6) desacopla proveedor / negocio / analytics · (7) el dominio jamás pregunta de qué `source` vino un movimiento (si necesita distinguir origen, el modelo canónico está incompleto — se enriquece, no se rompe) · (8) modelo canónico único `CanonicalMovement` · (9) tolera pivotes estratégicos, ningún proveedor es inamovible · (10) **la API Python NUNCA importa Playwright**; solo el worker tiene browser pool; API y worker son procesos deployables independientes.

**Ingestión/resiliencia**: (11) scraper como fallback permanente · (12) `AuthenticationError` NO dispara failover · (13) rate limit = `skip`, no `fail` · (14) configuración como palanca operativa (cambios de estrategia son `UPDATE` a `ingestion_routing_rules`, no deploys).

**Seguridad**: (15) `SUPABASE_SERVICE_KEY` y `BANK_ENCRYPTION_KEY` solo en backend · (16) credenciales = AES-256-GCM con IV único (`iv:authTag:ciphertext`, compat binaria Node↔Python) · (17) IA solo desde el backend · (18) RLS en TODAS las tablas `public`; `aria` solo service_role · (19) frontend nunca llama a Supabase con `service_role` ni a Anthropic directo · (20) errores de scraper sanitizados antes de mostrarse.

**Privacidad**: (21) ARIA solo con `aria_consent = true`; sin UUID en `aria.*`.

**Operación**: (22) la deuda técnica se documenta, no se oculta · (23) la ambición se merece con ejecución disciplinada (gate de verificación por cambio).

---

## 🏗️ Stack y arquitectura

Monorepo. Estado **mayo 2026**: migración Python **completa y en producción**. Node archivado.

| Carpeta | Rol | Estado |
|---|---|---|
| `backend-python/` | Python 3.12 + FastAPI + ARQ + Playwright | ✅ **Producción** — sirve usuarios reales · **FOCO ACTIVO** |
| `frontend/` | React 18.3 + Vite 5.4. Solo consume el backend. | ✅ **Producción** |
| `backend/` | Node.js + Express — backend legacy | 🗄️ Archivado post-cutover (solo referencia). **No tocar.** |

**DB compartida**: Supabase Postgres 15. Esquemas `public` (RLS en todo) y `aria` (analytics, sin UUID, service_role only).

**Despliegue**: Railway (proyecto SkyFinanzas) · `app.skyfinanzas.com` (frontend) + `api.skyfinanzas.com` (API Python) · DNS en registrador (CNAME → Railway) · landing `skyfinanzas.com` en GitHub Pages.

**IA**: Anthropic Claude — **Sonnet 4.6** (Mr. Money) y **Haiku 4.5** (categorización capa 3). Solo desde el backend.

**Procesos deployables (separación dura)**: la API nunca importa Playwright; solo el **worker** arranca el browser pool. Comparten Postgres y Redis. Servicios Railway: `sky-api-python`, `sky-worker-python`, `sky-cron-sync`, `Redis`, `SkyFinance` (frontend). ⚠️ Deuda B-6: `appealing-benevolence` (Node legacy) sigue online y duplicando datos — apagar urgente.

### Regla de oro
```
Frontend  → solo muestra, captura y llama al backend
Backend   → calcula, decide, guarda, llama a la IA
IA        → solo desde el backend, nunca desde el browser
ARIA      → solo escribe analytics anónimos
Cifrado   → solo el backend conoce BANK_ENCRYPTION_KEY
```

Detalle de arquitectura (middleware stack, routers, sync bancario, diagrama): **`docs/estado-del-arte/04_ARQUITECTURA.md`**.

---

## 🗺️ Mapa del repo

```
sky_OFFICIAL/
├── backend-python/              ← Python PRODUCCIÓN ← FOCO ACTIVO
│   ├── src/sky/
│   │   ├── core/                ← config, db, encryption, locks, logging, errors, metrics, audit
│   │   ├── ingestion/           ← router + scrapers + rate limit + circuit breaker + rules DB
│   │   │   ├── routing/         ← router.py, rules.py
│   │   │   ├── sources/         ← bchile_scraper (validado), bci_direct (roto), __init__ (SUPPORTED_BANKS)
│   │   │   └── parsers/         ← bchile_parser
│   │   ├── api/                 ← FastAPI: main + jwt_auth + routers/* + schemas/* (implementados)
│   │   ├── worker/              ← ARQ: main + jobs/* + banking_sync (implementados)
│   │   └── domain/              ← Mr. Money, ARIA, finance, categorizer (implementados)
│   ├── tests/                   ← 386 tests (unit verde + integration + parity)
│   ├── scripts/                 ← smoke_router, test_*_scraper, verify_encryption_compat, rekey_*, audit_rls_policies
│   ├── migrations/              ← SQL versionadas
│   ├── docs/                    ← referencia operativa durable + archive/ (histórico de las 13 fases)
│   │   ├── API_CONTRACT.md · SECURITY.md · DECISION_SECRETS_MANAGER.md
│   │   ├── DR_RUNBOOK.md · RUNBOOK_KEY_ROTATION.md · REMEDIATION_P0_P3.md
│   │   └── archive/            ← planes de cierre de fases, sprints, auditorías (histórico, doctrina §22)
│   └── README.md
├── frontend/                    ← React app (producción)
│   └── src/  Sky.jsx (god-component ~1.600 LOC, deuda P1-1) · services/api.js · components/BankConnect.jsx
├── backend/                     ← Node.js LEGACY archivado (no tocar)
├── docs/                        ← 📍 ESTADO DEL ARTE (punto de entrada técnico)
│   ├── ESTADO_DEL_ARTE.md       ← índice integral + TL;DR
│   ├── estado-del-arte/01..09   ← empresa, producto, ecosistema, arquitectura, infra, config, seguridad, deuda, doctrina
│   └── SECURITY_INFRASTRUCTURE.md
└── CLAUDE.md                    ← este archivo
```

**Fuera del monorepo**: `SkyFinancWebSite/` (landing, repo separado, GitHub Pages) · `SupabaseSQLQuerys/` (migraciones SQL versionadas, repo separado).

---

## 📐 Contrato `DataSource` (la pieza más protegida)

Vive en `backend-python/src/sky/ingestion/contracts.py`. Modificarlo requiere RFC interno. Detalle: **`docs/estado-del-arte/03_ECOSISTEMA.md`**.

### `kind` (5) · `auth_mode` (4)
- **kind**: `SCRAPER` · `AGGREGATOR` · `BANK_API_DIRECT` · `SFA` · `MANUAL_UPLOAD`
- **auth_mode**: `PASSWORD` · `OAUTH` · `API_KEY` · `CONSENT_TOKEN`

### Bancos soportados (`SUPPORTED_BANKS`)
| Identifier | Capa · Auth | Estado |
|---|---|---|
| `bchile` | SCRAPER · PASSWORD | **active** — validado funcionando desde IP residencial. ⚠️ Bloqueado por anti-bot (Incapsula) desde datacenter Railway. 2FA app. |
| `bci` | SCRAPER · PASSWORD | **pending** — scraper roto: BCI cambió el dominio del portal (`portalpersonas.bci.cl` ya no resuelve). Requiere rework. |
| `falabella` | SCRAPER · PASSWORD | removido del listado (skeleton, no operativo) |
| `mercadopago`, `fintoc`, `*.direct`, `sfa.*`, `manual` | varios | 🔴 Futuro |

> El frontend solo expone como conectables BChile y BCI; los `pending` aparecen como "Próximamente".

### `CanonicalMovement`
`external_id` (SHA-256 determinístico) · `amount_clp` (int CLP; **positivo = ingreso, negativo = gasto**) · `raw_description` · `occurred_at` (date) · `movement_source` (CUENTA / TARJETA / LÍNEA) · `source_kind` · `source_metadata` (libre, debug — el dominio NO lo lee).

```python
external_id = f"{bank_id}_{sha256(f'{date}|{amount}|{desc.lower()}').hexdigest()[:16]}"
```
Mismo movimiento real → mismo id → idempotencia natural en `INSERT ... ON CONFLICT`. Consecuencia: migrar un banco de scraping a SFA **no duplica histórico**.

---

## 🔁 IngestionRouter — failover, circuit breaker, rate limit

- **Cadena de proveedores por banco**: lista ordenada en `public.ingestion_routing_rules`. Editable sin redeploy.
- **Rollout %**: hash determinístico de `user_id + bank_id` para canary releases.
- **Circuit breaker en Redis** (`cb:<source_id>`): abre tras **5 fallos en 60s**, mantiene **120s**, cierra tras **3 éxitos consecutivos** en half-open.
- **Rate limit en Redis** (`rl:<source_id>`): sliding window log atómico (Lua), namespace separado del CB.
- **Política de failover**: circuit OPEN → salta al siguiente · `RecoverableIngestionError` → siguiente · `AuthenticationError` → propaga sin failover · rate limit → skip · toda la cadena falla → `AllSourcesFailedError`.

---

## 🧠 Mr. Money — arquitectura de respuesta

1. **Detección local primero** — patrones (saludos, consultas de desafíos) responden **sin tokens** (~60-70% de consultas).
2. Si no hay match local → construye contexto financiero (balance, ingresos/gastos por categoría, tasa de ahorro, metas, desafíos, cuentas) → eleva a `claude-sonnet-4-6`.
3. Tipos de respuesta: texto simple · `propose_challenge` (estructurada, render interactivo, **requiere confirmación**) · navegación (deep-link a vistas).
4. Tool use de Anthropic para proyecciones financieras y evaluar realismo de metas.

Config: `mr_money_max_tokens=4096`, `temperature=0.7`, prompt caching 5m.

---

## 🧮 Categorización 3 capas

Orden estricto, cada capa solo invoca la siguiente si falla:
1. **Reglas deterministas** — ~25 regex. Sin tokens.
2. **Caché de comercios** — tabla `merchant_categories`, lookup por prefijo progresivo (`"jumbo las condes" → "jumbo las" → "jumbo"`). Compartida entre usuarios.
3. **Claude API** (`claude-haiku-4-5`) — solo si las dos capas anteriores fallan. Resultado se guarda en caché.

Las tx se insertan con `categorization_status='pending'` y descripción `'Procesando...'`; el job ARQ `categorize_pending_job` las procesa async. **Display ingreso/gasto en frontend = por signo del monto (`tx.amount > 0`), NO por categoría.**

---

## 🛡️ ARIA — pipeline de anonimización

Solo activo si `profiles.aria_consent = true`. 5 pasos: (1) extracción evento→señal · (2) categorización valor→rango · (3) eliminación de UUID antes de escribir · (4) randomización intra-bucket · (5) ruptura de correlaciones (jitter ±36h, batch_id propio). Vistas con **k-anonymity ≥ 10**. Tablas `aria.*`: `spending_patterns`, `goal_signals`, `behavioral_signals`, `session_insights`.

---

## 📋 Deuda viva (mayo 2026)

Fuente: **`docs/estado-del-arte/08_ESTADO_Y_DEUDA.md`** + `backend-python/docs/REMEDIATION_P0_P3.md`. Las 13 fases técnicas están **cerradas**; P0 y BUG-1..4 cerrados por el cutover.

### Bloqueadores activos
| ID | Item | Nota |
|---|---|---|
| **B-1** | Scraping bloqueado desde datacenter (anti-bot Incapsula en BChile) | Funciona desde IP residencial, no desde Railway. Stealth básico agregado (2026-05-25): `--disable-blink-features=AutomationControlled`, UA realista, `navigator.webdriver=undefined`, palancas `browser_headless`/`scraper_debug_capture`. No garantizado vs Incapsula sofisticado. Crítico arquitectónico → refuerza tesis SFA. |
| **B-2** | Scraper BCI roto — dominio cambiado | `portalpersonas.bci.cl` ya no resuelve. Requiere rework (sprint propio). |
| ✅ **B-3** | ~~Audit log roto en runtime~~ — **cerrado 2026-05-25** | `:detail::jsonb` rompía asyncpg con named params → 0 filas escritas. Corregido: `CAST(:detail AS jsonb)`. Test de regresión en `test_audit.py`. Pendiente: verificar runtime con Postgres staging (10 min). + vocabulario de event_type/outcome en `audit.py` reconciliado con la DB (cerrado 2026-05-27). |
| ✅ **B-4** | ~~Balance post-disconnect~~ — **cerrado 2026-05-27** | cerrado 2026-05-27: summary filtra deleted_at + balance nunca cae a net_flow; KPI muestra '—' sin banco. |
| **B-5** | Lentitud general | Sin profiling. **Medir antes de optimizar.** |
| **B-6** | Backend Node legacy `appealing-benevolence` (Railway) online y duplicando datos en la Supabase compartida | Cada sync inserta movimientos con `external_id` en formato distinto al Python (`bchile_<6-base36>` vs `bchile_<16-hex>`) → la unique index no detecta colisión → duplicación garantizada. **APAGAR antes de cualquier limpieza adicional.** Detectado 2026-05-27. |

### Deuda abierta / infra
- **P1-1**: `Sky.jsx` god-component (~1.600 LOC) — refactor frontend.
- Limpiar `api-v2.skyfinanzas.com` (502, leftover canary) · warm standby Fly.io (DR Railway).

### Prioridades sugeridas
1. **Apagar `appealing-benevolence` en Railway** (B-6, urgente; corta la duplicación de datos en prod). · 2. **Prep pitch BCI** (2026-05-28). · 3. **B-2** rework BCI scraper. · 4. **B-1** anti-bot Incapsula. · 5. **B-5** performance (medir antes de optimizar). · 6. Sync de `docs/estado-del-arte/08` con saga Tanda 1-4.

---

## 🐍 Convenciones Python (backend-python/)

- `from __future__ import annotations` siempre.
- `StrEnum` (3.11+) en vez de `(str, Enum)`.
- Async-first: SQLAlchemy 2.0 async, `redis.asyncio`, FastAPI native async, ARQ, `httpx` async.
- `structlog` con context binding. Nunca `print`.
- Excepciones tipadas en `sky.core.errors`. NO crear duplicados.
- `pydantic-settings` (`Settings`) para config; fail-fast si falta env var crítica.
- `dataclass(frozen=True, slots=True)` para value objects inmutables.
- Sin `# type: ignore` salvo cuando mypy genuinamente no infiere.

### Tests
- `pytest` con `asyncio_mode=auto`. Sin `@pytest.mark.asyncio` por test.
- `fakeredis[lua]>=2.26` para Redis. Fixture `fake_redis` en `conftest.py`.
- `@pytest.fixture(autouse=True)` para resetear estado global.
- Nunca `time.sleep` en tests async — usa `await asyncio.sleep`. Timing del circuit breaker: `≥ 1.0s`.
- Dummies de Supabase en `conftest.py` con `os.environ.setdefault(...)` ANTES de cualquier import de `sky.*`.

### Naming Redis
- `rl:<source_id>` rate limit · `cb:<source_id>` circuit breaker · namespaces separados.

### Cola ARQ
- Cola única **`sky:default`**. API y worker crean sus pools con `default_queue_name="sky:default"`. Jobs sin nombre de cola caen en `arq:queue` (fantasma) y no corren — bug histórico ya corregido.

### Mensajes de commit
- Convencional pero en **español**. Siempre `Co-Authored-By: Claude ...`.

---

## ⚙️ Comandos comunes (PowerShell, Windows)

```powershell
cd backend-python; .venv\Scripts\activate
pip install -e ".[dev]"            # setup (una vez) + playwright install chromium

# loop dev
pytest tests/unit/ -v --cov=src/sky --cov-report=term-missing
ruff check src/sky/ ; mypy src/sky/

# levantar stack
$env:REDIS_URL = "redis://127.0.0.1:6379"   # en Windows usar 127.0.0.1, NO localhost
uvicorn sky.api.main:app --reload --port 8000
arq sky.worker.main.WorkerSettings

# smoke contra Redis real
docker run -d --rm -p 6379:6379 --name sky-redis-smoke redis:7-alpine
python scripts/smoke_router.py ; docker stop sky-redis-smoke

# antes de migración SQL (gate de RLS)
python scripts/audit_rls_policies.py        # exit 1 bloquea deploy
```

- PowerShell: `$env:VAR = "valor"` (NO `VAR=valor cmd`). Encadenar con `;` o `if ($?) { ... }` (NO `&&`). Heredoc: `@'...'@` (cierre `'@` en columna 0).

---

## ✅ Gates de calidad (por cambio)

No hay "cierre de fase" (las 13 fases ya cerraron; sus planes viven en `backend-python/docs/archive/`). Para cualquier cambio de código, todos deben dar exit 0 antes del commit:

1. `ruff check src/sky/ tests/`
2. `mypy src/sky/`
3. `pytest tests/ -v` (386 tests; cobertura en el módulo tocado)
4. Smoke contra Redis local si tocas ingestión/routing.
5. `uvicorn` arranca + `/api/health` responde 200 si tocas la API.
6. Si hay migración SQL: `audit_rls_policies.py` verde + aplicar en staging antes que prod.

### Hook automático de pre-push (R-6, 2026-05-23)

Los gates se corren automáticamente antes de cada `git push` vía `.githooks/pre-push`.

**Activación (one-time por clon):**
```powershell
git config core.hooksPath .githooks
```

**Correr los gates manualmente (PowerShell, desde `backend-python/` con venv activo):**
```powershell
.\scripts\check_gates.ps1
```

**Saltar el gate en emergencia** (bajo tu responsabilidad):
```sh
SKY_SKIP_GATE=1 git push
```

---

## 🤝 Reglas de operación con Claude

- **Lee `docs/ESTADO_DEL_ARTE.md` al inicio de cada sesión nueva.** Es el estado vigente.
- **Mantén `CLAUDE.md` sincronizado.** Si un cambio deja este archivo o el Estado del Arte desactualizados, actualízalos (orden: v5 PDF si es doctrina/legal → `docs/ESTADO_DEL_ARTE.md` → `CLAUDE.md`). Esta pieza no se queda atrás.
- **Trabajamos directo en `main`** (decisión 2026-04-30). Sin worktrees, sin PRs en flujo normal. `.claude/` está en `.gitignore`.
- **El usuario hace `git push`.** Yo solo commit local.
- **Nunca `--force` push a main.** Si parece necesario, algo está mal — diagnosticar antes.
- **Ante ambigüedad o conflicto**: parar y preguntar antes de tocar archivos. No tomar acciones destructivas (`reset --hard`, merge, force) sin OK explícito.
- **Si encuentro deuda fuera de scope**: documentarla en `docs/estado-del-arte/08_ESTADO_Y_DEUDA.md` (o como TODO), no arreglarla en el momento.
- **No tocar `backend/` (Node).** Está archivado; solo referencia histórica.
- **Producción es real.** `backend-python/` y `frontend/` sirven usuarios. Cambios con cuidado quirúrgico; respetar la doctrina §09.
- **PowerShell por defecto** — Windows + miniconda.

---

## 🎯 Visión estratégica (5 fases de negocio)

No confundir con las 13 fases técnicas (ya cerradas).

| Fase | Objetivo |
|---|---|
| **F1 — Demostrar alivio** ← **etapa actual** | Que un usuario sienta más claridad en una semana. Objetivo inmediato: **pitch a BCI**. |
| **F2 — Consolidar hábito** | Recomendación entre pares. Más bancos. Fintoc + APIs directas. Entrada universitaria. |
| **F3 — Capa institucional** | ARIA genera valor B2B (bancos, gobierno, aseguradoras). |
| **F4 — Infraestructura** | Sky como plataforma. Contrato `DataSource` como API pública. |
| **F5 — Categoría regional** | Expansión Perú, México, Colombia. |

**Dirección estratégica de fondo**: migrar de scraping a **SFA (Open Banking CMF)** cuando los bancos liberen APIs; el scraper queda como fallback permanente. La fragilidad del scraping (anti-bot, cambios de portal) es el argumento técnico honesto para el SFA.

---

## 🔖 Atajos de contexto frecuentes

| Pregunta | Dónde mirar |
|---|---|
| "Estado vigente / TL;DR" | `docs/ESTADO_DEL_ARTE.md` |
| "Qué es Sky / empresa / visión" | `docs/estado-del-arte/01_EMPRESA.md` · `02_PRODUCTO.md` |
| "Bancos, DataSource, modelo canónico, SFA" | `docs/estado-del-arte/03_ECOSISTEMA.md` |
| "Arquitectura (middleware, routers, sync, diagrama)" | `docs/estado-del-arte/04_ARQUITECTURA.md` |
| "Infra (Railway, Supabase, DNS, DR)" | `docs/estado-del-arte/05_INFRAESTRUCTURA.md` |
| "Variables de entorno / config / despliegue / CI" | `docs/estado-del-arte/06_CONFIGURACION.md` |
| "Seguridad (cifrado, RLS, ARIA, audit, runbooks)" | `docs/estado-del-arte/07_SEGURIDAD.md` |
| "Qué funciona / qué no / deuda viva" | `docs/estado-del-arte/08_ESTADO_Y_DEUDA.md` |
| "Doctrina completa (23 reglas)" | `docs/estado-del-arte/09_DOCTRINA.md` |
| "Doctrina legal / titularidad / profundidad" | v5 PDF (registro INAPI) |
| "Contrato de API REST" | `backend-python/docs/API_CONTRACT.md` |
| "Runbooks (DR, rotación de clave)" | `backend-python/docs/DR_RUNBOOK.md` · `RUNBOOK_KEY_ROTATION.md` |
| "Cómo se construyó (histórico de fases)" | `backend-python/docs/archive/` |

---

## 📅 Última actualización

`2026-05-27` · Saga de números: idempotencia con id nativo BChile + fallback con saldo, ventana mes calendario, audit_log vocabulario reconciliado, tzdata pinneado, toggles simétricos transfer→ingreso/gasto (default ON, principio contable), cleanup + categorize self-drain. Detectado y documentado el double-write de Node legacy (B-6). Migraciones aplicadas: 006 (`bank_accounts.status`), 007 (`count_transfers_as_income`), 008 (`count_transfers_as_expense`). Lint E501 pendiente en `tests/unit/test_finance.py:216-217`.

`2026-05-23` · Reescrito para reflejar que la **migración Python está completa y en producción** (las 13 fases cerradas, Node archivado). Alineado con `docs/ESTADO_DEL_ARTE.md`. El v5 PDF sigue siendo la fuente doctrinal/legal; su Parte II quedará reescrita cuando se reactualice el registro INAPI.
