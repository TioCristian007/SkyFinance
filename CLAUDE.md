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

**Procesos deployables (separación dura)**: la API nunca importa Playwright; solo el **worker** arranca el browser pool. Comparten Postgres y Redis. Servicios Railway: `sky-api-python`, `sky-worker-python`, `sky-cron-sync`, `Redis`, `SkyFinance` (frontend). ✅ B-6: `appealing-benevolence` (Node legacy) **apagado (Offline) 2026-06-13** vía `railway down` (repo GitHub ya desconectado; sin double-write — 184/184 external_id en formato Python). Pendiente menor: Delete Service definitivo en el dashboard.

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
│   │   │   ├── sources/         ← bchile_scraper (validado), bci_scraper (rework construido, pending prod), __init__ (SUPPORTED_BANKS)
│   │   │   └── parsers/         ← bchile_parser
│   │   ├── api/                 ← FastAPI: main + jwt_auth + routers/* + schemas/* (implementados)
│   │   ├── worker/              ← ARQ: main + jobs/* + banking_sync (implementados)
│   │   └── domain/              ← Mr. Money, ARIA, finance, categorizer (implementados)
│   ├── tests/                   ← 598 tests (unit verde + integration + parity)
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
| `bchile` | SCRAPER · PASSWORD | **active** — ✅ validado **en producción** (2026-06-12: sync real desde Railway, 42 movs, channel=chrome). 2FA app. RUT se llena con `type()` (directiva Angular), clave con `fill()` — NO cambiar (tests lo pinean). |
| `bci` | SCRAPER · PASSWORD | **pending** — rework + tests #1-#4 (2026-06-13, `bci_scraper.py`): portal `www.bci.cl` (widget) + app JSF + BFF v3.2. **Login OK** end-to-end + **JWT capturado** (test #3: el esquema es `bearer` minúscula, match case-insensitive; lo dispara la navegación a Saldos/Movimientos, no la home; el token va en el header, no en storage). Bodies reales: `por-rut {"rut":"<rut>-<dv>"}`, saldo `{"cuentaNumero":"<n>"}`, movs `{"numeroCuenta":"<n>"}` (keys distintas, sin `tipo`). RUT `type()` en `#rut_aux`, clave `fill()` en `#clave`. 2FA Digital Pass. **Test #4 — la API falla por CORS** (`Failed to fetch`): `_api_post` usaba `credentials:"include"` (modo CORS-con-credenciales) pero apilocal autentica por Bearer, no cookies → fix: `credentials:"omit"` + `bearer` minúscula (espeja el frontend) + instrumentación `bci_request_headers` (gated, PII-safe). Pendiente: **test #5** (debería listar cuentas+movs+saldo end-to-end) → sync real prod (vigilar DetectCA easysol, tipo B-1) → activar `bci`. |
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

## 🧮 Categorización — 5 niveles (aprende del usuario)

Orden estricto, cada nivel solo se consulta si el anterior no resolvió (sprint 2026-06-12 tercera tanda; antes eran solo los niveles 2-4):
0. **Votos propios** (`merchant_category_votes`, prefix matching per-user) — el usuario recategorizó ese comercio: override privado inmediato. Lo escribe `merchant_feedback.record_user_categorization` desde el PATCH de transacciones.
1. **Caché global `source='user'`** — consenso crowdsourced (≥ `merchant_vote_promotion_threshold` usuarios distintos, default 3; converge a la mayoría). Corrige una regla equivocada para todos. La guarda de `upsert_merchant_category` (migración 014) impide que la IA pise estas filas.
2. **Reglas deterministas** — ~25 regex. Sin tokens.
3. **Caché de comercios** `source 'rule'/'ai'` — lookup por prefijo progresivo (`"jumbo las condes" → "jumbo las" → "jumbo"`). Compartida entre usuarios. Va BAJO las reglas — solo el tier `'user'` las supera; no cambiar sin leer el sprint doc.
4. **Claude API** (`claude-haiku-4-5`) — solo si todo lo anterior falla. Resultado se guarda en caché.

**Frontera de privacidad / identidad (doctrina §5/§21)**: una key se promueve al global SOLO si identifica confiablemente UN comercio. Quedan fuera (`crowdsource_eligible=false`, override privado solamente, fuera de logs): (1) transferencias y contrapartes personales (`TRANSFER_PREFIX_RE` o categoría `transfer`); (2) **etiquetas de pasarela/terminal de pago** (`mercadopago`, `paypal`, `sumup`, `khipu`, `webpay`, `transbank` — match por primera palabra de la key, `GATEWAY_LABEL_FIRST_WORDS`): la misma etiqueta es comercios distintos para gente distinta. La decisión vive en `merchant_feedback.is_crowdsource_eligible` (función única, reusada por votos Y aliases). El fix profundo (¿una key = un comercio o varios?) es la Fase 3 (identidad canónica).

**Renombre de comercio (Fase 2)**: `PATCH /api/transactions/{id}/merchant` registra un alias per-user (`merchant_aliases`, migración 015) que aplica YA a todas las tx del comercio; con quórum de N usuarios se promueve a `merchant_display_names` (nombre canónico global). El display se resuelve al leer (`categorizer.merchant_display_batch`): alias propio → alias global → Title Case. Misma frontera de privacidad/identidad que los votos. La tx NO se muta — el cliente nunca manda la `merchant_key`, se deriva de la tx del usuario.

Las tx se insertan con `categorization_status='pending'` y descripción `'Procesando...'`; el job ARQ `categorize_pending_job` las procesa async (propaga `user_id` para el nivel 0). **Display ingreso/gasto en frontend = por signo del monto (`tx.amount > 0`), NO por categoría.**

---

## 🛡️ ARIA — pipeline de anonimización

Solo activo si `profiles.aria_consent = true`. 5 pasos: (1) extracción evento→señal · (2) categorización valor→rango · (3) eliminación de UUID antes de escribir · (4) randomización intra-bucket · (5) ruptura de correlaciones (jitter ±36h, batch_id propio). Vistas con **k-anonymity ≥ 10**. Tablas `aria.*`: `spending_patterns`, `goal_signals`, `behavioral_signals`, `session_insights`.

---

## 📋 Deuda viva (mayo 2026)

Fuente: **`docs/estado-del-arte/08_ESTADO_Y_DEUDA.md`** + `backend-python/docs/REMEDIATION_P0_P3.md`. Las 13 fases técnicas están **cerradas**; P0 y BUG-1..4 cerrados por el cutover.

### Bloqueadores activos
| ID | Item | Nota |
|---|---|---|
| ✅ **B-1** | ~~Scraping bloqueado desde datacenter (anti-bot Incapsula)~~ — **obsoleto, cerrado 2026-06-12** | Con la migración a Auth0 el bloqueo de datacenter dejó de aplicar: el scraper llena y envía el form desde Railway sin challenge. Confirmado con sync real en prod. La fragilidad del scraping sigue reforzando la tesis SFA. |
| **B-2** | Scraper BCI — login OK, JWT arreglado (test #3), falta sync real | Portal `www.bci.cl` (widget) + app JSF + BFF v3.2; `bci_scraper.py` reconstruido y gated. **R-2 cerrado** (`BCIScraperSource`, `scraper.bci` intacto). **Login OK end-to-end** + bodies confirmados (test #1). **Test #3 (2026-06-13): ROOT CAUSE del JWT encontrado y arreglado** — la instrumentación (censo de red) mostró que `apilocal.bci.cl` se llama con `auth_scheme='bearer'` (minúscula) pero `_is_jwt_request` matcheaba `"Bearer "` case-sensitive → el token estaba en cada request y se descartaba. Fix quirúrgico: match case-insensitive (`auth[:7].lower()=="bearer "`). Confirmado además: el JWT lo dispara la **navegación** a Saldos/Movimientos (no la home), y NO vive en storage (sondas `looks_like_jwt:False`) — va en el header. Falta: **test #4** (debería listar cuentas+movs+saldo end-to-end) → **sync real en prod** → activar `bci`. Riesgo: DetectCA easysol (tipo B-1, no apareció en local). |
| ✅ **B-3** | ~~Audit log roto en runtime~~ — **cerrado 2026-05-25** | `:detail::jsonb` rompía asyncpg con named params → 0 filas escritas. Corregido: `CAST(:detail AS jsonb)`. Test de regresión en `test_audit.py`. Pendiente: verificar runtime con Postgres staging (10 min). + vocabulario de event_type/outcome en `audit.py` reconciliado con la DB (cerrado 2026-05-27). |
| ✅ **B-4** | ~~Balance post-disconnect~~ — **cerrado 2026-05-27** | cerrado 2026-05-27: summary filtra deleted_at + balance nunca cae a net_flow; KPI muestra '—' sin banco. |
| **B-5** | Lentitud general | Sin profiling. **Medir antes de optimizar.** |
| ✅ **B-6** | ~~Backend Node legacy `appealing-benevolence` online~~ — **cerrado 2026-06-12** | Servicio apagado en Railway (D1). No alcanzó a duplicar datos (184/184 external_id en formato Python). |
| ✅ **B-7** | ~~Falso positivo URL BChile post-migración Auth0~~ — **cerrado, verificado en prod 2026-06-12** | BChile migró el form de login a `login.portales.bancochile.cl/login` (Auth0 + Angular), manteniendo los IDs DOM. El check `if "/login" in page.url` matcheaba el nombre literal del nuevo dominio → todos los syncs caían en `AuthenticationError` → mensaje "Credenciales rechazadas por el banco" para todos los usuarios/testers. Fix: check `"/login" in url` reemplazado por poll positivo 20s esperando que la URL salga de `login.portales.bancochile.cl` (commit 6fdae84). La saga fill/type quedó resuelta y pineada por tests en el sprint 2026-06-12: **RUT = `type()`** (directiva Angular `delete-zero-left` requiere keystrokes) · **clave = `fill()`** (`type()` manglaba el `$` en Chromium bundled headless — esa era la causa raíz del último bloqueador). Verificación post-fill (`FieldFillError`) como red permanente. Verificado en prod: 42 movs, channel=chrome, categorización OK. |

### Deuda abierta / infra
- **P1-1**: `Sky.jsx` god-component (~1.600 LOC) — refactor frontend.
- Limpiar `api-v2.skyfinanzas.com` (502, leftover canary) · warm standby Fly.io (DR Railway).

### Ciclo de credenciales (sprint 2026-06-12 — Fase B)
Clave rechazada de verdad por el banco → status **`needs_reconnection`** (migración 013): hard-stop en TODOS los caminos (cron ARQ, sync-all, cron HTTP, endpoint manual → 409, backstop en el worker) hasta que el usuario reconecte — el upsert de reconexión resetea status/errores (pineado por test). Protege contra el bloqueo del banco al 3er fallo. Frontend: "Actualizar" deshabilitado + "Reconectar" primario. Taxonomía de fallos `SyncFailureKind` en `contracts.py` (mensajes/acciones en un solo lugar, `failure_kind` en audit). Panel operador: `GET /api/internal/operator/sync-status` (x-cron-secret) con `by_status`.

### Categorización que aprende — Fase 1 ✅ + Bloque 0 + Fase 2 (sprint 2026-06-12/13)
- **Fase 1 VERIFICADA EN PROD** (migración 014 aplicada): votos OK, frontera de privacidad OK, anti-envenenamiento OK. Invariantes pineados por tests: la IA jamás pisa un voto `user` · transferencias/contrapartes personales jamás se promueven al global · promoción solo con quórum de usuarios distintos · un voto no se filtra a otro usuario.
- **Bloque 0 (endurecer elegibilidad)**: `merchant_key` NO es identidad de comercio, es etiqueta de pago. `is_crowdsource_eligible` (función única, reusada por votos Y aliases) excluye del global las etiquetas de pasarela/terminal (`GATEWAY_LABEL_FIRST_WORDS`: mercadopago, paypal, sumup, khipu, webpay, transbank — match por primera palabra). Lista corta deliberada (mejor sub-excluir; el quórum es el backstop). `_key_is_promotable` re-chequea al promover (cubre votos viejos sin backfill). Override per-user intacto para lo excluido.
- **Fase 2 (renombre + nombre canónico)** ✅ VERIFICADA EN PROD (migración 015 aplicada 2026-06-13): `merchant_aliases` (per-user) + `merchant_display_names` (consenso global). Endpoint `PATCH …/{id}/merchant`, display resuelto al leer (`merchant_display_batch`: propio → global → Title Case), UI con lápiz en Movimientos. `merchant_display_names` sin guarda de prioridad (no hay escritor IA, solo el consenso escribe). Guarda de lectura: keys de transferencia jamás consultan el global.
- **✅ Verificado en prod (2026-06-13)**: migraciones 014 y 015 aplicadas (orden migración-antes-de-deploy, `audit_rls_policies.py` + `verify_merchant_priority_guard.py` exit 0). Smoke real: renombré `60092 providencia`→Copec y `toledo`→Oxxo (`eligible=true`, aplicados a todas las tx); recategoricé `mercadopago decop`→food y quedó `eligible=false` (Bloque 0 vivo: la pasarela no se crowdsourcea); transferencia `eligible=false`; `merchant_display_names` y `source='user'` en 0 filas (sin promoción con 1 usuario).
- Fase 3 (identidad canónica por variantes) solo diseñada — sprint propio, motivada por el hallazgo del Bloque 0 (¿una key = un comercio o varios?). Detalle: `backend-python/docs/SPRINT_CATEGORIZACION_APRENDE.md`.

### 2FA y onboarding de testers (sprint 2026-06-12, segunda tanda)
- **`_post_submit_flow`** (`bchile_scraper.py`): resolución post-submit en el dominio Auth0. La ambigüedad **jamás** lanza `AuthenticationError` (mandaría la cuenta a `needs_reconnection` con la clave buena). Clave mala = SOLO con el mensaje del banco en pantalla (keyword "no son correctos", pineada por test). Pantalla desconocida sin form de login → se asume 2FA (espera + captura `pii_safe` para refinar keywords); form pegado → `RecoverableIngestionError` (ANTIBOT).
- Keywords 2FA en dos listas: `TWO_FA_KEYWORDS_CLASSIC` (post-login, portal clásico — NO agregar frases Auth0 acá: el dashboard matchearía marketing) y `TWO_FA_KEYWORDS_AUTH0` (solo en el dominio de login).
- **`waiting_2fa` se escribe de verdad**: `sync_bank_account` pasa `on_progress` al router; `PROGRESS_2FA_WAIT_PREFIX` (contracts) marca el status, `PROGRESS_LOGIN_OK` devuelve a `syncing`. NO cambiar el prefijo sin tocar `BankConnect.jsx` (fallback `/Esperando aprobaci[oó]n/i`). Cron ARQ recupera `waiting_2fa` stale (>30 min). Sin migración: el CHECK 006/013 ya permitía el status.
- Capturas debug `pii_safe` (post-submit): solo HTML scrubeado, sin screenshot (doctrina §20).

### Prioridades sugeridas
1. **B-2 — verificar el rework BCI en prod** (construido y gated 2026-06-13): test manual con cuenta real → refinar señal post-submit / keywords 2FA / bodies con la captura PII-safe → sync end-to-end → activar `bci` para tener **dos bancos operativos a la vez** (BChile + BCI). · 2. **Onboarding testers** (sync BChile verificado en prod + 2FA endurecido; bucket `scraper-debug` + `SCRAPER_DEBUG_CAPTURE=true` ya activos en el worker — **apagar post-onboarding**). · 3. **Prep pitch BCI**. · 4. **B-5** performance (medir antes de optimizar). · 5. Fase 3 categorización (identidad canónica, sprint propio). · (Cierre operativo de hoy: categorización 014/015 en prod ✅, `appealing-benevolence` apagado ✅, D2 no-op ✅.)

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
3. `pytest tests/ -v` (598 tests; cobertura en el módulo tocado)
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

`2026-06-13 (noche, 3)` · **BCI (B-2) — test #3: ROOT CAUSE del JWT encontrado y arreglado (`bearer` minúscula).** La instrumentación del test #2 pagó al primer intento. El **censo de red** (`bci_network_census`) mostró la línea de oro: `apilocal.bci.cl` se llama (GET + POST) con `has_auth=True` y **`auth_scheme='bearer'` en MINÚSCULA**, pero `_is_jwt_request` matcheaba `auth.startswith("Bearer ")` (B mayúscula) → `"bearer eyJ…".startswith("Bearer ")` = `False`: **el token estaba en CADA request a apilocal y lo dejábamos pasar por un check case-sensitive** (el frontend manda el esquema en minúscula). Las otras sondas cerraron las alternativas: storage todo `looks_like_jwt:False` (el token NO vive en local/sessionStorage — va en el header); `bci_body_captured` confirmó en vivo `por-rut {"rut":...}` y movs `{"numeroCuenta":...}`; `bci_frames` reveló que la app autenticada es un portal **JSF** (`www.bci.cl/cl/bci/aplicaciones/contenido.jsf` + `cartolaCuenta.jsf`), no `www.bci.cl/personas`. **Fix (Opus 4.8 — Fable caído a nivel mundial; solo `bci_scraper.py` + 1 test; quirúrgico; `bci` sigue `pending`)**: `_is_jwt_request` ahora case-insensitive (`auth[:7].lower()=="bearer "`, token con `.strip() or None`); comentarios del módulo (ESTRATEGIA/FLUJO + inline en `fetch`) corregidos (el JWT lo dispara la navegación a Saldos/Movimientos, no la home; esquema minúscula). Test `test_jwt_capture_case_insensitive_bearer`. Gates: ruff ✅ · mypy ✅ · pytest ✅ **696 passed, 1 skipped** (`test_bci_source.py` 45→46). **Próximo (usuario): test #4** local (mismo comando) → con el `bearer` capturado debería listar cuentas + movimientos + saldo end-to-end → sync real en prod (vigilar DetectCA easysol, tipo B-1) → activar `bci` → **dos bancos a la vez**. Plan: `backend-python/docs/SPRINT_BCI_SCRAPER_REWORK.md` (sección "Test #3 — ROOT CAUSE").

`2026-06-13 (noche, 2)` · **BCI (B-2) — test #2: login OK pero el JWT no se captura; instrumentación de diagnóstico.** El login anda end-to-end (`bci_fields_verified` + sesión iniciada); falló SOLO la captura del JWT: `_await_jwt` hizo timeout sin interceptar ninguna request Bearer a `apilocal.bci.cl` y el nudge no encontró menú. **El supuesto "el dashboard dispara apilocal solo" resultó falso**: la home `www.bci.cl/personas` no pega `apilocal` hasta navegar al view de cuentas, y el nudge era ciego al DOM (solo top frame, solo innerText). Peor: el timeout hacía `raise` sin captura → se gastó un intento de cuenta real (lockout) sin aprender. Fix (solo `bci_scraper.py` + tests; login y bodies intactos; `bci` sigue `pending`; **todo gated tras `scraper_debug_capture`, PII-safe §20**): (1) **censo de red** — `_census_entry` resume PII-safe cada request a `*.bci.cl` (host + 1er path + método + has_auth + auth_scheme, dígitos redactados, `[opaque]` si no es esquema), logueado en éxito y timeout; (2) **sonda de token** — `_probe_tokens` enumera keys de local/sessionStorage (test JWT-shaped **en JS**, solo vuelve `key→bool`, jamás el valor) + nombres/dominios de cookies bci.cl; (3) **captura DOM + frames** en el timeout (`_capture_debug` + URLs de frames vía `_safe_url`; `_scrub_pii` endurecido `\d{7,10}`→`\d{6,}`); (4) **nudge multi-frame** (innerText/aria-label/title + href, candidatos `cartola`/`productos`/`movimientos`…) + **ventana 30s** (`jwt_wait_sec`) con re-nudge a mitad. 45 tests en `test_bci_source.py` (10 nuevos), ruff+mypy verdes. **Próximo: test #3 headful con `SCRAPER_DEBUG_CAPTURE=true`** → leer el diagnóstico → fix real (¿token en storage/cookie? ¿qué click dispara `apilocal`? ¿iframe?) → sync prod → activar. Plan: `backend-python/docs/SPRINT_BCI_SCRAPER_REWORK.md` (sección "Test #2 + instrumentación").

`2026-06-13 (noche)` · **BCI (B-2) — fix dirigido post-test #1: login OK + bodies confirmados.** El test #1 con la cuenta real confirmó que el **login funciona** (post-fill verificado, sesión iniciada) y falló SOLO la extracción de datos. Fix quirúrgico en `bci_scraper.py` (NO se tocó el login): (1) **JWT por host** — `_is_jwt_request` captura el Bearer de cualquier request a `apilocal.bci.cl` (el dashboard lo dispara solo desde `usuarios/<rut>`, `cashback/<rut>`, `obtenerDatosCliente`; ya no se depende del path del BFF); (2) **sin dependencia del menú** — `fetch()` espera el JWT con `_await_jwt` (~15s), `_navigate_to_accounts_menu` queda como nudge best-effort que traga excepciones (el `bci_accounts_menu_not_found` ya no rompe); (3) **bodies CONFIRMADOS** — `por-rut {"rut":"<rut>-<dv>"}` (vía `_rut_with_dv`, como BChile; ya no `{rut,dig}`), saldo `{"cuentaNumero":"<n>"}`, movs `{"numeroCuenta":"<n>"}` (keys distintas, sin `tipo`); (4) **capture-and-replay = fallback/refuerzo** — el listener sigue logueando PII-safe el `post_data` real; el body que se envía es el confirmado, la captura de `por-rut` solo se reintenta si el confirmado no trae cuentas. 685 tests (`test_bci_source.py` 32→35: pin de JWT-por-host, bodies confirmados, fallback replay), ruff+mypy verdes. **`bci` sigue `pending`**: falta **test #2** (mismo comando, headful → debería listar cuentas + movimientos) y sync real en prod antes de activar. Plan: `backend-python/docs/SPRINT_BCI_SCRAPER_REWORK.md` (sección "Fix dirigido APLICADO").

`2026-06-13 (tarde)` · **Rework scraper BCI (B-2) construido — segundo banco en camino (commit `69a03e3`).** El portal BCI migró del muerto `portalpersonas.bci.cl` (NXDOMAIN) al widget embebido en `www.bci.cl/corporativo/banco-en-linea/personas`; la API interna (`apilocal.bci.cl`, BFF v3.2) conservó la base, cambiaron los endpoints. `bci_scraper.py` (ex `bci_direct.py` — **R-2 cerrado**: `BCIScraperSource`, sin tocar el identificador `scraper.bci` → sin migración de routing) reconstruido con el discovery (Fase 0) y las lecciones BChile pineadas: **RUT `type()` en `#rut_aux`** + **clave `fill()` en `#clave`** + **verificación post-fill** (relee ambos campos Y confirma que los hidden `#rut`/`#dig` que el JS del form puebla quedaron poblados → `FieldFillError` si no), **`_post_submit_flow`** (éxito = dejar el marcador de URL `corporativo/banco-en-linea` o JWT capturado; **la ambigüedad jamás es clave mala**; form pegado → ANTIBOT, flag tipo B-1 del DetectCA easysol), endpoints `cuentas-busquedas/por-rut` · `por-numero-cuenta` · `cuentas-movimientos/por-numero-cuenta` con JWT Bearer interceptado del host `apilocal`, y **body capture-and-replay** (el listener captura el `post_data` real del frontend para las formas que el discovery no fijó, lo loguea PII-safe y lo replica; fallbacks `{rut,dig}` / `{numero,tipo}`). Normalización con `idMovimiento`→`native_id` (idempotencia), `monto` str→int (formato chileno), `tipo`→signo. 682 tests (32 nuevos en `tests/unit/test_bci_source.py`), ruff+mypy verdes. **`bci` sigue `pending`**: falta el discovery de runtime (test manual con la cuenta BCI real → refinar señal post-submit / keywords 2FA / bodies vía captura `pii_safe`) y un sync real end-to-end en prod antes de activar. Plan: `backend-python/docs/SPRINT_BCI_SCRAPER_REWORK.md`.

`2026-06-13` · **Sprint categorización que aprende — COMPLETO Y VERIFICADO EN PROD (migraciones 014 + 015 aplicadas).** **Bloque 0 (endurecer elegibilidad)**: hallazgo de diseño — `merchant_key` no es identidad de comercio, es etiqueta de pago; las etiquetas de pasarela (`mercadopago <token>`, paypal, sumup, khipu, webpay, transbank) son comercios distintos para gente distinta → `is_crowdsource_eligible` (función única, reusada por votos Y aliases) las excluye del global por primera palabra (`GATEWAY_LABEL_FIRST_WORDS`, lista corta deliberada — el quórum es el backstop), `_key_is_promotable` re-chequea al promover (cubre votos viejos sin backfill); override per-user intacto. **Fase 2 (renombre + nombre canónico)**: migración 015 (`merchant_aliases` per-user + `merchant_display_names` global por consenso; esta última sin guarda de prioridad porque no tiene escritor IA), endpoint `PATCH …/{id}/merchant` (la tx no se muta, la key se deriva de la tx del usuario), display resuelto al leer (`merchant_display_batch`: propio → global → Title Case, con guarda de lectura: las keys de transferencia jamás consultan el global), UI lápiz inline en Movimientos con copy según elegibilidad. Fase 3 (identidad canónica) solo diseño, motivada por el hallazgo del Bloque 0. 650 tests. **Verificación en prod (2026-06-13, vía conexión directa con OK del usuario)**: migraciones 014+015 aplicadas en orden, `audit_rls_policies.py` + `verify_merchant_priority_guard.py` exit 0; smoke real → renombres `60092 providencia`→Copec / `toledo`→Oxxo (eligible=true, aplicados a todas las tx), `mercadopago decop`→food quedó `eligible=false` (Bloque 0 confirmado en vivo), transferencia eligible=false, sin promoción al global con 1 usuario. Las 3 invariantes confirmadas con dato real.

`2026-06-12 (tercera tanda)` · **Sprint categorización que aprende — Fase 1 construida (pendiente: aplicar migración 014 + deploy).** Recategorizar ahora enseña: voto per-user inmediato (nivel 0, prefix matching) + promoción al caché global con quórum de N usuarios distintos (default 3, converge a la mayoría) y guarda de prioridad user>ai en `upsert_merchant_category` — antes el upsert sobrescribía ciego y el PATCH no enseñaba nada. Frontera de privacidad: transferencias/contrapartes personales jamás se crowdsourcean (`crowdsource_eligible=false` decidido al votar con la raw_description a mano; defensa en profundidad sobre la key; fuera de logs). Resolución 5 niveles: votos → caché `'user'` → reglas → caché `'rule'/'ai'` → Haiku (desviación deliberada del doc del sprint: solo el tier `'user'` sube sobre las reglas, para no dejar que semillas/filas IA viejas sombreen las reglas sign-dependent por prefijo). El job propaga `user_id`. Bug latente cerrado: `'travel'` no existe en el CHECK de transactions (picker "Viajes" → 500) — backend y picker alineados al canon de 16 (`insurance` entra). Migración 014 con drop del CHECK era-Node por inspección de `pg_constraint` + `verify_merchant_priority_guard.py` (verificación funcional con ROLLBACK, correr en staging y prod). Fase 2 gated a verificación en prod; Fase 3 solo diseño (sprint doc). 598 tests.

`2026-06-12 (segunda tanda)` · **Sprint endurecer onboarding de testers cerrado.** Riesgo mayor neutralizado: un tester con BChile Pass disparaba el 2FA Auth0 no detectado → 20s de poll → `AuthenticationError` → `needs_reconnection` con la clave buena ("tu clave cambió" falso). Nuevo `_post_submit_flow`: la ambigüedad jamás se castiga como clave mala; 2FA positivo con keywords Auth0 (frases compuestas) + asunción de 2FA en pantallas desconocidas sin form + capturas `pii_safe` para refinar. `waiting_2fa` ahora se escribe de verdad (wiring `on_progress` que faltaba; el frontend ya sabía mostrarlo); cron ARQ recupera `waiting_2fa` stale. Cobertura `needs_reconnection` completada (cron HTTP, reset por reconexión, keyword pineada). UX: "Primera sincronización…" visible, panel operador con `by_status`. Debts: `_sanitize_error` eliminado, `check_gates.ps1` ASCII (la "Ó" rompía el parser de PS 5.1). B-6 cerrado (`appealing-benevolence` apagado). Sin migración SQL. 555 tests.

`2026-06-12` · **Sprint ingesta BChile cerrado — MVP desbloqueado.** Causa raíz del bloqueador: `$` de la clave mal tecleado por `type()` en Chromium bundled headless (la clave en DB estaba bien). Fase A verificada en prod (sync real: 42 movs, channel=chrome): clave con `fill()`, RUT sigue con `type()`, verificación post-fill con `FieldFillError`, Chrome real en worker, `--force-bundled` para repro. Fase B: ciclo `needs_reconnection` (migración 013) con hard-stop anti-bloqueo en todos los caminos + UX Reconectar. Fase C: taxonomía `SyncFailureKind`, panel operador `/api/internal/operator/sync-status`, capturas debug a Supabase Storage, auto-refresh del dashboard post-categorización. Fase D: B-1 y B-7 cerrados; pendiente manual: apagar `appealing-benevolence` (D1), correr `cleanup_bchile_accounts.sql` (D2). Plan: `backend-python/docs/SPRINT_INGESTA_BCHILE_AUTH0.md`.

`2026-06-09` · B-7 cerrado: falso positivo URL scraper BChile post-migración Auth0 (check `/login` en URL → poll positivo + revert fill→type). B-1 marcado para re-verificar en Railway. Ver detalles en B-7.

`2026-05-27` · Saga de números: idempotencia con id nativo BChile + fallback con saldo, ventana mes calendario, audit_log vocabulario reconciliado, tzdata pinneado, toggles simétricos transfer→ingreso/gasto (default ON, principio contable), cleanup + categorize self-drain. Detectado y documentado el double-write de Node legacy (B-6). Migraciones aplicadas: 006 (`bank_accounts.status`), 007 (`count_transfers_as_income`), 008 (`count_transfers_as_expense`). Lint E501 pendiente en `tests/unit/test_finance.py:216-217`.

`2026-05-23` · Reescrito para reflejar que la **migración Python está completa y en producción** (las 13 fases cerradas, Node archivado). Alineado con `docs/ESTADO_DEL_ARTE.md`. El v5 PDF sigue siendo la fuente doctrinal/legal; su Parte II quedará reescrita cuando se reactualice el registro INAPI.
