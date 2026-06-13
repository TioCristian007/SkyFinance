# SPRINT — Rework scraper BCI (B-2): segundo banco operativo

> **Estado**: PREP / discovery-first (2026-06-13). El portal BCI cambió de dominio
> (`portalpersonas.bci.cl` ya no resuelve, NXDOMAIN). Objetivo: BChile + **BCI**
> sincronizando a la vez — SkyFinanzas con dos bancos reales.
> **Disciplina aprendida de BChile**: NO escribir el fix a ciegas. El portal migró
> (como BChile→Auth0); primero **capturar el portal real**, después fix dirigido.

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

---

## FASE 1+ — Rework (build, tras la captura)

Estructura esperada (a confirmar con el discovery):
1. **Login en el portal nuevo**: URL + selectores reales. Aplicar las **lecciones de BChile**: `fill()` vs `type()` según el campo (verificar si BCI tiene directivas tipo Angular que requieran keystrokes); **verificación post-fill** (`_verify_login_fields`) reusable para no mandar credenciales mal tecleadas; `AuthenticationError` solo con mensaje real del banco (no por ambigüedad).
2. **Captura de JWT + API**: confirmar `BCI_API_BASE` nuevo; el patrón de interceptar el Bearer del tráfico se conserva si sigue siendo JWT.
3. **Normalización**: `_to_canonical` ya maneja varias formas de glosa/fecha/monto; ajustar a la respuesta real.
4. **R-2**: renombrar a `BCIScraperSource`/`bci_scraper.py` + actualizar `SUPPORTED_BANKS`, `build_all_sources`, routing rules, tests.
5. **Activar `bci` en `SUPPORTED_BANKS`** (hoy `pending`) recién cuando el sync real funcione end-to-end en prod.

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
