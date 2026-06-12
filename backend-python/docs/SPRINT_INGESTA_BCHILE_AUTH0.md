# SPRINT — Ingesta BChile: hardening post-Auth0 + ciclo de credenciales

> **Estado**: listo para ejecutar. Causa raíz del bloqueador del MVP ya diagnosticada y cerrada (2026-06-12).
> **Objetivo**: dejar el sync de BChile funcionando de punta a punta en producción para testers reales, y blindar el camino para que esta clase de fallo nunca vuelva a ser invisible.
> **No es un fix puntual — es el upgrade del subsistema de ingesta.**

---

## 0. Causa raíz (cerrada, con evidencia)

El mensaje "Credenciales rechazadas por el banco" colapsaba **tres** causas distintas. Las tres están resueltas o entendidas:

1. **B-7 — falso positivo de URL post-Auth0** (✅ ya corregido y desplegado, commits `f822901`/`6fdae84`/`3145a0c`/`1254053`). BChile migró el login a `login.portales.bancochile.cl` (Auth0). El check `if "/login" in page.url` matcheaba el nombre del dominio nuevo. Reemplazado por poll positivo de URL. Confirmado en prod: el scraper llega al form y lo envía.

2. **B-1 — anti-bot Incapsula desde datacenter** (✅ obsoleto). El scraper carga, llena y **envía** el form desde la IP de Railway, y el banco responde con su página de error. No hay challenge. El bloqueo de datacenter dejó de aplicar con la migración a Auth0.

3. **🎯 CAUSA RAÍZ DEL BLOQUEADOR ACTUAL — carácter `$` mal tecleado en producción.**
   - La clave real del fundador termina en `$` (patrón `Xxx_999$`).
   - La app la guarda **correctamente**: el descifrado directo de `bank_accounts.encrypted_pass` confirma el `$` intacto. El cifrado está sano.
   - Pero `_fill_password` usa `await el.type(password, delay=45)`. En el worker de prod el browser cae a **Chromium bundled headless** (`channel="chromium-bundled"`, porque no hay Chrome real instalado), y ahí el `$` (que se teclea como `Shift+4`) se manda mal al input del banco → el banco recibe una clave incorrecta → "Los datos ingresados no son correctos".
   - **Local funciona** porque la máquina del fundador tiene Chrome instalado → cae a `channel="chrome"` (Chrome real) que teclea el `$` bien.

### Cadena de evidencia
- Test local headless con la clave correcta → **extrae movimientos OK**. Esto exonera al scraper, a headless en sí, y a la directiva Angular.
- Test local headless con la clave entre comillas en PowerShell (que mangla el `$`) → **falla igual que prod**. Confirma que el `$` mal transportado es la causa.
- Reconexión real en la app (disconnect 06:19 → connect 06:20 → sync fail 06:21, audit_log) con la misma clave que funciona local → **falla en prod**. Descarta clave desactualizada.
- Descifrado de la clave guardada → `$` presente en posición final. Cifrado correcto.

---

## 1. Alcance del sprint

Cuatro fases. La **Fase A es la que desbloquea el MVP** y debe ir primero. El resto endurece el subsistema.

### FASE A — Fix del input + red de seguridad permanente (desbloquea MVP)

**A1. `fill()` para la clave (primario).**
- En `backend-python/src/sky/ingestion/sources/bchile_scraper.py`, método `_fill_password`: cambiar `await el.type(password, delay=45)` por `await el.fill(password)`.
- **Importante / no confundir**: el campo password **no** tiene la directiva `delete-zero-left` (esa es exclusiva del RUT). Por eso `fill()` es seguro aquí — setea el valor por DOM y dispara `input`/`change`, que el `ngModel` de Angular escucha. El `$` entra perfecto sin pasar por el teclado.
- **`_fill_rut` SE QUEDA con `type()`** — el RUT sí tiene `delete-zero-left=""` que requiere keystrokes reales. No tocar. (Esta distinción fue la confusión del commit `6fdae84`, que cambió ambos a `fill()` y rompió el RUT.)

**A2. Verificación post-fill (keystone — la pieza más importante del sprint).**
- En `_login`, después de llenar RUT y clave y **antes** de hacer click en submit: leer de vuelta `input.value` de ambos campos vía `page.evaluate` y comparar con el valor que se quiso escribir.
- Si no coinciden → lanzar un error tipado nuevo `FieldFillError` (recoverable, NO auth) con detalle preciso del campo, **sin loguear el valor de la clave** (solo longitudes / un flag de match). Ej: `logger.warning("bchile_field_mismatch", field="password", expected_len=8, got_len=7)`.
- Esto convierte el "datos no son correctos" opaco en un diagnóstico exacto, para siempre. Es la red que habría cazado este bug en el primer intento.

**A3. Chrome real en el worker (defensa en profundidad).**
- El worker en Railway hoy instala Chromium bundled (build command fuera del repo Dockerfile — confirmado: el `Dockerfile` versionado solo construye la API). Cambiar el build del servicio `sky-worker-python` para instalar el Chrome de canal: `playwright install --with-deps chrome` (instala el Chrome branded), de modo que `browser_pool.start()` use `channel="chrome"` en prod = misma huella y comportamiento que el local que funciona.
- Verificar en logs de arranque del worker que diga `channel="chrome"` y no `channel="chromium-bundled"`.

**A4. Repro local para validar sin tocar prod ni gastar intentos al banco.**
- Agregar al test/manual un modo que **fuerce Chromium bundled** (ej. `channel=None` o flag `--force-bundled` en `BrowserPool`) para reproducir el bug del `$` localmente. Criterio: con bundled + clave con `$` → falla ANTES del fix, pasa DESPUÉS.

**Criterio de aceptación Fase A**: con `fill()` + post-fill verify, un sync de prueba en local-bundled con una clave que contiene `$` pasa el login. Idealmente, un sync real en prod (con la cuenta del fundador, un solo intento) entra y trae movimientos → cierra B-7/B-1/causa-raíz en producción de verdad.

#### ✅ Estado de ejecución Fase A (2026-06-12) — código completo, pendiente verificación en prod

Commits: `b3f5f26` (A1+A2) · `10213c2` (A3+A4). Gates verdes: ruff + mypy + 506 tests (13 nuevos).

- **A1** ✅ `_fill_password` usa `fill()`; `_fill_rut` se queda con `type()` (pineado por test de regresión anti-6fdae84).
- **A2** ✅ `_verify_login_fields` lee `input.value` de ambos campos antes del submit; mismatch → `FieldFillError` (recoverable, no auth, solo longitudes — jamás el valor) + log `bchile_field_mismatch`. `fetch()` lo propaga sin re-envolver y `_user_message_for_failure` lo mapea a "problema técnico, no es tu clave". RUT se compara normalizado (el sitio reformatea puntos/guion; `delete-zero-left` quita ceros).
- **A3** ✅ en repo: `docker/worker.Dockerfile` instala Chrome real (`playwright install chrome --with-deps`) + chromium de fallback; el fallback a bundled ahora loguea **warning**. Nuevo setting `browser_channel` (palanca §14).
  ⚠️ **Acción manual Railway**: si `sky-worker-python` NO buildea con `docker/worker.Dockerfile` (build command propio en el dashboard), agregar ahí `playwright install chrome --with-deps`.
- **A4** ✅ `BrowserPool(channel="bundled")` + flag `--force-bundled` en `scripts/test_bchile_scraper.py`. Test de integración lanza Chromium bundled real y verifica que `fill()` preserva `Abc_123$` exacto (sin tocar al banco). El "falla ANTES con type()" no se pinea en test: es específico de bundled-headless-Linux; la evidencia quedó en §0.

**Verificación pendiente (requiere al fundador — un solo intento cada paso):**
1. (Opcional, local) `python scripts/test_bchile_scraper.py RUT CLAVE --headless --force-bundled` → debe entrar y traer movimientos. Reproduce exactamente el entorno de prod.
2. Deploy del worker a Railway → en logs de arranque debe decir `browser_pool_started ... channel="chrome"` (si dice `chromium-bundled` + warning, aplicar la acción manual de A3 — el fix A1/A2 igual cubre).
3. Sync real de la cuenta del fundador en prod → entra, trae movimientos, balance correcto. **Esto cierra el MVP.**

---

### FASE B — Ciclo de vida de credenciales + seguridad anti-bloqueo

El subsistema hoy no distingue "clave incorrecta" de otros errores, y "Actualizar" reusa la clave guardada — un usuario con clave mala nunca se arregla apretando Actualizar, y cada intento acerca al bloqueo del banco.

**B1. Estado `needs_reconnection`** distinto de `error` genérico. Cuando el banco responde "datos no son correctos" (clave realmente incorrecta, no un mismatch de fill ya cubierto por A2) → la cuenta entra a este estado. Requiere migración si `bank_accounts.status` tiene CHECK constraint (verificar con `pg_get_constraintdef`; ver [[project_supabase_node_era_artifacts]]).

**B2. Hard-stop de reintentos** en `needs_reconnection`: bloquear sync manual **y** cron hasta que haya una reconexión exitosa. Protege la clave real del bloqueo del banco (promesa central de Sky: confianza). El cron ya excluye por `consecutive_errors >= 5`; agregar exclusión explícita por status.

**B3. UX honesta** (`frontend/src/components/BankConnect.jsx`):
- En `needs_reconnection`: mostrar "Tu clave cambió o el banco la rechazó — vuelve a ingresarla", **deshabilitar "Actualizar"** y ofrecer **"Reconectar"** como acción primaria.
- Hoy ambos botones llevan al mismo callejón sin salida.

**Criterio**: una cuenta con clave rechazada nunca se reintenta sola ni por botón; el usuario es dirigido a reconectar; imposible llegar al 3er fallo por acción automática.

---

### FASE C — Observabilidad (que no haya que cavar a mano nunca más)

Este diagnóstico requirió acceso directo a la DB y descifrar credenciales. Eso no debe ser necesario.

**C1. Taxonomía de errores de sync** en `sky.core.errors` / `contracts`: `wrong_credentials` · `needs_2fa` · `bank_temporary` · `antibot` · `field_fill_failed`. Cada uno con mensaje de usuario y acción propios.

**C2. Surfacing del error real (sanitizado)** al usuario: el `detail` que hoy queda enterrado en `audit_log` debe manejar el mensaje del frontend (ej. "El banco dice: revisa tu clave") y un panel/endpoint mínimo de operador (service-role) para ver estado + último error sin scripts ad-hoc.

**C3. Capturas debug a storage durable** (bucket Supabase con expiración + PII-aware), gated por flag, en vez del `/tmp` efímero del contenedor.

**Criterio**: ante un fallo de sync, la causa real es visible desde la app/panel sin acceso directo a la DB.

---

### FASE D — Higiene operativa

**D1. Apagar `appealing-benevolence`** (Node legacy, B-6) en Railway — sigue Online. (Hoy no duplica datos: 184/184 external_id en formato Python, pero es deuda viva y riesgo latente.)

**D2. Limpieza de estado** de las 3 cuentas bchile (1 del fundador + 2 disconnected viejas).

**D3. Sincronizar docs**: `CLAUDE.md` + `docs/estado-del-arte/08_ESTADO_Y_DEUDA.md` — B-7 cerrado en prod, B-1 obsoleto, causa raíz `$` documentada, nuevo ciclo de credenciales. Orden de actualización per CLAUDE.md.

---

## 2. Archivos involucrados (mapa para el ejecutor)

| Archivo | Cambio |
|---|---|
| `backend-python/src/sky/ingestion/sources/bchile_scraper.py` | A1 (`fill()` password), A2 (post-fill verify) |
| `backend-python/src/sky/ingestion/browser_pool.py` | A3 (channel chrome), A4 (forzar bundled para repro) |
| build del servicio `sky-worker-python` (Railway) | A3 (`playwright install --with-deps chrome`) |
| `backend-python/src/sky/core/errors.py` · `ingestion/contracts.py` | A2 (`FieldFillError`), C1 (taxonomía) |
| `backend-python/src/sky/worker/banking_sync.py` | B1 (estado), B2 (hard-stop), C2 (surface detail) |
| `backend-python/src/sky/worker/jobs/scheduled.py` | B2 (excluir `needs_reconnection` del cron) |
| `backend-python/src/sky/api/routers/banking.py` | B2 (bloquear sync manual si needs_reconnection), C2 |
| `frontend/src/components/BankConnect.jsx` | B3 (UX Actualizar vs Reconectar, mensaje real) |
| `backend-python/migrations/*` | B1 (nuevo status, si hay CHECK constraint) |
| `CLAUDE.md` · `docs/estado-del-arte/08_*.md` | D3 |

---

## 3. Seguridad / riesgos

- **Bloqueo de la cuenta del banco**: el banco avisa "al tercer intento fallido tu clave será bloqueada". El skip-por-5-errores del cron protege hoy. Durante el sprint, **no reintentar a ciegas**; cada validación contra el banco real cuenta. Un login exitoso resetea el contador del banco.
- **PII**: la verificación post-fill (A2) NUNCA debe loguear el valor de RUT/clave — solo longitudes / flags de match. Las capturas debug (C3) deben ser PII-aware (el form lleva el RUT en pantalla).
- **Doctrina**: §15 (secrets solo backend), §16 (cifrado), §20 (errores sanitizados). Respetar.

---

## 4. Plan de verificación (gate por cambio, CLAUDE.md)

1. `ruff check src/sky/ tests/` + `mypy src/sky/` exit 0.
2. `pytest tests/ -v` — agregar tests de regresión: post-fill verify detecta mismatch; clave con `$` se llena correcta con `fill()`.
3. Repro local (A4): bundled + clave-con-`$` falla antes, pasa después.
4. Smoke del scraper local (headful y bundled).
5. **Validación end-to-end en prod**: un sync real de la cuenta del fundador entra, trae movimientos, balance correcto. Cierra el MVP.
6. Onboarding: cada tester reconecta con su clave vigente; el sync entra.

---

## 5. Definición de "MVP listo para testers"

- [ ] Un sync real de BChile en producción entra y trae movimientos (Fase A).
- [ ] Una clave incorrecta lleva a `needs_reconnection` con UX clara, sin riesgo de bloqueo (Fase B).
- [ ] El error real es visible sin cavar en la DB (Fase C).
- [ ] Node legacy apagado, docs al día (Fase D).
