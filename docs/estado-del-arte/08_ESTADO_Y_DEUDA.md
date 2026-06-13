# 08 — Estado Real y Deuda Viva

[← Volver al índice](../ESTADO_DEL_ARTE.md)

> La sección más importante para operar honestamente. Doctrina §22: "la deuda se documenta, no se oculta".
> Referencia de deuda formal: `backend-python/docs/REMEDIATION_P0_P3.md`.

**Última actualización**: 2026-06-12

---

## ✅ Lo que funciona (verificado)

- **Producción viva**: `app.skyfinanzas.com` + `api.skyfinanzas.com` responden 200.
- **Migración Python completa**: 13 fases cerradas, cutover hecho, Node archivado.
- **Categorización**: feedback loop de 5 niveles **verificado en prod** (Fase 1, migración 014 aplicada). El renombre de comercios (Fase 2: aliases per-user + nombre canónico global) está construido y commiteado, **pendiente de aplicar migración 015 + deploy** (ver el bloque del sprint abajo).
- **Display ingreso/gasto**: por signo del monto — ingresos en verde, gastos en rojo.
- **Cifrado, RLS, audit (parcial), data export, rate limit, idempotencia**: implementados.
- **Scraper BChile**: ✅ **validado end-to-end EN PRODUCCIÓN (2026-06-12)** — sync real desde Railway: login OK, 42 movimientos, balance correcto, `channel="chrome"`, categorización OK. El MVP para testers está desbloqueado.
- **Cola ARQ**: corregida (ver abajo).

## 🏁 Sprint ingesta BChile 2026-06-12 (cerrado)

Plan completo: `backend-python/docs/SPRINT_INGESTA_BCHILE_AUTH0.md`. Causa raíz del
bloqueador del MVP: la clave del fundador termina en `$` y `type()` lo tecleaba mal
en Chromium bundled headless (prod); local con Chrome real funcionaba. La clave en
DB estaba bien (cifrado sano). Qué quedó construido:

- **Fase A (verificada en prod)**: `_fill_password` usa `fill()` (el RUT **se queda**
  con `type()` por la directiva Angular `delete-zero-left`); verificación post-fill
  lee `input.value` antes del submit y lanza `FieldFillError` (recoverable, no auth,
  solo longitudes — jamás el valor); Chrome real en el worker
  (`docker/worker.Dockerfile`) con bundled de fallback (warning visible);
  `browser_channel` setting + `--force-bundled` para repro local sin tocar al banco.
- **Fase B — ciclo de credenciales**: nuevo status `needs_reconnection`
  (migración 013) cuando el banco rechaza la clave de verdad. Hard-stop en TODOS
  los caminos (cron ARQ, sync-all, cron HTTP deprecated, endpoint manual → 409,
  backstop dentro del worker). Imposible llegar al 3er fallo del banco por acción
  automática. Frontend: "Actualizar" deshabilitado + "Reconectar" primario con
  banco preseleccionado.
- **Fase C — observabilidad**: taxonomía `SyncFailureKind` en contracts
  (wrong_credentials · needs_2fa · bank_temporary · antibot · field_fill_failed)
  con mensaje y acción por kind; `failure_kind` en el audit_log; panel de operador
  `GET /api/internal/operator/sync-status` (x-cron-secret) — estado + último error
  real sin scripts ad-hoc; capturas debug a Supabase Storage
  (`scraper_debug_bucket`, bucket privado, best-effort); auto-refresh del dashboard
  mientras la categorización async drena (sin recarga manual).
- **Fase D**: script `scripts/cleanup_bchile_accounts.sql` (D2, correr manual);
  docs sincronizados (D3). D1 ✅ **`appealing-benevolence` apagado en Railway
  (confirmado 2026-06-12)** — cierra B-6.

## 🛡️ Sprint endurecer onboarding de testers (2026-06-12, segunda tanda — cerrado)

Continuación inmediata del sprint de ingesta: blinda la experiencia para testers
reales, no solo la cuenta del fundador. **Sin migración SQL** (el status
`waiting_2fa` ya estaba permitido por el CHECK de las migraciones 006/013).

- **2FA sobre Auth0** (el riesgo mayor: testers con Banco de Chile Pass). El
  challenge "aprueba en tu app" del form Auth0 no matcheaba los
  `TWO_FA_KEYWORDS` del portal viejo → el poll de URL expiraba a los 20s →
  `AuthenticationError` → `needs_reconnection` (hard-stop B2) con "tu clave
  cambió" **falso**. Nuevo `_post_submit_flow` en `bchile_scraper.py`: éxito =
  la URL sale del dominio Auth0; error del banco (keywords, en cualquier tick)
  = `AuthenticationError`; 2FA positivo (keywords nuevas, frases compuestas) =
  espera con timeout completo + progreso visible; ambiguo tras 25s → form
  visible = `RecoverableIngestionError` (ANTIBOT), form ausente = se asume 2FA
  desconocido (beneficio de la duda + captura debug para refinar keywords).
  **La ambigüedad jamás se castiga como clave mala.** Keywords divididas
  CLASSIC (camino post-login verificado en prod, intacto) / AUTH0 (solo en el
  dominio de login).
- **Capturas PII-safe**: `_capture_debug(pii_safe=True)` para estados
  post-submit (error de login, pantallas 2FA, form pegado) — solo HTML
  scrubeado (`_scrub_pii`: values de inputs, RUTs, corridas de dígitos), sin
  screenshot (doctrina §20). Es el material para refinar la detección cuando
  un tester real dispare el challenge.
- **`waiting_2fa` visible (el wiring que faltaba)**: el status existía y el
  frontend lo sabía renderear, pero `sync_bank_account` llamaba al router SIN
  `on_progress` — nunca se escribía. Ahora el prefijo
  `PROGRESS_2FA_WAIT_PREFIX` (constante en contracts, convención
  fuente↔worker) marca `waiting_2fa` y `PROGRESS_LOGIN_OK` devuelve a
  `syncing`; los UPDATE corren como tasks drenadas antes de cualquier
  escritura final de estado. El cron ARQ recupera `waiting_2fa` stale
  (>30 min) junto con `syncing`.
- **Cobertura `needs_reconnection` completada**: cron HTTP deprecated (sin
  test alguno → ahora pinea el guard del SELECT), reconexión (upsert resetea
  `status/consecutive_errors/last_sync_error` — si se pierde, la cuenta queda
  en hard-stop CON la clave nueva), keyword "no son correctos" pineada,
  credenciales jamás en texto plano en params.
- **UX multi-tester**: tarjeta distingue "Primera sincronización — puede
  tardar unos minutos…" (syncCount=0) de "Sincronizando con el banco…";
  "Actualizar" se deshabilita ante syncs de cualquier origen; `handleSync`
  muestra el `{detail}` de FastAPI tal cual (regex AUTH_FAILED/2FA_TIMEOUT de
  la era Node eliminados). Panel operador con `by_status` (triage de un
  vistazo, sigue sin PII).
- **Debts cerrados**: `_sanitize_error` (código muerto post-taxonomía C1)
  eliminado con sus tests; `check_gates.ps1` 100% ASCII (PS 5.1 sin BOM lee
  ANSI: el segundo byte UTF-8 de "Ó" es 0x93 = comilla tipográfica → rompía el
  parser).
- Tests: 534 → 555 (descontando los 5 de `_sanitize_error` eliminados).

## 🧠 Sprint categorización que aprende — Fase 1 construida (2026-06-12, tercera tanda)

Plan: `backend-python/docs/SPRINT_CATEGORIZACION_APRENDE.md`. Es el "§4 votos
crowdsourced" diferido desde Fase 6: **recategorizar ahora enseña** — antes el
PATCH solo actualizaba la tx y `upsert_merchant_category` sobrescribía ciego
(una pasada de IA podía pisar la corrección de un usuario).

- **Migración 014** (`merchant_category_votes` + el CHECK era-Node de `source`
  acepta `'user'` + `upsert_merchant_category` con guarda de prioridad).
  ⚠️ **Pendiente de aplicar — va ANTES del deploy de api+worker** (el código
  viejo es compatible con el esquema nuevo; el nuevo no corre sin la tabla).
  Tras aplicar: `audit_rls_policies.py` + `verify_merchant_priority_guard.py`
  (script nuevo: ejercita la guarda contra DB real con ROLLBACK, sin residuos).
- **Guarda de prioridad user > ai**: una fila `source='user'` solo la actualiza
  otra escritura `'user'`. La IA jamás pisa un voto humano.
- **Frontera de privacidad**: elegibilidad decidida al votar (prefijo de
  transferencia o categoría `transfer` → `crowdsource_eligible=false`): el voto
  vale como override privado pero JAMÁS se promueve al global. Defensa en
  profundidad re-chequea la key antes del upsert. Keys inelegibles fuera de logs.
- **Anti-envenenamiento**: promoción al caché global solo con ≥ N usuarios
  distintos de acuerdo (`merchant_vote_promotion_threshold`, default 3, env);
  converge a la mayoría real (COUNT DISTINCT por categoría), no al último voto.
- **Resolución 5 niveles**: votos propios (prefix matching, per-user) → caché
  `source='user'` (el consenso corrige una regla equivocada PARA TODOS) → reglas
  regex → caché `'rule'`/`'ai'` → Haiku. Desviación deliberada del doc del
  sprint: solo el tier `'user'` sube sobre las reglas, para que semillas/filas
  IA viejas no sombreen por prefijo las reglas sign-dependent (transfer/income).
  `categorize_pending_job` ahora propaga `user_id` (el SELECT no lo traía).
- **Bug latente cerrado**: el PATCH aceptaba `'travel'`, que NO existe en el
  CHECK de `transactions` (elegir "Viajes" en el picker → 500 en prod), y
  rechazaba `'insurance'` (DB-válida) con 422. Backend (`set(CATEGORIES)`) y
  picker de `Sky.jsx` alineados al canon de 16.
- **Fase 2** (renombre/alias de comercio) NO arrancada — gated a verificación en
  prod de la Fase 1. **Fase 3** (identidad canónica por variantes) solo
  diseñada en el sprint doc — candidata a sprint propio.
- Tests: 555 → 598.

### Actualización 2026-06-13 — Fase 1 verificada en prod · Bloque 0 + Fase 2 construidos

- **Fase 1 VERIFICADA EN PROD** (migración 014 aplicada): votos, frontera de
  privacidad y anti-envenenamiento OK.
- **Bloque 0 (endurecer elegibilidad)**: un hallazgo de diseño obligó a
  refinar la frontera ANTES del renombre — `merchant_key` NO es una identidad
  de comercio, es una **etiqueta de pago**. Las etiquetas de pasarela/terminal
  (`mercadopago <token>`, paypal, sumup, khipu, webpay, transbank) pueden ser
  comercios distintos para gente distinta → crowdsourcearlas mezcla negocios
  ajenos (y en wallets P2P filtra contrapartes). `is_crowdsource_eligible`
  (**función única**, reusada por votos de categoría Y aliases) las excluye del
  global por **primera palabra** de la key (`GATEWAY_LABEL_FIRST_WORDS`, sin
  substring; lista corta deliberada — mejor sub-excluir, el quórum es el
  backstop). `_key_is_promotable` re-chequea al promover (cubre votos viejos
  persistidos como elegibles, sin backfill). Override per-user intacto.
- **Fase 2 (renombre + nombre canónico)** construida: **migración 015**
  (`merchant_aliases` per-user con RLS por usuario + `merchant_display_names`
  global por consenso, RLS service_role only). `merchant_display_names` NO
  lleva guarda de prioridad — a diferencia de `merchant_categories` no tiene
  escritor IA, solo la promoción con quórum escribe. Endpoint
  `PATCH /api/transactions/{id}/merchant` (la tx NO se muta; la `merchant_key`
  se deriva de la tx del usuario, el cliente nunca la manda). Display resuelto
  al leer (`categorizer.merchant_display_batch`: alias propio → alias global →
  Title Case; **guarda de lectura**: keys de transferencia jamás consultan el
  global, el alias propio sí aplica como renombre privado de la contraparte;
  fail-open). UI: lápiz inline en Movimientos (`Sky.jsx`) con copy según
  elegibilidad. **⚠️ Migración 015 pendiente de aplicar — va ANTES del deploy**
  (preflight `to_regclass` de ambas tablas → NULL; el código viejo no lee las
  tablas nuevas, el nuevo las necesita).
- **Fase 3** (identidad canónica por variantes) sigue solo diseño — ahora
  motivada explícitamente por el hallazgo del Bloque 0 (¿una key = un comercio
  o varios?).
- Tests: 598 → 650. Smoke `/api/health` 200 OK.

## ❌ Lo que NO funciona / bloqueadores

### ✅ B-1 · Scraping bloqueado desde datacenter (anti-bot) — **obsoleto, cerrado 2026-06-12**

**Cierre**: con la migración del banco a Auth0, el scraper desde la IP de Railway carga, llena y **envía** el form sin challenge — el bloqueo de datacenter dejó de aplicar. Confirmado con el sync real en prod del 2026-06-12 (42 movimientos). El fallo que quedaba tras B-7 no era anti-bot: era el `$` de la clave mal tecleado por `type()` en Chromium bundled headless (ver sprint 2026-06-12 arriba).

**Contexto histórico**: BChile estaba detrás de **Imperva Incapsula** en `portalpersonas.bancochile.cl`. El scraper headless desde datacenter era detectado como bot → página-desafío sin formulario → "No se encontró el campo de RUT". Desde IP residencial funcionaba. Las palancas de stealth (2026-05-25: `--disable-blink-features=AutomationControlled`, UA realista, `navigator.webdriver=undefined`, `browser_headless`, `scraper_debug_capture`) se conservan.

**Implicación estratégica intacta**: el scraping sigue siendo frágil ante cambios del banco (esta saga lo demuestra dos veces). **Refuerza la tesis SFA.**

### ✅ B-7 · Falso positivo URL BChile post-migración Auth0 — **cerrado y verificado en prod 2026-06-12**

**Causa raíz**: BChile migró el form de login a `login.portales.bancochile.cl/login` (Auth0 + Angular), manteniendo los IDs DOM intactos. El scraper tenía el check `if "/login" in page.url` para detectar login fallido — pero el nuevo dominio contiene literalmente `/login` en la URL → todos los syncs caían en `AuthenticationError` al completarse correctamente → mensaje "Credenciales rechazadas por el banco" para todos los usuarios y testers. No era Incapsula.

**Fix aplicado**:
- `commit 6fdae84`: check `"/login" in url` reemplazado por poll positivo de hasta 20s esperando que la URL salga de `login.portales.bancochile.cl`. Si el poll agota el timeout → `logger.warning` + `_capture_debug` + `AuthenticationError("Login falló — el portal siguió en pantalla de login post-submit")`.
- Historia del fill/type (importante para no repetir el error): `6fdae84` cambió **ambos** campos a `fill()` y rompió el RUT (la directiva Angular `delete-zero-left` requiere keystrokes reales) → `3145a0c` revirtió ambos a `type()` → el sprint 2026-06-12 estableció la forma correcta y la pineó con tests: **RUT = `type()` · password = `fill()`** (el campo password no tiene la directiva, y `type()` manglaba el `$` en bundled headless).

**Verificación en prod (2026-06-12)**: sync real desde Railway — login OK, 42 movimientos, balance correcto, `channel="chrome"`, categorización OK.

### B-2 · Scraper BCI roto — dominio cambiado
`portalpersonas.bci.cl` ya no resuelve (NXDOMAIN desde toda red probada; antes funcionaba). BCI cambió el dominio de su portal. Requiere rework: nuevo dominio + probablemente nuevos selectores y endpoints de API interna. BCI está en `pending`. Sprint propio pendiente.

### ✅ B-3 · Auditoría — bug de runtime corregido (2026-05-25)

**Bug encontrado**: el INSERT en `sky/core/audit.py` usaba `:detail::jsonb`. Con SQLAlchemy `text()` + asyncpg, el cast `::jsonb` rompe el parseo del bind param nombrado `:detail` → asyncpg lanza `PostgresSyntaxError` en runtime. **Ningún evento de auditoría se escribía en Postgres real** desde el inicio del sistema.

**Fix aplicado**: `CAST(:detail AS jsonb)` en lugar de `:detail::jsonb`. Un line change quirúrgico. Test de regresión agregado en `tests/unit/test_audit.py` (`test_sql_uses_cast_not_postgres_cast_syntax`) que verifica que el SQL compilado no contiene `::jsonb`.

**Estado**: ✅ corregido y cubierto por test. Verificación de runtime con Postgres de staging sigue siendo recomendable para confirmar que `resource_id uuid` acepta `str` Python vía asyncpg, pero el bug de sintaxis está resuelto.

### B-4 · Balance visible tras desconectar cuenta
`handleDisconnect` en `BankConnect.jsx` llamaba `loadAccounts()` (refresca estado interno del componente) pero no llamaba `onSyncComplete?.()`, que es el callback que refresca `bankBalances` en `Sky.jsx`. **Corregido** (2026-05-23): se agregó `onSyncComplete?.()` tras `loadAccounts()`. Verificación visual de QA manual pendiente.

### B-5 · Lentitud general
La app se siente lenta. Sin profiling aún. Sospechas: cold-start de Railway, queries de `/summary`/`/transactions`, re-renders del god-component `Sky.jsx`, polling de `BankConnect` cada 5s. **Medir antes de optimizar.**

## ✅ Corregido recientemente (mayo 2026)

| Fix | Detalle |
|---|---|
| **A1 — categoría real en sync bancario** | `banking_sync._track_aria_events` tenía hardcoded `"category": "other"`. Cambiado a `getattr(m, "category", None) or "other"` — future-proof cuando `CanonicalMovement` reciba el campo. |
| **A2 — track_goal_event cableado** | `goals.py`: `_fire_goal_aria` (fire-and-forget) nunca se disparaba. Ahora se dispara en `create_goal` (status=active), `update_goal` (active/completed según pct), `delete_goal` (abandoned). |
| **A3 / A3b — aria_consent endpoint + toggle frontend** | `ProfilePatch` expone `aria_consent: bool \| None`. Endpoint `PATCH /api/profile` persiste el valor en `profiles.aria_consent`. Frontend `Sky.jsx`: sección "Privacidad y datos" con toggle "Compartir patrones anónimos para mejorar Sky". |
| **Cola ARQ** | `worker/main.py` ahora crea el pool con `default_queue_name="sky:default"`. Antes, `categorize_pending_job` caía en `arq:queue` (fantasma) y nunca corría → "Procesando..." eterno + todo rojo. Causa raíz de dos síntomas. |
| **Income display** | `Sky.jsx` usa `tx.amount > 0` (3 lugares) en vez de `category === "income"`. Ingresos sin glosa estándar ya no se ven como gasto. |
| **BankConnect** | `Promise.allSettled` — la lista de bancos no se rompe si `/accounts` falla. |
| **VITE_API_URL** | Reapuntado de `api-v2` (canary muerto) a `api.skyfinanzas.com`. |
| **Listado bancos** | `SUPPORTED_BANKS` solo expone BChile + BCI. |
| **SyntaxWarning `\S`** | Docstrings de scripts como raw strings. |
| **PII en logs scraper** | (2026-05-23) Eliminados dos `logger.info` de debug que registraban RUT, nombre y nº de cuenta a nivel INFO en `bchile_scraper.py`. Doctrina §16. |
| **Transparencia de errores de sync** | (2026-05-23) `AllSourcesFailedError` conserva la causa; mensaje al usuario por tipo de error; no se reintentan fallos terminales (ARQ). |
| **propose_challenge roto** | (2026-05-23) La tool generaba desafíos freeform sin `challenge_id`; el frontend esperaba `{type, input:{challenge_id, reasoning}}` y crasheaba. Restaurada la paridad con el catálogo `MOCK_CHALLENGES`. |
| **Tests de chat rotos** | (2026-05-23) 4 tests de `test_api_chat.py` asertaban el contrato viejo (`type/text/route`) ya reemplazado por `ChatUnifiedResponse`. Actualizados → recuperada la red de cobertura de Mr. Money. |
| **ruff verde** | (2026-05-23) Limpiadas las 17 violaciones preexistentes (imports muertos, EOF, líneas largas). El gate `ruff check exit 0` ahora se cumple. |
| **audit INSERT roto en runtime (B-3)** | (2026-05-25) `:detail::jsonb` rompía asyncpg con named params → 0 filas escritas. Corregido con `CAST(:detail AS jsonb)`. Test de regresión agregado. |
| **Mr. Money: logging silencioso en errores Anthropic** | (2026-05-25) `except` usaba `logger.warning` sin traceback. Cambiado a `logger.error(exc_info=True)` con detección explícita de `AuthenticationError`/`APIStatusError`. |
| **Stealth anti-bot básico en browser_pool** | (2026-05-25) `--disable-blink-features=AutomationControlled`, User-Agent realista, `navigator.webdriver=undefined`. Palancas `browser_headless` + `scraper_debug_capture`. |
| **Validators fail-fast en Settings** | (2026-05-25) `field_validator` en pydantic v2 para secrets críticos: vacío/espacios → error al arrancar. `anthropic_api_key` valida además prefijo `sk-ant`. |
| **KPI Ingresos perdía positivos no-income/no-transfer** | (2026-05-28) `compute_summary` usaba whitelist `category IN ('income','transfer')` para income — positivos con `category='other'`, `'food'`, etc. caían en ninguna rama y se perdían del summary (~$50K invisibles: sidebar vs donut). Tercera aparición del patrón "filtro por categoría en vez de signo" (anteriores: toggle Tipo frontend, B-3 vocabulario audit). Fix: predicado por signo (`amount > 0 AND (category != 'transfer' OR count_transfers_as_income)`). Tests de regresión en `TestIncomeBySign` · `test_finance.py`. |

## 🆕 ARIA-quali v1 (2026-05-29)

Nueva capa de inteligencia cualitativa incorporada en producción. No es deuda — es feature nueva.

### Perfil cualitativo privado (`public.user_financial_profile`)
- Tabla con dimensiones psicológicas/financieras: `savings_mindset`, `risk_tolerance`, `financial_volatility`, `goal_orientation`, `stress_baseline/current`, `emotional_volatility`, `motivation_primary`, `recurring_blockers`, `protective_behaviors`, `emotion_history` (jsonb).
- **RLS `ufp_service_only`**: `USING (false) WITH CHECK (false)` — ningún JWT puede leer ni escribir. Solo `service_role`. El perfil es invisible al usuario.
- **Migración**: `migrations/011_user_financial_profile.sql` (aplicar manualmente).

### Mr. Money: contexto enriquecido + tools
- `_build_financial_context` inyecta sección "PERFIL APRENDIDO" para dimensiones con `confidence >= 0.5`.
- Tool `read_profile`: Mr. Money puede leer el perfil propio para enriquecer respuesta.
- Tool `update_profile_dimension`: actualiza una dimensión del allow-list (`_EDITABLE_DIMENSIONS`). El allow-list bloquea columnas como `user_id` o `emotional_volatility` (estas solo las calcula el sistema).
- Tool `infer_emotional_state` (**premium-gated**): llama a `apply_emotion_inference` que registra `last_emotion`, actualiza `stress_current`, y calcula `emotional_volatility` como desviación estándar móvil de las últimas 20 observaciones.

### Snapshot semanal k-anon (`aria.user_profile_snapshots`)
- Job ARQ `snapshot_profiles_job`: corre lunes 06:00 UTC. Agrupa perfiles por `(age_range, region, income_range, occupation)`. Buckets con menos de `profile_snapshot_k_anon_min` (default 5) se descartan. Los que superan el umbral se insertan como snapshots anónimos con jitter ±`profile_snapshot_jitter_days` días.
- Tabla `aria.user_profile_snapshots`: sin `user_id`, sin UUID. Solo datos agregados. `service_role` only.
- **Migración**: `migrations/012_aria_user_profile_snapshots.sql` (aplicar manualmente).

### Data export (Ley 19.628)
- `_collect_user_data` agrega dataset `perfil_cualitativo` al ZIP. El usuario puede descargar sus propias dimensiones aprendidas.

### Deuda nueva introducida por ARIA-quali v1

| ID | Item | Nota |
|---|---|---|
| **Q-1** | `profiles.tier` no existe | `_is_premium_user()` siempre retorna `False` → `infer_emotional_state` deshabilitado para todos. Retomar cuando se agregue la columna `tier` a `public.profiles`. |
| **Q-2** | `k_anon_min=5` es bajo para ARIA | Para privacidad ARIA robusta el umbral debería ser ≥10. Aceptable para lanzamiento con base de usuarios pequeña; subir a 10 cuando haya ≥100 usuarios activos. Configurable sin redeploy (`profile_snapshot_k_anon_min` en settings). |
| **Q-3** | Snapshot no tiene test de integración contra Postgres real | Los tests de `test_snapshot_profiles.py` mockean el insert a `aria.*`. El job funciona lógicamente pero el insert a Supabase no está verificado en staging. Confirmar en el primer run real. |
| **Q-4** | Perfil cualitativo sin ponderación temporal | `upsert_profile_dimension` (`financial_profile.py:96`) sobreescribe cada dimensión con la última inferencia de Claude. Sin EWMA para numéricas, sin histograma ponderado para categóricas, sin decay temporal. Único componente con memoria: `emotion_history` (jsonb capped 20) + `emotional_volatility` (rolling std). Consecuencia: el perfil puede saltar entre estados ante un mensaje impulsivo y los snapshots a `aria.*` quedan ruidosos. Sprint propio planeado con parámetros aprobados (suave: α=0.25 numéricas, threshold conf 0.8 categóricas, confianza acumulativa). **Hacer antes de cualquier demo del perfil cualitativo** — el primer cliente que vea el perfil "saltando" pierde confianza. |

## 🧹 Rastrilleo de deuda menor (2026-05-23)

Hallazgos del barrido de calidad. No bloquean, pero se documentan para no acumularse (doctrina §22):

| ID | Item | Nota |
|---|---|---|
| ✅ **R-1** | ~~Lista de bancos duplicada en 4+ lugares~~ | **Cerrado 2026-05-23.** `SUPPORTED_BANKS` (incl. `account_type`) es la fuente única. `_DEFAULT_ACCOUNT_TYPE` eliminado de `banking.py` y `summary.py`. `DEFAULT_RULES` alineado a bchile+bci. |
| **R-2** | Naming engañoso de BCI | `BCIDirectSource` (archivo `bci_direct.py`) tiene `source_identifier == "scraper.bci"` y BCI es un scraper (no API directa). Renombrar a `BCIScraperSource`/`bci_scraper.py` cuando se haga el rework B-2. |
| ✅ **R-3** | ~~`FalabellaScraperSource` muerto~~ | **Cerrado 2026-05-23.** Dejó de registrarse en `build_all_sources`; el archivo se conserva como skeleton de referencia. |
| ✅ **R-4** | ~~`RuntimeWarning: coroutine never awaited`~~ | **Cerrado 2026-05-24.** Fixture autouse en `test_sync_job` deshabilita la tarea fire-and-forget de ARIA (no la verifican). Suite sin warnings (`pytest -W error::RuntimeWarning` verde). |
| **R-5** | Webhooks sin verificación de firma | `webhooks.py`: TODO de validar HMAC-SHA256 nunca implementado. Confirmar que la ruta no haga nada sensible mientras Fintoc no esté cableado. Cerrar cuando se cablee Fintoc (agregar HMAC primero). |
| ✅ **R-6** | ~~Sin gate automático~~ | **Cerrado 2026-05-23.** `.githooks/pre-push` corre ruff+mypy+pytest antes de cada push. Activar con `git config core.hooksPath .githooks`. Script manual: `backend-python/scripts/check_gates.ps1`. |
| ✅ **R-7** | ~~BOM en 3 mensajes de commit~~ | **Cerrado 2026-05-24.** Removido el BOM UTF-8 de los 3 subjects vía `git filter-branch --msg-filter` (commits aún sin pushear; contenido idéntico verificado con diff vacío). |

## Deuda de infraestructura

- ✅ **`appealing-benevolence`** (Node legacy, B-6) — **apagado en Railway, confirmado 2026-06-12**. Cierra el último riesgo de double-write.
- **`api-v2.skyfinanzas.com`** — custom domain leftover del canary, devuelve 502. Limpiar.
- **Warm standby** en Fly.io recomendado (DR Railway).
- **Bucket `scraper-debug`** (C3): crearlo privado en Supabase Storage y setear `SCRAPER_DEBUG_BUCKET` en el worker para activar capturas durables. Sin TTL nativo — purga manual. **Sube de valor con el sprint testers**: las capturas pii_safe del 2FA son el material para refinar `TWO_FA_KEYWORDS_AUTH0` cuando un tester real dispare el challenge.

## Inventario de deuda P0-P3 (de `REMEDIATION_P0_P3.md`)

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

## Prioridades sugeridas (orden)

0. **Deploy Fase 2 categorización que aprende** (Fase 1 ya en prod): preflight `to_regclass('public.merchant_aliases')` + `…merchant_display_names` → NULL → aplicar migración 015 en staging → `audit_rls_policies.py` → prod + re-audit → deploy Railway api+worker → smoke (renombrar comercio de una tx → fila en `merchant_aliases` con `crowdsource_eligible=true` + nombre en TODAS las tx del comercio; renombrar "Transferencia a:…" o `mercadopago*…` → `crowdsource_eligible=false` y nada en `merchant_display_names`).
1. **Cierre operativo restante**: correr `cleanup_bchile_accounts.sql` (D2) si no se corrió; crear bucket `scraper-debug` + `SCRAPER_DEBUG_BUCKET` en el worker (recomendado para el onboarding — captura el DOM del 2FA real). Verificar migración 013 aplicada antes del deploy del worker si hubiera duda.
2. **Onboarding de testers reales** — sync BChile verificado en prod + 2FA endurecido (sprint testers). Cada tester conecta con su clave vigente; si tiene BChile Pass, la espera de aprobación ahora es visible (waiting_2fa).
3. **Prep del pitch BCI** (objetivo de negocio inmediato — ver `Documentacion_Externa_Reuniones_Bancos/`).
4. **B-2** rework scraper BCI (sprint propio).
5. **B-5** performance (profiling primero).
6. Limpiar `api-v2` + warm standby Fly.io.
