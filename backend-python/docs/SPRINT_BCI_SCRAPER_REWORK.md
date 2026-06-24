# SPRINT — Rework scraper BCI (B-2): segundo banco operativo

> **ESTADO (2026-06-24)**: el rework cerró **en local** (login → captura JWT → API
> in-page → normalización; tests verdes). Se **activó `bci` el 2026-06-14** y el
> **primer sync real en prod falló** — el worker recibió un *managed challenge* de
> Cloudflare en el login → **repliegue a `pending` el 2026-06-24**. **Foco: hacer
> funcionar el scraper en prod; causa raíz en diagnóstico (sprint propio — causa
> aún NO determinada, no asumir datacenter/IP).** Estado canónico al día:
> `docs/estado-del-arte/08_ESTADO_Y_DEUDA.md` B-2. Lo de abajo es el **log histórico**
> del rework (discovery + tests #1–#6); se conserva por doctrina §22.
>
> ⚠️ El **§0 "Estado actual"** de más abajo quedó congelado en el arranque
> (2026-06-13, citando `bci_direct.py` pre-R-2) — es histórico, no el estado vigente
> (hoy: `bci_scraper.py` / `BCIScraperSource`).

---

## 0. Estado actual (verificado en código)

`backend-python/src/sky/ingestion/sources/bci_direct.py` — `BCIDirectSource`,
`source_identifier="scraper.bci"`. Estrategia (buena, se conserva):
1. Login en el portal web (RUT + clave, `type()`).
2. Detectar 2FA (BCI Digital Pass) → esperar aprobación.
3. Navegar al menú de cuentas → el frontend dispara requests con **JWT Bearer**.
4. **Interceptar el JWT** del tráfico de red (`page.on("request")`).
5. Llamar la API interna directamente: `GET /cuentas`, `POST /cuentas-busquedas/por-numero-cuenta` (saldo).
6. Normalizar a `CanonicalMovement`.

**Lo roto:**
- `BCI_BANK_URL = "https://portalpersonas.bci.cl/mibci/login"` → **dominio muerto** (NXDOMAIN).
- `BCI_API_BASE = "https://apilocal.bci.cl/bci-produccion/api-bci/bff-saldosyultimosmovimientoswebpersonas/v3.2"` → **a verificar** (puede haber cambiado con el portal).
- Selectores de login (`RUT_SELECTORS`, `PASS_SELECTORS`, `SUBMIT_SELECTORS`) → del portal viejo, a re-derivar.

**Candidato de dominio nuevo** (web search, SIN verificar): `bciimg.bci.cl/sitioseguro/login/login_personas_act.html`. La captura de Fase 0 lo confirma o lo corrige.

**Deuda R-2 (cerrar en este rework)**: renombrar `BCIDirectSource`→`BCIScraperSource`, `bci_direct.py`→`bci_scraper.py` (es scraper, no API directa; el nombre engaña).

---

## ⚠️ Dependencia bloqueante: cuenta BCI real

Igual que BChile necesitó la cuenta del fundador, esto necesita **una cuenta BCI** (fundador o cofundador Juan José) para: confirmar el dominio nuevo, capturar el DOM de login, ver el flujo 2FA, e identificar el JWT + los endpoints de API actuales. **Sin cuenta BCI, el discovery no arranca.** Confirmar disponibilidad antes de planificar fechas.

---

## FASE 0 — Discovery (primero, gating; la hace el fundador con captura)

Mismo playbook que destrabó BChile Auth0:
1. Apuntar `BCI_BANK_URL` al candidato (`bciimg.bci.cl/...` o el que resulte) y correr el test manual local **con captura debug** (`SCRAPER_DEBUG_CAPTURE=true`, `--headless` para reproducir prod, y headful para diagnosticar) contra la cuenta BCI real.
2. Capturar: (a) el HTML del form de login nuevo → selectores RUT/clave/submit reales; (b) el flujo 2FA (keywords del portal nuevo); (c) **el tráfico de red post-login** → confirmar el dominio del JWT Bearer y los endpoints de API vigentes (`/cuentas`, saldo, movimientos).
3. Yo analizo la captura (como con el DOM de BChile Auth0) y recién ahí se escribe el prompt de build dirigido para Fable.

**Criterio Fase 0**: tenemos el dominio de login real, los selectores, el patrón del JWT y los endpoints de API actuales — con evidencia, no suposición.

### ✅ Discovery RESULTADOS (2026-06-13, captura PII-safe de la cuenta del fundador)

**Login** — entry `https://www.bci.cl/corporativo/banco-en-linea/personas` (widget de login embebido; el candidato `bciimg.bci.cl/sitioseguro/login/...` redirige ahí). Form:
- RUT visible: **`#rut_aux`** (`name=rut_aux`, placeholder "Ingresa tu RUT"). Los `#rut` + `#dig` son **hidden** que el JS del form rellena al escribir en `rut_aux` → el código viejo apuntaba a `input[name="rut"]`/`#rut` (los hidden) y por eso no llenaba nada.
- Clave: **`#clave`** (`name=clave`, type password).
- Hidden del form: `transaccion, grupo, serv(#input1), canal(#input2), touch`. Submit: `button[type=submit]` dentro del form de login (hay varios submits en la página — search/comentarios; targetear el del form que contiene `#clave`).
- App autenticada post-login: `www.bci.cl/personas`. Anti-fraude **Easy Solutions DetectCA** (`detectca.easysol.net`) presente → posible riesgo desde datacenter (como B-1 de BChile); verificar en prod.

**API interna** — base SIN cambios: `https://apilocal.bci.cl/bci-produccion/api-bci/bff-saldosyultimosmovimientoswebpersonas/v3.2`. JWT Bearer se intercepta del tráfico (la estrategia actual sirve). **Endpoints nuevos** (todos POST, `application/json`, con Bearer):

| Endpoint | Respuesta (shape verificado) |
|---|---|
| `cuentas-busquedas/por-rut` | `{cuentas: [{numero: str, tipo: str}]}` — **lista de cuentas** (reemplaza el `GET /cuentas` que usa el código viejo) |
| `cuentas-busquedas/por-numero-cuenta` | `{numero, tipo, estado, saldoContable: int, saldoDisponible: int, retenciones, lineaSobregiro{montoUtilizado,saldoDisponible}, lineaEmergencia{...}, ultimosChequesCobrados[]}` — **saldo** |
| `cuentas-movimientos/por-numero-cuenta` | `{movimientos: [{fechaMovimiento: str, idMovimiento: str, glosa: str, monto: str, serie: str, tipo: str, detalleMovimiento{...}}], ordenadoPor: str}` — **movimientos** |

Otros con Bearer (no esenciales): `ms-gestiondatoscliente-neg/v2.1/obtenerDatosCliente` (datos cliente), `ms-bciplus-orq/v1.9/usuarios|cashback`.

**Normalización** (mapear en `_to_canonical`): `idMovimiento` → `native_id` (idempotencia, como BChile); `monto` (str) → int; `tipo` (cargo/abono/débito/crédito) → signo; `fechaMovimiento` → date; `glosa` → `raw_description`.

### ✅ Test #1 + captura de bodies (2026-06-13) — login OK, bodies confirmados

**Login VERIFICADO en local**: `bci_fields_verified` (RUT `type()` en `#rut_aux` pobló los hidden `#rut`/`#dig`; clave `fill()` en `#clave`) → `_post_submit_flow` dio "Sesión iniciada correctamente". El 2FA no se disparó en ese intento.

**Lo que falló y el fix**: el scraper no extrajo datos porque (a) la captura del JWT estaba limitada al path del BFF de saldos, y (b) el heurístico de click al menú "Saldos y movimientos" no matchea el DOM nuevo (`bci_accounts_menu_not_found`). **Atajo robusto**: el dashboard dispara SOLO (sin navegar) `usuarios/<rut>`, `cashback/<rut>`, `obtenerDatosCliente` — todas con el JWT Bearer al host `apilocal.bci.cl`. → **Capturar el JWT de CUALQUIER request a `apilocal.bci.cl`** (no solo el BFF de saldos) y llamar los 3 endpoints **directo, sin navegar menú** (eliminar `_navigate_to_accounts_menu` como dependencia).

**Bodies CONFIRMADOS** (captura PII-safe del `request.post_data` real):
| Endpoint | Body exacto |
|---|---|
| `cuentas-busquedas/por-rut` | `{"rut": "<rut>-<dv>"}` — RUT **sin puntos**, con guion-dv (ej. `"22141522-1"`). NO `{rut,dig}`. |
| `cuentas-busquedas/por-numero-cuenta` (saldo) | `{"cuentaNumero": "<numero>"}` — key **`cuentaNumero`**, SIN `tipo`. |
| `cuentas-movimientos/por-numero-cuenta` (movs) | `{"numeroCuenta": "<numero>"}` — key **`numeroCuenta`** (≠ la de saldo), SIN `tipo`. |
| `obtenerDatosCliente` | body vacío (no esencial). |

⚠️ Trampas: las dos APIs de cuenta usan **nombres de clave distintos** para el número (`cuentaNumero` vs `numeroCuenta`); ninguna lleva `tipo` (el código viejo mandaba `{numero,tipo}` → incorrecto). El `numero` sale de la respuesta de `por-rut` (`{cuentas:[{numero,tipo}]}`).

### ✅ Fix dirigido APLICADO (2026-06-13, post-test #1) — login intacto

Cambios quirúrgicos en `bci_scraper.py` (NO se tocó el login que ya andaba). Gates verdes (ruff + mypy + tests; `test_bci_source.py` 32→35). `bci` sigue **`pending`** hasta el sync real en prod (test #2).

1. **Captura del JWT por HOST** (no por path del BFF): `_is_jwt_request(url, headers)` devuelve el Bearer de **cualquier** request a `apilocal.bci.cl`. El dashboard lo dispara solo desde `usuarios/<rut>`, `cashback/<rut>`, `obtenerDatosCliente` → el token aparece sin depender del menú. (El listener `capture_request` ya filtraba por host desde `69a03e3`; ahora está extraído y pineado por test.)
2. **Sin dependencia del menú**: `fetch()` espera el JWT con `_await_jwt` (~15s de poll a que el dashboard lo emita). `_navigate_to_accounts_menu` queda como **nudge best-effort** (traga cualquier excepción; `bci_accounts_menu_not_found` ya no es un warning ni rompe el flujo). El error de "no se capturó el JWT" ya no culpa a la navegación.
3. **Bodies CONFIRMADOS** (reemplazan los del build inicial):
   - `por-rut` → `{"rut": "<rut>-<dv>"}` vía `_rut_with_dv` (limpia puntos/guiones, reinserta guion-dv como BChile; ej. `"22141522-1"`). Ya **no** `{rut,dig}`.
   - `por-numero-cuenta` (saldo) → `{"cuentaNumero": "<numero>"}`. Sin `tipo`.
   - `cuentas-movimientos` (movs) → `{"numeroCuenta": "<numero>"}` (key ≠ la del saldo). Sin `tipo`.
4. **Flujo**: login → `_await_jwt` → `por-rut` → por cada cuenta: saldo (`cuentaNumero`) + movs (`numeroCuenta`) → normalizar. Se ignora `tipo` de la cuenta (los bodies confirmados no lo usan).
5. **Capture-and-replay = fallback/refuerzo**: el listener sigue capturando y logueando PII-safe el `post_data` real (`por-rut`, movs). El body que se **envía** es el CONFIRMADO; la forma capturada de `por-rut` solo se reintenta si el confirmado no devuelve cuentas.

**Pendiente**: test #2 (mismo comando, headful) → debería listar cuentas + movimientos. Si entra, sync real end-to-end en prod → activar `bci`.

### ⚠️ Test #2 (2026-06-13) — login OK, JWT NO se captura + instrumentación de diagnóstico

**Resultado**: login end-to-end OK (`bci_fields_verified` + "Sesión iniciada correctamente"). Falló la captura del JWT: `_await_jwt` hizo timeout (15s) sin interceptar **ninguna** request Bearer a `apilocal.bci.cl`, y el nudge no encontró menú (`bci_dashboard_nudge_no_menu`). **El supuesto "el dashboard dispara apilocal solo, sin navegar" resultó falso**: la home `www.bci.cl/personas` no pega `apilocal` hasta navegar al view de cuentas/movimientos, y el nudge era ciego al DOM real (solo top frame, solo innerText). **Peor**: el timeout hacía `raise` sin captura debug → se gastó un intento de cuenta real (lockout doctrinal) sin aprender nada.

**Fix (commit siguiente, solo `bci_scraper.py` + tests; login y bodies intactos; `bci` sigue `pending`; todo gated tras `scraper_debug_capture`, PII-safe §20)** — el próximo test es de **máxima información**:

1. **Censo de red** (`_census_entry` + listener): por cada request a `*.bci.cl`, resumen PII-safe deduplicado `{host, seg(1er path, dígitos redactados), método, has_auth, auth_scheme}` (`[opaque]` si el scheme no parece esquema → nunca un token crudo). Se loguea `bci_network_census` en éxito y en timeout. Objetivo: saber si `apilocal` se llama, desde qué host y con qué auth.
2. **Sonda de token** (`_probe_tokens`, en el timeout antes del raise): recorre `page.frames`, enumera keys de local/sessionStorage y testea **en JS** si el valor es JWT-shaped (`^[\w-]+\.[\w-]+\.[\w-]+$`) → vuelve solo `key→bool` (el valor jamás cruza a Python); `context.cookies()` → nombres+dominios de cookies bci.cl. `bci_token_probe_storage` / `_cookies`. Objetivo: si el token vive en storage/cookie, el fix real lo lee directo sin depender de una request.
3. **Captura DOM + frames** (`_emit_jwt_timeout_diagnostics`): `_capture_debug(page, "jwt_timeout", pii_safe=True)` + URLs de `page.frames` (sin query, RUT/dígitos redactados vía `_safe_url`). `_scrub_pii` endurecido `\d{7,10}`→`\d{6,}` (DOM autenticado = más PII). Objetivo: ver el menú real y si el view de cuentas es un iframe.
4. **Nudge mejorado + ventana**: `_navigate_to_accounts_menu` itera **todos** los frames, matchea innerText/aria-label/title + substring de href, candidatos ampliados (`cartola`, `cartolas`, `mis productos`, `productos`, `cuenta corriente`, `movimientos`). `_await_jwt` sube ~15s→~30s (`jwt_wait_sec`) y re-corre el nudge **una vez** a mitad de la espera. Solo clicks de navegación, nunca submit.

Tests: `test_bci_source.py` 35→45 (censo PII-safe + opaque guard, cookie/storage no filtran valores, `_safe_url`, nudge itera frames y traga excepciones, `_await_jwt` timeout → diagnóstico + re-nudge una vez). Gates verdes.

**Pendiente**: **test #3** (mismo comando, headful, con `SCRAPER_DEBUG_CAPTURE=true`) → leer `bci_network_census` + `bci_token_probe_*` + la captura `jwt_timeout` para decidir el fix real (¿token en storage/cookie? ¿qué click dispara `apilocal`? ¿iframe?). Recién ahí, sync real → activar `bci`.

---

### ✅ Test #3 (2026-06-13) — ROOT CAUSE: el JWT llega en `bearer` minúscula

La instrumentación pagó: el diagnóstico apuntó al bug exacto en una corrida (el fundador navegó manualmente por Movimientos y Cartola para forzar el tráfico).

**`bci_network_census`** — la línea de oro:
```
{'host': 'apilocal.bci.cl', 'seg': 'bci-produccion', 'method': 'GET',  'has_auth': True, 'auth_scheme': 'bearer'}
{'host': 'apilocal.bci.cl', 'seg': 'bci-produccion', 'method': 'POST', 'has_auth': True, 'auth_scheme': 'bearer'}
```
`apilocal.bci.cl` **se llamó** (GET + POST) con `Authorization` presente y esquema **`bearer` en MINÚSCULA**. Pero `_is_jwt_request` matcheaba `auth.startswith("Bearer ")` (B mayúscula) → `"bearer eyJ…".startswith("Bearer ")` = `False`. **El token estuvo en cada request a apilocal; lo dejábamos pasar por un check case-sensitive.** El frontend de BCI manda el esquema en minúscula (común en JS: `headers: {Authorization: 'bearer ' + token}`).

**Las otras sondas cerraron los caminos alternativos:**
- **Storage**: todas las keys `looks_like_jwt: False` → el token **NO** vive en local/sessionStorage. Interceptar del request header (lo que ya hace el código) es el camino correcto, no leer storage.
- **`bci_body_captured`**: `por-rut` → `{"rut":"[rut]"}` y `cuentas-movimientos/por-numero-cuenta` → `{"numeroCuenta":"[digits]"}` aparecieron en vivo → endpoints y bodies confirmados (test #1) correctos, y el frontend realmente los pega.
- **`bci_frames`**: la app autenticada es un portal **JSF** (`www.bci.cl/cl/bci/aplicaciones/contenido.jsf` + `.../cartola/cuenta/cartolaCuenta.jsf`), **no** `www.bci.cl/personas`. El nudge clickeó OK (`bci_dashboard_nudge_clicked` ×2). Cookies de sesión: `JSESSIONID`, `X-CSRF-TOKEN`, `persist`, `userID`, `banca_cliente` (el JWT no está acá; va dinámico en el header).
- **Cookies/host del anti-fraude**: `detectca.easysol.net` no apareció en el censo de esta corrida (sigue siendo el riesgo tipo B-1 a vigilar en datacenter; en local no bloqueó).

**Fix aplicado** (solo `bci_scraper.py` + 1 test; quirúrgico; `bci` sigue `pending`): `_is_jwt_request` ahora matchea el esquema **case-insensitive** (`auth[:7].lower() == "bearer "`, devuelve el token con `.strip() or None`). Comentarios del módulo (ESTRATEGIA/FLUJO + inline en `fetch`) corregidos: el JWT lo dispara la **navegación** a Saldos/Movimientos, NO la home (test #2/#3); el esquema es minúscula. Test `test_jwt_capture_case_insensitive_bearer` (minúscula/mayúscula/mixta capturan, `bearer ` vacío y otros esquemas → None). Gates: ruff ✅ · mypy ✅ · pytest ✅ **696 passed, 1 skipped** (`test_bci_source.py` 45→46).

**Pendiente para activar `bci`**: (1) **test #4** local (mismo comando) → con la captura del `bearer` arreglada debería **listar cuentas + movimientos + saldo** end-to-end; (2) **sync real en prod** (worker con Chrome real) → vigilar `DetectCA easysol` desde datacenter (riesgo tipo B-1); (3) recién ahí activar `bci` en `SUPPORTED_BANKS` → **dos bancos a la vez**.

### ✅ Test #4 (2026-06-13) — JWT capturado, falla la API por CORS (`Failed to fetch`)

El fix del `bearer` minúscula funcionó: `bci_jwt_captured` ✅, el nudge disparó `apilocal` hands-off, el token se capturó. Ahora falla **en la llamada a la API**: `_list_accounts` → `_api_post(por-rut)` → el `fetch()` in-page lanza `TypeError: Failed to fetch` (stack vía el wrapper Dynatrace `dtAWF/fetch` en `contenido.jsf` — ruido; la falla real es de red).

**ROOT CAUSE**: `Failed to fetch` en un fetch cross-origin (`www.bci.cl` → `apilocal.bci.cl`) = **bloqueo CORS a nivel red**, no un 4xx. El endpoint anda (el frontend pegó a `por-rut` y capturamos su body). Causa: `_api_post` usaba `credentials: "include"`, que fuerza el **modo CORS-con-credenciales**; `apilocal` autentica por **Bearer (no cookies)** y su respuesta CORS (ACAO `*` sin `Allow-Credentials: true`) no satisface ese modo → el browser bloquea **antes** de ver el status. El frontend usa `credentials: omit`.

**Fix aplicado** (solo `bci_scraper.py` + tests; login/bodies intactos; `bci` sigue `pending`; PII-safe §20):
1. **`_api_post` espeja el frontend**: `credentials: "include"` → **`"omit"`** + `Authorization: \`Bearer ${jwt}\`` → **`\`bearer ${jwt}\``** (minúscula, como el censo). Accept/Content-Type/body/referrer intactos. Docstring documenta el porqué + el **fallback** `page.context.request.post()` (APIRequestContext, no sujeto a CORS, pero riesgo de fingerprint anti-bot con cf_clearance/__cf_bm + DetectCA → el in-page va primero para conservar el path de red de Chrome real que pasa el WAF; **no implementado**).
2. **Instrumentación (gated, PII-safe)**: el listener ahora loguea `bci_request_headers` (headers del request del frontend a los `BODY_CAPTURE_PATHS`) vía `_scrub_headers` — `authorization` → solo el esquema + `[redacted]`, `cookie` → `[redacted]`, RUTs/dígitos redactados, resto visible. Si `Failed to fetch` persiste pese al fix, replicamos los headers exactos del frontend.

Tests: `test_bci_source.py` 46→49 (`_api_post` pina `credentials:"omit"` + `` `bearer ${jwt}` ``; `_scrub_headers` no filtra authorization/cookie/dígitos y deja visible content-type/origin). Gates: ruff ✅ · mypy ✅ · pytest ✅ **699 passed, 1 skipped**.

**Pendiente**: **test #5** local (mismo comando) → con `credentials:omit` + `bearer` minúscula, `por-rut` debería responder y listar cuentas → saldo + movimientos end-to-end. Si aún diera `Failed to fetch`, leer `bci_request_headers` para replicar la forma exacta. Después: sync prod → activar `bci`.

---

## FASE 1+ — Rework (build, tras la captura)

Estructura esperada (a confirmar con el discovery):
1. **Login en el portal nuevo**: URL + selectores reales. Aplicar las **lecciones de BChile**: `fill()` vs `type()` según el campo (verificar si BCI tiene directivas tipo Angular que requieran keystrokes); **verificación post-fill** (`_verify_login_fields`) reusable para no mandar credenciales mal tecleadas; `AuthenticationError` solo con mensaje real del banco (no por ambigüedad).
2. **Captura de JWT + API**: confirmar `BCI_API_BASE` nuevo; el patrón de interceptar el Bearer del tráfico se conserva si sigue siendo JWT.
3. **Normalización**: `_to_canonical` ya maneja varias formas de glosa/fecha/monto; ajustar a la respuesta real.
4. **R-2**: renombrar a `BCIScraperSource`/`bci_scraper.py` + actualizar `SUPPORTED_BANKS`, `build_all_sources`, routing rules, tests.
5. **Activar `bci` en `SUPPORTED_BANKS`** (hoy `pending`) recién cuando el sync real funcione end-to-end en prod.

### ✅ Rework CONSTRUIDO (2026-06-13, commit `69a03e3`)

`bci_scraper.py` (ex `bci_direct.py` — **R-2 cerrado**: `BCIScraperSource`). Gated verde (ruff + mypy + 682 tests, 32 nuevos en `tests/unit/test_bci_source.py`). **NO activa `bci`** (sigue `pending`).

- **Login**: entry `www.bci.cl/corporativo/banco-en-linea/personas`. RUT con `type()` en `#rut_aux`; clave con `fill()` en `#clave`. Verificación post-fill extendida: relee `#rut_aux`/`#clave` Y confirma que los hidden `#rut`/`#dig` se poblaron (prueba que el `type()` disparó el JS del form) → `FieldFillError` (recoverable, no auth) si no. Submit acotado al form que contiene `#clave`.
- **`_post_submit_flow`** (portado de BChile): éxito = dejar el marcador de URL `corporativo/banco-en-linea` **o** JWT capturado; clave mala SOLO con el mensaje del banco; ambigüedad → asume 2FA + captura `pii_safe` (jamás `AuthenticationError`); form pegado → `RecoverableIngestionError` ANTIBOT (flag tipo B-1 del DetectCA easysol).
- **API**: JWT Bearer interceptado del host `apilocal.bci.cl`; `cuentas-busquedas/por-rut` (lista), `por-numero-cuenta` (saldo `saldoContable`), `cuentas-movimientos/por-numero-cuenta` (movs). **Body capture-and-replay**: el listener captura el `post_data` real del frontend (`por-rut`, movimientos) al navegar a "Saldos y movimientos", lo loguea PII-safe y replica la forma exacta; fallbacks `{rut,dig}` / `{numero,tipo}`.
- **Normalización**: `idMovimiento`→`native_id` (idempotencia), `monto` str→int (formato chileno), `tipo`→signo, `fechaMovimiento`→date, `glosa`→`raw_description`; `since` filtra.

**Pendiente (discovery de runtime — gating de la activación)**: el discovery fijó login + endpoints + shapes, pero NO el post-submit completo ni los bodies. El primer test manual con la cuenta BCI real confirma/refina, vía captura `pii_safe`: (1) la señal post-submit exacta; (2) las keywords 2FA del portal nuevo; (3) los bodies de `por-rut`/movimientos; (4) el formato real de `monto`/`tipo`/`fecha`. Recién con un sync real end-to-end en prod → activar `bci` → **dos bancos a la vez**.

---

## Invariantes (doctrina + lecciones BChile)

- **§12 `AuthenticationError` NO dispara failover** — y NO se lanza por ambigüedad (mandaría la cuenta a un estado de clave-mala falso). Solo con el mensaje real del banco.
- **2FA**: keywords del portal nuevo; la ambigüedad jamás se castiga como clave mala (lección BChile `_post_submit_flow`).
- **No martillar el banco real** en desarrollo (riesgo de bloqueo de clave). Capturas debug `pii_safe` (solo HTML scrubeado, sin screenshot — §20). Reusar el bucket `scraper-debug`.
- **El ciclo `needs_reconnection`** (migración 013) ya aplica a BCI sin cambios — el hard-stop anti-bloqueo es transversal.
- **Worker con Chrome real** (`channel="chrome"`) ya está — beneficia a BCI igual que a BChile.

---

## Orden de trabajo

1. **Confirmar cuenta BCI** disponible (fundador/cofundador).
2. **Fase 0 discovery** (captura real) → yo analizo.
3. **Prompt de build dirigido para Fable** (escrito con la evidencia de la captura, no antes).
4. Verificación en prod (sync real BCI) → activar `bci` → **dos bancos a la vez**.
