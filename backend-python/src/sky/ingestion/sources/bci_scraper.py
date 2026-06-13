"""
sky.ingestion.sources.bci_scraper — Scraper BCI (Playwright + JWT Bearer).

ESTRATEGIA:
    BCI expone APIs REST internas en apilocal.bci.cl (BFF v3.2) autenticadas
    con JWT Bearer. El scraper hace login en el portal web; el portal autenticado
    (app JSF en www.bci.cl/cl/bci/aplicaciones/) dispara las requests a
    apilocal.bci.cl con el JWT al NAVEGAR a Saldos/Movimientos — NO desde la home
    (test #2/#3). El scraper navega (nudge) e intercepta ese Bearer del tráfico
    de red (esquema en MINÚSCULA, `bearer …` — test #3), luego llama directamente
    a la API con los bodies CONFIRMADOS (test #1).

FLUJO:
    1. goto portal BCI (www.bci.cl/corporativo/banco-en-linea/personas)
    2. type RUT en #rut_aux (el form parte en los hidden #rut/#dig) + fill #clave
    3. verificación post-fill (incl. que los hidden #rut/#dig se poblaron)
    4. submit DENTRO del form de #clave → resolver post-submit (error/2FA/éxito)
    5. nudge a Saldos/Movimientos (la home no pega apilocal — test #2/#3) y
       esperar el JWT `bearer` que esa navegación dispara a apilocal.bci.cl
    6. API: POST cuentas-busquedas/por-rut          body {"rut":"<rut>-<dv>"}
    7. API: POST cuentas-busquedas/por-numero-cuenta body {"cuentaNumero":"<n>"}
    8. API: POST cuentas-movimientos/por-numero-cuenta body {"numeroCuenta":"<n>"}
    9. Normalizar a CanonicalMovement con build_external_id (idMovimiento nativo)

DISCOVERY (2026-06-13, captura PII-safe de la cuenta del fundador):
    El portal migró de portalpersonas.bci.cl (NXDOMAIN) al widget embebido en
    www.bci.cl. La API interna (apilocal.bci.cl, BFF v3.2) NO cambió de base; lo
    que cambió fueron los endpoints (POST por-rut reemplaza el GET /cuentas) y el
    form de login. Ver backend-python/docs/SPRINT_BCI_SCRAPER_REWORK.md.

LECCIONES BCHILE APLICADAS (pineadas en prod, sprint 2026-06-12):
    · RUT con type() (el form parte el visible en hidden vía JS — necesita
      keystrokes); clave con fill() (type() mangla el '$' en Chromium headless).
    · Verificación post-fill: relee input.value antes del submit → FieldFillError
      (recoverable, NO auth) si no quedó lo que se quiso escribir.
    · La ambigüedad post-submit JAMÁS se castiga como AuthenticationError —
      mandaría la cuenta a needs_reconnection con la clave buena. Clave mala =
      SOLO con el mensaje del banco en pantalla.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import traceback
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import Page, Request

from sky.core.config import settings
from sky.core.logging import get_logger
from sky.ingestion.browser_pool import get_browser_pool
from sky.ingestion.contracts import (
    PROGRESS_2FA_WAIT_PREFIX,
    PROGRESS_LOGIN_OK,
    AccountBalance,
    AuthenticationError,
    BankCredentials,
    CanonicalMovement,
    DataSource,
    FieldFillError,
    IngestionCapabilities,
    IngestionResult,
    MovementSource,
    OAuthTokens,
    ProgressCallback,
    RecoverableIngestionError,
    SourceKind,
    TwoFactorTimeoutError,
    build_external_id,
)

logger = get_logger("bci_scraper")

BCI_BANK_URL = "https://www.bci.cl/corporativo/banco-en-linea/personas"
# Mientras la URL siga conteniendo este marcador, el login NO terminó: o hay
# error, o 2FA pendiente, o el form no avanzó. El éxito = la app autenticada
# (www.bci.cl/personas) que NO contiene este fragmento. BCI no cambia de dominio
# como BChile (Auth0) — la señal es el PATH, no el host.
LOGIN_URL_MARKER = "corporativo/banco-en-linea"
# Host de la API interna. El JWT Bearer se intercepta de CUALQUIER request a
# este host (más temprano que esperar la base v3.2 completa).
JWT_HOST = "apilocal.bci.cl"
BCI_API_BASE = (
    "https://apilocal.bci.cl/bci-produccion/api-bci"
    "/bff-saldosyultimosmovimientoswebpersonas/v3.2"
)

# Endpoints v3.2 (discovery 2026-06-13). Todos POST, Bearer, application/json.
# Bodies CONFIRMADOS en el test #1 (captura PII-safe del post_data real):
#   por-rut           → {"rut": "<rut>-<dv>"}    (sin puntos, guion-dv)
#   por-numero-cuenta → {"cuentaNumero": "<n>"}  (saldo; SIN tipo)
#   movimientos       → {"numeroCuenta": "<n>"}  (movs; key ≠ la del saldo)
ACCOUNTS_PATH = "cuentas-busquedas/por-rut"
BALANCE_PATH = "cuentas-busquedas/por-numero-cuenta"
MOVEMENTS_PATH = "cuentas-movimientos/por-numero-cuenta"
# Refuerzo (capture-and-replay): el listener captura el post_data real del
# frontend para estos paths y lo loguea PII-safe. Los bodies que se ENVÍAN son
# los CONFIRMADOS de arriba; la forma capturada de por-rut queda como fallback
# si el confirmado no devuelve cuentas.
BODY_CAPTURE_PATHS = (ACCOUNTS_PATH, MOVEMENTS_PATH)

# Headers que NO se replican en _api_post (test #5): forbidden header names que
# el browser gestiona/descarta igual, o los que seteamos nosotros. Lo que queda
# (x-apikey, canal, id-transaccion, x-bci-*…) es lo que el gateway BFF exige —
# faltaban y respondía 400 "Cabeceras incompletas".
HEADER_REPLAY_DENY = frozenset(
    {
        "host",
        "content-length",
        "connection",
        "cookie",
        "origin",
        "referer",
        "user-agent",
        "accept-encoding",
        "content-type",
        "accept",
        "authorization",
    }
)
HEADER_REPLAY_DENY_PREFIXES = ("sec-",)
# Nombres de header cuyo VALOR se redacta al loguear (un x-apikey del BFF no debe
# quedar en logs). La KEY siempre queda visible — es el diagnóstico.
SENSITIVE_HEADER_HINTS = ("apikey", "api-key", "token", "secret", "auth", "session", "csrf")

RUT_SELECTORS = [
    "#rut_aux",
    'input[name="rut_aux"]',
    'input[placeholder*="RUT"]',
    'input[placeholder*="rut"]',
]
# Hidden que el JS del form rellena al teclear en #rut_aux. Si quedan vacíos,
# el type() no disparó el JS → el banco recibiría un RUT vacío (FieldFillError).
RUT_HIDDEN_SELECTORS = ["#rut", "#dig"]
PASS_SELECTORS = [
    "#clave",
    'input[name="clave"]',
    'input[type="password"]',
]

# Detección POSITIVA de la pantalla 2FA (BCI Digital Pass). Frases compuestas a
# propósito: palabras sueltas como "app" o "aprueba" matchearían el marketing
# del propio sitio. Solo se evalúa mientras la URL siga en el login
# (_post_submit_flow). Cuando un tester real dispare el 2FA, la captura debug
# (pii_safe) trae el DOM para refinar esta lista.
TWO_FA_KEYWORDS = [
    "digital pass",
    "bci pass",
    "segundo factor",
    "clave dinámica",
    "clave dinamica",
    "código de verificación",
    "codigo de verificacion",
    "aprobar en tu app",
    "aprueba en tu app",
    "aprueba el ingreso",
    "autoriza el ingreso",
    "revisa tu app bci",
    "notificación a tu celular",
    "notificacion a tu celular",
]
LOGIN_ERROR_KEYWORDS = [
    "clave incorrecta",
    "datos incorrectos",
    "no son correctos",
    "rut inválido",
    "rut invalido",
    "bloqueada",
    "bloqueado",
    "suspendida",
    "sesión activa",
    "sesion activa",
    "intentos fallidos",
]
REJECTION_KEYWORDS = ["rechazad", "denegad", "cancelad"]

ACCOUNTS_MENU_TEXT = [
    "saldos y movimientos",
    "saldos y últimos movimientos",
    "saldos y ultimos movimientos",
    "mis cuentas",
    "cuentas",
    "saldos",
    "cartola",
    "cartolas",
    "mis productos",
    "productos",
    "cuenta corriente",
    "movimientos",
]

# Sonda PII-safe de storage: el test JWT-shaped se hace EN JS y solo vuelve
# {store: {key: bool}} — el valor NUNCA cruza a Python (doctrina §20).
STORAGE_PROBE_JS = """() => {
    const JWT_RE = /^[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+$/;
    const probe = (store) => {
        const out = {};
        try {
            for (let i = 0; i < store.length; i++) {
                const k = store.key(i);
                let v = "";
                try { v = store.getItem(k) || ""; } catch (e) { v = ""; }
                out[k] = JWT_RE.test(v);
            }
        } catch (e) {}
        return out;
    };
    return { local: probe(window.localStorage), session: probe(window.sessionStorage) };
}"""

# Nudge best-effort: clickea el acceso a cuentas/movimientos/cartola por texto
# (innerText / aria-label / title) o por substring de href. Solo navegación,
# nunca submit de forms. Devuelve true si clickeó algo.
MENU_CLICK_JS = """(keywords) => {
    const hitText = (s) => !!s && keywords.some((kw) => s === kw || s.startsWith(kw));
    const els = Array.from(document.querySelectorAll(
        "a, button, li, span, [role='menuitem'], [role='link']"
    ));
    for (const el of els) {
        const text = (el.innerText || el.textContent || "").trim().toLowerCase();
        const aria = ((el.getAttribute && el.getAttribute("aria-label")) || "").trim().toLowerCase();
        const title = ((el.getAttribute && el.getAttribute("title")) || "").trim().toLowerCase();
        const href = ((el.getAttribute && el.getAttribute("href")) || "").toLowerCase();
        if (hitText(text) || hitText(aria) || hitText(title)
            || keywords.some((kw) => href.includes(kw))) {
            try { el.click(); return true; } catch (e) {}
        }
    }
    return false;
}"""


class BCIScraperSource(DataSource):
    """DataSource para BCI vía Playwright + JWT REST (BFF v3.2)."""

    def __init__(
        self,
        two_fa_timeout_sec: int = 120,
        *,
        post_submit_grace_sec: float = 25.0,
        poll_interval_sec: float = 1.0,
        jwt_wait_sec: float = 30.0,
    ):
        self._timeout_sec = two_fa_timeout_sec
        # Cuánto esperar señales post-submit (error / 2FA / redirect) antes de
        # decidir por estructura. Override solo en tests (acelerar el loop).
        self._post_submit_grace_sec = post_submit_grace_sec
        self._poll_interval_sec = poll_interval_sec
        # Ventana para que el dashboard emita el JWT a apilocal.bci.cl. El
        # supuesto "lo dispara solo" resultó frágil (test #2) → se re-nudgea a
        # mitad. Override solo en tests.
        self._jwt_wait_sec = jwt_wait_sec

    @property
    def source_identifier(self) -> str:
        return "scraper.bci"

    @property
    def source_kind(self) -> SourceKind:
        return SourceKind.SCRAPER

    @property
    def supported_banks(self) -> list[str]:
        return ["bci"]

    def capabilities(self) -> IngestionCapabilities:
        return IngestionCapabilities(
            typical_latency_ms=60_000,
            estimated_failure_rate=0.15,
            supports_backfill=False,
            backfill_days=0,
            provides_credit_card=False,
        )

    async def fetch(
        self,
        bank_id: str,
        credentials: BankCredentials | OAuthTokens,
        *,
        on_progress: ProgressCallback | None = None,
        since: date | None = None,
    ) -> IngestionResult:
        if not isinstance(credentials, BankCredentials):
            raise ValueError("BCI requiere BankCredentials (RUT + password)")

        progress = on_progress or (lambda s: None)
        started_at = datetime.now()
        pool = get_browser_pool()

        async with pool.acquire() as context:
            page = await context.new_page()

            # Un solo listener captura el JWT Bearer Y los bodies POST que el
            # frontend dispara contra apilocal.bci.cl. Los bodies se loguean
            # PII-safe y se replican (capture-and-replay) para los endpoints
            # cuya forma exacta el discovery no fijó (por-rut, movimientos).
            jwt_token: list[str] = []
            captured_bodies: dict[str, str] = {}
            # Headers custom del frontend (x-apikey/canal/id-*…) para replicar en
            # _api_post: el gateway BFF los exige (400 "Cabeceras incompletas").
            # Se leen de la 1ª request a apilocal con all_headers (async) fuera
            # del listener sync — request.headers (sync) es parcial.
            captured_headers: dict[str, str] = {}
            apilocal_requests: list[Request] = []
            # Censo PII-safe de TODA request a *.bci.cl (dedup por host|seg|
            # método|scheme). Diagnóstico: saber si apilocal se llama, desde
            # qué host y con qué auth. Solo se acumula con debug activo.
            network_census: dict[str, dict[str, Any]] = {}

            def capture_request(request: Request) -> None:
                # JWT: cualquier request a apilocal.bci.cl con Bearer — el
                # dashboard lo dispara desde usuarios/<rut>, cashback/<rut>,
                # obtenerDatosCliente, no solo el BFF de saldos (fix test #1).
                if not jwt_token:
                    token = self._is_jwt_request(request.url, request.headers)
                    if token:
                        jwt_token.append(token)
                        logger.info("bci_jwt_captured", url_prefix=request.url[:80])
                # 1ª request a apilocal: se guarda el Request para leer su set
                # COMPLETO de headers (all_headers, async) fuera del listener y
                # replicar los custom que el gateway exige (test #5). El sync
                # request.headers es parcial: omite origin/cookie/custom.
                if JWT_HOST in request.url and not apilocal_requests:
                    apilocal_requests.append(request)
                # Refuerzo: capturar el post_data real del frontend (PII-safe).
                if request.method == "POST" and JWT_HOST in request.url:
                    for suffix in BODY_CAPTURE_PATHS:
                        if suffix in request.url and suffix not in captured_bodies:
                            post_data = request.post_data
                            if post_data:
                                captured_bodies[suffix] = post_data
                                logger.info(
                                    "bci_body_captured",
                                    path=suffix,
                                    body=self._scrub_body(post_data),
                                )
                # Censo de red (gated): resumen PII-safe deduplicado.
                if settings.scraper_debug_capture:
                    entry = self._census_entry(request)
                    if entry is not None:
                        sig = (
                            f"{entry['host']}|{entry['seg']}|"
                            f"{entry['method']}|{entry['auth_scheme']}"
                        )
                        network_census[sig] = entry

            page.on("request", capture_request)

            try:
                progress("Abriendo sitio del banco...")
                await self._login(
                    page, credentials.rut, credentials.password, jwt_token, progress
                )

                # El portal autenticado pega apilocal.bci.cl (con el JWT) al
                # navegar a Saldos/Movimientos, NO desde la home (test #2/#3).
                # El nudge dispara esa navegación; _await_jwt lo re-corre a mitad
                # de la espera. El listener intercepta el Bearer (case-insensitive).
                progress("Capturando token de sesión...")
                await self._navigate_to_accounts_menu(page)
                jwt = await self._await_jwt(page, jwt_token, network_census)

                # Set COMPLETO de headers del frontend (para replicar los custom
                # que el gateway exige). all_headers es async → se lee acá.
                await self._capture_headers(apilocal_requests, captured_headers)

                progress("Listando cuentas...")
                accounts = await self._list_accounts(
                    page, jwt, credentials.rut, captured_bodies, captured_headers
                )
                if not accounts:
                    raise RecoverableIngestionError("BCI no devolvió cuentas")

                progress(f"Extrayendo movimientos de {len(accounts)} cuenta(s)...")
                all_movs: list[CanonicalMovement] = []
                first_balance: int | None = None

                for acct in accounts:
                    numero = str(acct.get("numero") or "")
                    if not numero:
                        continue

                    balance = await self._fetch_balance(page, jwt, numero, captured_headers)
                    if first_balance is None and balance is not None:
                        first_balance = balance

                    movs_raw = await self._fetch_movements(page, jwt, numero, captured_headers)
                    for mov in movs_raw:
                        cm = self._to_canonical(mov, "bci", since)
                        if cm is not None:
                            all_movs.append(cm)

                all_movs = self._deduplicate(all_movs)
                progress(f"Listo — {len(all_movs)} movimientos")
                elapsed_ms = int((datetime.now() - started_at).total_seconds() * 1000)

                return IngestionResult(
                    balance=(
                        AccountBalance(balance_clp=first_balance, as_of=datetime.now())
                        if first_balance is not None
                        else None
                    ),
                    movements=all_movs,
                    source_kind=SourceKind.SCRAPER,
                    source_identifier=self.source_identifier,
                    elapsed_ms=elapsed_ms,
                    metadata={"account_count": len(accounts)},
                )

            except (AuthenticationError, TwoFactorTimeoutError, FieldFillError):
                raise
            except Exception as exc:
                logger.error("bci_fetch_failed", error=str(exc), tb=traceback.format_exc())
                raise RecoverableIngestionError(f"Scraper BCI falló: {exc}") from exc

    # ── Login ────────────────────────────────────────────────────────────────

    async def _login(
        self,
        page: Page,
        rut: str,
        password: str,
        jwt_token: list[str],
        progress: ProgressCallback,
    ) -> None:
        await page.goto(BCI_BANK_URL, wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(3)

        formatted_rut = self._format_rut(rut)
        clean_rut = re.sub(r"[.\-]", "", rut)

        rut_fill = await self._fill_rut(page, formatted_rut, clean_rut)
        if not rut_fill:
            await self._capture_debug(page, "fill_rut_failed")
            raise RecoverableIngestionError("No se encontró el campo de RUT en BCI")

        await asyncio.sleep(0.5)

        pass_selector = await self._fill_password(page, password)
        if not pass_selector:
            await self._capture_debug(page, "fill_password_failed")
            raise RecoverableIngestionError("No se encontró el campo de clave en BCI")

        rut_selector, rut_typed = rut_fill
        await self._verify_login_fields(page, rut_selector, rut_typed, pass_selector, password)

        progress("Enviando credenciales...")
        await self._submit_login_form(page)

        # Dejar que el DOM asiente antes de leer señales post-submit.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=25_000)
        except Exception:
            pass
        await asyncio.sleep(2)

        # Resolver el estado post-submit: éxito (deja el login), error del banco,
        # challenge 2FA o form pegado. La ambigüedad nunca es clave mala.
        await self._post_submit_flow(page, jwt_token, progress)

        # Dar tiempo a la SPA autenticada a inicializar tokens de sesión.
        await asyncio.sleep(3)
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        await asyncio.sleep(1)

        progress(PROGRESS_LOGIN_OK)

    async def _fill_rut(
        self, page: Page, formatted: str, clean: str
    ) -> tuple[str, str] | None:
        """Llena el RUT con type() — keystrokes reales.

        El campo visible #rut_aux dispara, vía el JS del form, el llenado de los
        hidden #rut/#dig. Eso necesita eventos de teclado reales (igual que la
        directiva delete-zero-left del RUT de BChile); fill() no los emitiría.

        Devuelve (selector, valor_tecleado) para la verificación post-fill, o None.
        """
        for sel in RUT_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if not el:
                    continue
                max_len = await page.evaluate(
                    "(s) => document.querySelector(s)?.maxLength ?? -1", sel
                )
                await el.click(click_count=3)
                value = clean if (0 < max_len <= 10) else formatted
                await el.type(value, delay=45)
                return sel, value
            except Exception:
                continue
        return None

    async def _fill_password(self, page: Page, password: str) -> str | None:
        """Llena la clave con fill() — setea el valor por DOM y dispara input/change.

        type() teclea por keyboard events, y en Chromium bundled headless los
        caracteres con Shift (ej. '$') llegan mal al input → el banco recibe una
        clave incorrecta (causa raíz del sprint BChile 2026-06-12). El campo
        #clave no tiene directivas que requieran keystrokes, así que fill() es
        seguro aquí.

        Devuelve el selector usado para la verificación post-fill, o None.
        """
        for sel in PASS_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if not el:
                    continue
                is_readonly = await page.evaluate(
                    "(s) => { const i = document.querySelector(s); return i?.readOnly || i?.disabled || false; }",
                    sel,
                )
                if is_readonly:
                    continue
                await el.click(click_count=3)
                await el.fill(password)
                return sel
            except Exception:
                continue
        return None

    @staticmethod
    def _normalize_rut_value(value: str) -> str:
        """Normaliza un RUT para comparación post-fill: sin puntos/guion/espacios,
        mayúsculas y sin ceros a la izquierda."""
        return re.sub(r"[.\-\s]", "", value or "").upper().lstrip("0")

    async def _verify_login_fields(
        self, page: Page, rut_selector: str, rut_typed: str, pass_selector: str, password: str
    ) -> None:
        """Verificación post-fill (keystone, reusada de BChile + twist BCI).

        Lee de vuelta input.value de RUT y clave ANTES del submit y compara con
        lo que se quiso escribir. Además, confirma que los hidden #rut/#dig
        quedaron poblados — eso prueba que el type() disparó el JS del form. Un
        mismatch (o hidden vacíos) significa que el valor correcto nunca va a
        llegar al banco: FieldFillError (técnico, recoverable), no auth.

        RUT se compara normalizado (el sitio reformatea con puntos/guion); la
        clave, exacta. PII: jamás se loguean valores — solo longitudes (§20).
        """
        values = await page.evaluate(
            """(sels) => sels.map((s) => {
                const el = document.querySelector(s);
                return el ? el.value : null;
            })""",
            [rut_selector, pass_selector, *RUT_HIDDEN_SELECTORS],
        )
        rut_value, pass_value = values[0], values[1]
        hidden_values = values[2:]

        if self._normalize_rut_value(rut_value or "") != self._normalize_rut_value(rut_typed):
            logger.warning(
                "bci_field_mismatch", field="rut",
                expected_len=len(rut_typed), got_len=len(rut_value or ""),
            )
            raise FieldFillError("rut", expected_len=len(rut_typed), got_len=len(rut_value or ""))

        if pass_value != password:
            logger.warning(
                "bci_field_mismatch", field="password",
                expected_len=len(password), got_len=len(pass_value or ""),
            )
            raise FieldFillError(
                "password", expected_len=len(password), got_len=len(pass_value or "")
            )

        # Keystone BCI: el form parte el RUT visible en los hidden #rut/#dig al
        # teclear. Si quedaron vacíos, el banco recibiría un RUT vacío — eso es
        # un fill fallido (técnico), jamás "clave mala".
        populated = sum(1 for v in hidden_values if (v or "").strip())
        if populated < len(RUT_HIDDEN_SELECTORS):
            logger.warning(
                "bci_hidden_rut_not_populated",
                expected=len(RUT_HIDDEN_SELECTORS), populated=populated,
            )
            raise FieldFillError(
                "rut_hidden",
                expected_len=len(RUT_HIDDEN_SELECTORS),
                got_len=populated,
            )

        logger.info("bci_fields_verified", rut_len=len(rut_typed), password_len=len(password))

    async def _submit_login_form(self, page: Page) -> None:
        """Dispara el submit DENTRO del form que contiene #clave.

        La página tiene varios button[type=submit] (buscador, comentarios); un
        submit global mandaría el form equivocado. Se localiza el form de la
        clave y se dispara su submit; si no hay botón, requestSubmit() del form.
        """
        clicked = await page.evaluate(
            """() => {
                const pass = document.querySelector('#clave')
                    || document.querySelector('input[name="clave"]')
                    || document.querySelector('input[type="password"]');
                const form = pass ? pass.closest('form') : null;
                if (!form) return false;
                const btn = form.querySelector('button[type="submit"], input[type="submit"]');
                if (btn) { btn.click(); return true; }
                if (form.requestSubmit) { form.requestSubmit(); } else { form.submit(); }
                return true;
            }"""
        )
        if clicked:
            return

        # Fallback: heurística por texto del botón (igual que BChile).
        await page.evaluate("""() => {
            for (const btn of Array.from(document.querySelectorAll("button, a, input[type='submit']"))) {
                const text = btn.innerText?.trim().toLowerCase() || "";
                if (text.includes("ingresar") || text.includes("acceder")
                    || text.includes("continuar") || text.includes("entrar")) {
                    btn.click();
                    return;
                }
            }
        }""")

    def _still_on_login(self, page: Page, jwt_token: list[str]) -> bool:
        """¿Seguimos en el login? Señal de éxito BCI: dejar el marcador de URL
        (la app autenticada es www.bci.cl/personas) O haber capturado el JWT
        (tráfico Bearer a apilocal ⇒ autenticado, backstop fuerte)."""
        if jwt_token:
            return False
        return LOGIN_URL_MARKER in page.url

    async def _post_submit_flow(
        self, page: Page, jwt_token: list[str], progress: ProgressCallback
    ) -> None:
        """Resuelve el estado post-submit (portado de BChile, señal de éxito BCI).

        Poll cada `_poll_interval_sec` con cuatro salidas posibles:
          · Dejó el login (_still_on_login False) → login OK (return).
          · Mensaje de error del banco (LOGIN_ERROR_KEYWORDS) en CUALQUIER tick
            → AuthenticationError.
          · Pantalla 2FA detectada POSITIVAMENTE (TWO_FA_KEYWORDS) → modo espera
            con el timeout 2FA completo y progreso visible al usuario.
          · Sin señales tras `_post_submit_grace_sec`: si el form de clave
            DESAPARECIÓ, se asume un challenge 2FA con texto desconocido
            (espera + captura debug para refinar keywords); si el form sigue
            visible, el submit no avanzó → RecoverableIngestionError (anti-bot,
            el flag tipo B-1 del DetectCA easysol queda acá).

        REGLA (la razón de ser de este método): la ambigüedad JAMÁS se castiga
        como AuthenticationError — eso mandaría la cuenta a needs_reconnection
        (hard-stop) con la clave buena. Clave mala se declara SOLO con el
        mensaje del banco en pantalla.
        """
        start = datetime.now()
        two_fa_started: datetime | None = None
        last_progress_emit = 0.0

        while True:
            if not self._still_on_login(page, jwt_token):
                return  # éxito: dejó el login o el JWT ya apareció

            # Lecturas de DOM tolerantes: una navegación en curso destruye el
            # execution context — ese tick se pierde y la URL decide el próximo.
            try:
                login_error = await self._check_login_error(page)
            except Exception:
                login_error = None
            if login_error:
                logger.warning(
                    "bci_auth_error", reason="check_login_error", detail=login_error[:200]
                )
                await self._capture_debug(page, "auth_check_login_error", pii_safe=True)
                raise AuthenticationError(f"Error de login: {login_error}")

            try:
                body_text = await page.evaluate(
                    "() => (document.body?.innerText || '').toLowerCase()"
                )
            except Exception:
                body_text = ""

            elapsed = (datetime.now() - start).total_seconds()

            if two_fa_started is None:
                if self._match_2fa_text(body_text):
                    two_fa_started = datetime.now()
                    logger.info("bci_2fa_detected", positive=True)
                    progress(f"{PROGRESS_2FA_WAIT_PREFIX} en tu app BCI...")
                    await self._capture_debug(page, "2fa_screen", pii_safe=True)
                elif elapsed >= self._post_submit_grace_sec:
                    if await self._password_field_present(page):
                        # Form completo en pantalla, sin error y sin redirect:
                        # el submit no avanzó. Posible challenge anti-bot
                        # (DetectCA easysol desde datacenter — riesgo tipo B-1).
                        logger.warning("bci_post_submit_stuck")
                        await self._capture_debug(page, "post_submit_form_stuck", pii_safe=True)
                        raise RecoverableIngestionError(
                            "El formulario de login no avanzó tras el envío "
                            "(posible challenge anti-bot)"
                        )
                    # El form desapareció pero seguimos en el login: lo más
                    # probable es un challenge 2FA con texto que aún no
                    # conocemos. Beneficio de la duda + captura para refinar.
                    two_fa_started = datetime.now()
                    logger.warning("bci_2fa_assumed", reason="unrecognized_screen")
                    progress(f"{PROGRESS_2FA_WAIT_PREFIX} en tu app BCI...")
                    await self._capture_debug(page, "2fa_unrecognized_screen", pii_safe=True)

            if two_fa_started is not None:
                if any(kw in body_text for kw in REJECTION_KEYWORDS):
                    logger.info("bci_2fa_rejected")
                    raise TwoFactorTimeoutError(
                        "La aprobación 2FA fue rechazada o cancelada. "
                        "Reintenta el sync y aprueba la notificación en tu app."
                    )
                elapsed_2fa = (datetime.now() - two_fa_started).total_seconds()
                if elapsed_2fa >= self._timeout_sec:
                    logger.warning("bci_2fa_timeout", timeout_sec=self._timeout_sec)
                    await self._capture_debug(page, "2fa_timeout", pii_safe=True)
                    raise TwoFactorTimeoutError(
                        "Timeout esperando aprobación 2FA. "
                        "Abre tu app BCI y aprueba cuando inicies el sync."
                    )
                if elapsed_2fa - last_progress_emit >= 15:
                    last_progress_emit = elapsed_2fa
                    remaining = int(self._timeout_sec - elapsed_2fa)
                    progress(f"{PROGRESS_2FA_WAIT_PREFIX} ({remaining}s restantes)...")

            await asyncio.sleep(self._poll_interval_sec)

    @staticmethod
    def _match_2fa_text(body_text: str, keywords: list[str] = TWO_FA_KEYWORDS) -> bool:
        """True si el texto (ya en minúsculas) matchea la pantalla 2FA."""
        return any(kw in body_text for kw in keywords)

    async def _password_field_present(self, page: Page) -> bool:
        """¿Sigue el form de login en pantalla? (señal estructural post-submit).

        El challenge 2FA reemplaza el form — si el campo de clave sigue presente,
        lo que vemos NO es un 2FA sino el form pegado.
        """
        for sel in PASS_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el:
                    return True
            except Exception:
                continue
        return False

    async def _check_login_error(self, page: Page) -> str | None:
        return await page.evaluate(
            """(keywords) => {
                for (const sel of ['[class*="error"]', '[class*="alert"]', '[role="alert"]', '[class*="mensaje"]']) {
                    for (const el of document.querySelectorAll(sel)) {
                        const text = el.innerText?.trim();
                        if (text && keywords.some((kw) => text.toLowerCase().includes(kw)))
                            return text;
                    }
                }
                return null;
            }""",
            LOGIN_ERROR_KEYWORDS,
        )

    # ── Captura del JWT (independiente del menú) ──────────────────────────────

    @staticmethod
    def _is_jwt_request(url: str, headers: dict[str, str]) -> str | None:
        """Token Bearer si la request es a apilocal.bci.cl con `Authorization:
        bearer …`, SIN importar el path NI la capitalización del esquema.

        El dashboard dispara el JWT desde usuarios/<rut>, cashback/<rut> y
        obtenerDatosCliente — no solo el BFF de saldos. Capturar por host (no
        por el path del BFF) hace que el token aparezca sin depender del menú
        (fix del test #1).

        CASE-INSENSITIVE (fix del test #3): el frontend de BCI manda el esquema
        en MINÚSCULA (`authorization: bearer <token>`) — el censo de red lo
        confirmó (`auth_scheme='bearer'`). El `startswith("Bearer ")`
        case-sensitive anterior dejaba pasar el token pese a estar en CADA
        request a apilocal → `_await_jwt` siempre hacía timeout. None si no
        aplica."""
        if JWT_HOST not in url:
            return None
        auth = headers.get("authorization", "")
        prefix = "bearer "
        if auth[: len(prefix)].lower() == prefix:
            return auth[len(prefix):].strip() or None
        return None

    async def _await_jwt(
        self, page: Page, jwt_token: list[str], network_census: dict[str, dict[str, Any]]
    ) -> str:
        """Espera ~`jwt_wait_sec` a que el dashboard emita el primer Bearer a
        apilocal.bci.cl (el listener lo captura). A mitad de la espera re-corre
        el nudge una vez (la home no pega apilocal hasta navegar — test #2).
        Si nunca llega → diagnóstico PII-safe de máxima información (censo +
        sonda de token + DOM) y raise."""
        iters = max(2, int(self._jwt_wait_sec / self._poll_interval_sec))
        midpoint = iters // 2
        renudged = False
        for i in range(iters):
            if jwt_token:
                if settings.scraper_debug_capture:
                    logger.info("bci_network_census", entries=list(network_census.values()))
                return jwt_token[0]
            if i == midpoint and not renudged:
                renudged = True
                await self._navigate_to_accounts_menu(page)
            await asyncio.sleep(self._poll_interval_sec)
        await self._emit_jwt_timeout_diagnostics(page, network_census)
        raise RecoverableIngestionError(
            "No se capturó el JWT de BCI — el dashboard autenticado no emitió "
            "ninguna request con Bearer a apilocal.bci.cl en la ventana de espera."
        )

    async def _emit_jwt_timeout_diagnostics(
        self, page: Page, network_census: dict[str, dict[str, Any]]
    ) -> None:
        """Máxima información PII-safe antes del raise por timeout (§20).

        Gated tras scraper_debug_capture. Censo de red + sonda de
        storage/cookies + URLs de frames + captura DOM scrubeada. Todo
        envuelto: un fallo de diagnóstico jamás enmascara el raise."""
        if not settings.scraper_debug_capture:
            return
        try:
            logger.info("bci_network_census", entries=list(network_census.values()))
        except Exception as exc:
            logger.warning("bci_network_census_failed", error=str(exc))
        await self._probe_tokens(page)
        try:
            logger.info("bci_frames", urls=[self._safe_url(f.url) for f in page.frames])
        except Exception as exc:
            logger.info("bci_frames_failed", error=str(exc))
        await self._capture_debug(page, "jwt_timeout", pii_safe=True)

    async def _probe_tokens(self, page: Page) -> None:
        """Sonda PII-safe de localStorage/sessionStorage/cookies en busca del
        token (§20: solo key names, hosts, booleans — jamás valores).

        Si el token vive en storage/cookie, el fix real lo lee directo, sin
        depender de que el dashboard dispare una request a apilocal."""
        findings: list[dict[str, Any]] = []
        for frame in page.frames:
            try:
                data = await frame.evaluate(STORAGE_PROBE_JS)
            except Exception:
                continue  # cross-origin / contexto destruido → se ignora
            if not isinstance(data, dict):
                continue
            frame_host = urlsplit(frame.url).hostname or ""
            findings.extend(
                self._safe_storage_findings(
                    frame_host, data.get("local", {}), data.get("session", {})
                )
            )
        logger.info("bci_token_probe_storage", findings=findings)
        try:
            cookies = await page.context.cookies()
        except Exception as exc:
            logger.info("bci_token_probe_cookies_failed", error=str(exc))
            return
        logger.info(
            "bci_token_probe_cookies", cookies=self._safe_cookie_summary(cookies)
        )

    @staticmethod
    def _census_entry(request: Request) -> dict[str, Any] | None:
        """Resumen PII-safe de una request a *.bci.cl para el censo de red.

        host + primer segmento de path (dígitos redactados) + método +
        has_auth + auth_scheme (primera palabra del header Authorization;
        '[opaque]' si no parece un esquema — nunca se filtra un token crudo).
        None si el host no es *.bci.cl (§20)."""
        parts = urlsplit(request.url)
        host = parts.hostname or ""
        if not host.endswith("bci.cl"):
            return None
        segs = [s for s in parts.path.split("/") if s]
        seg = BCIScraperSource._redact_digits(segs[0]) if segs else ""
        auth = request.headers.get("authorization", "")
        scheme: str | None = None
        if auth:
            scheme = auth.split(" ", 1)[0]
            if len(scheme) > 12 or not scheme.isalpha():
                scheme = "[opaque]"
        return {
            "host": host,
            "seg": seg,
            "method": request.method,
            "has_auth": bool(auth),
            "auth_scheme": scheme,
        }

    @staticmethod
    def _safe_storage_findings(
        frame_host: str, local: Any, session: Any
    ) -> list[dict[str, Any]]:
        """Findings PII-safe de storage: frame_host + store + key (dígitos
        redactados) + looks_like_jwt (bool). El VALOR nunca entra — el test
        JWT-shaped se hizo en JS y solo vuelve el booleano (§20)."""
        out: list[dict[str, Any]] = []
        for store_name, items in (("local", local), ("session", session)):
            if not isinstance(items, dict):
                continue
            for key, looks in items.items():
                out.append(
                    {
                        "frame_host": frame_host,
                        "store": store_name,
                        "key": BCIScraperSource._redact_digits(str(key)),
                        "looks_like_jwt": bool(looks),
                    }
                )
        return out

    @staticmethod
    def _safe_cookie_summary(cookies: list[Any]) -> list[dict[str, str]]:
        """Nombre + dominio de las cookies de bci.cl. NUNCA el valor ni la
        expiración (§20)."""
        out: list[dict[str, str]] = []
        for c in cookies:
            domain = str(c.get("domain", ""))
            if "bci.cl" not in domain:
                continue
            out.append(
                {"name": BCIScraperSource._redact_digits(str(c.get("name", ""))), "domain": domain}
            )
        return out

    @staticmethod
    def _safe_url(url: str) -> str:
        """URL sin query/fragment y con RUT/dígitos largos redactados (§20)."""
        base = url.split("?", 1)[0].split("#", 1)[0]
        base = re.sub(r"\b\d{1,2}(?:\.?\d{3}){2}\s*-\s*[\dkK]\b", "[rut]", base)
        return BCIScraperSource._redact_digits(base)

    @staticmethod
    def _redact_digits(s: str) -> str:
        """Redacta corridas de 6+ dígitos (RUT sin formato, número de cuenta)."""
        return re.sub(r"\d{6,}", "[digits]", s or "")

    # ── Navegación al menú de cuentas (nudge best-effort) ─────────────────────

    async def _navigate_to_accounts_menu(self, page: Page) -> None:
        """Nudge best-effort en TODOS los frames: clickea el acceso a
        cuentas/movimientos/cartola para empujar al frontend a pegarle a
        apilocal.bci.cl (la home no lo hace sola — test #2).

        NO es crítico ni fatal: el flujo espera el JWT vía _await_jwt encuentre
        o no este menú. Matchea por innerText / aria-label / title y por
        substring de href; itera frames (el view de cuentas puede ser un
        iframe). Solo clicks de navegación, nunca submit. Cualquier excepción
        por frame se traga."""
        for frame in page.frames:
            try:
                clicked = await frame.evaluate(MENU_CLICK_JS, ACCOUNTS_MENU_TEXT)
            except Exception:
                continue  # cross-origin / contexto destruido → siguiente frame
            if clicked:
                logger.info("bci_dashboard_nudge_clicked")
                await asyncio.sleep(4)
                return
        logger.info("bci_dashboard_nudge_no_menu")
        await asyncio.sleep(2)

    # ── API REST con JWT Bearer ───────────────────────────────────────────────

    async def _api_post(
        self,
        page: Page,
        jwt: str,
        path: str,
        body: dict,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """POST a la API interna (BFF v3.2) desde el render de Chrome real.

        El fetch se emite IN-PAGE (no con el cliente HTTP de Playwright) a
        propósito: conserva el path de red de Chrome real — cookies de sesión,
        TLS fingerprint y el WAF (Cloudflare cf_clearance/__cf_bm + DetectCA
        easysol) que un cliente HTTP plano no pasa.

        Espeja el request del propio frontend (tests #4/#5) para no romperse:
          · credentials: "omit" — apilocal autentica por Bearer, NO por cookies;
            "include" fuerza el modo CORS-con-credenciales y la respuesta de
            apilocal (ACAO '*' sin Allow-Credentials:true) no lo satisface → el
            browser bloquea ANTES de ver el status ("Failed to fetch", test #4).
          · esquema "bearer" en minúscula — exacto como lo manda el frontend
            (el censo del test #3 mostró auth_scheme='bearer').
          · `extra_headers` — los headers custom que el frontend manda y el
            gateway BFF exige (x-apikey, canal, id-transaccion, x-bci-*…): sin
            ellos respondía 400 "Cabeceras incompletas" (test #5). Se capturan
            con all_headers (_capture_headers) y se mergean acá; los nuestros
            (authorization/content-type/accept) SIEMPRE ganan. Vacío → se
            degrada al comportamiento previo (sin custom, no rompe).

        Los args (url, jwt, body, extra) van por evaluate, nunca interpolados en
        el script — el token y el apikey jamás entran al source del fetch.

        FALLBACK (no implementado): si el fetch in-page siguiera fallando, la
        alternativa es page.context.request.post() (APIRequestContext, no sujeto
        a CORS) — pero usa el cliente HTTP de Playwright, no el render de Chrome,
        con riesgo de fingerprint anti-bot. Por eso el in-page va primero.
        """
        return await page.evaluate(
            """async ([url, jwt, bodyStr, extra]) => {
                const headers = {};
                if (extra) { for (const k in extra) headers[k] = extra[k]; }
                // Los nuestros SIEMPRE ganan (el denylist ya sacó accept/
                // content-type/authorization de extra; esto es defensa).
                headers["Accept"] = "application/json";
                headers["Content-Type"] = "application/json";
                headers["Authorization"] = `bearer ${jwt}`;
                const r = await fetch(url, {
                    method: "POST",
                    credentials: "omit",
                    headers: headers,
                    body: bodyStr,
                    referrer: window.location.href,
                });
                if (!r.ok) {
                    const text = await r.text().catch(() => "");
                    throw new Error(`POST ${url} -> ${r.status} :: ${text.slice(0, 200)}`);
                }
                return r.json();
            }""",
            [f"{BCI_API_BASE}/{path}", jwt, json.dumps(body), extra_headers or {}],
        )

    async def _list_accounts(
        self,
        page: Page,
        jwt: str,
        rut: str,
        captured: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> list[dict]:
        """POST cuentas-busquedas/por-rut → lista de cuentas.

        Body CONFIRMADO (test #1): {"rut": "<rut>-<dv>"} (sin puntos, guion-dv).
        Si el confirmado no devuelve cuentas y se capturó el body real del
        frontend, se reintenta con esa forma (capture-and-replay, refuerzo).
        """
        body = self._accounts_body(rut)
        accounts = self._extract_accounts(
            await self._api_post(page, jwt, ACCOUNTS_PATH, body, headers)
        )
        if accounts:
            return accounts
        replay = self._body_for(captured, ACCOUNTS_PATH, body)
        if replay != body:
            logger.info("bci_accounts_replay_fallback")
            accounts = self._extract_accounts(
                await self._api_post(page, jwt, ACCOUNTS_PATH, replay, headers)
            )
        return accounts

    @staticmethod
    def _extract_accounts(raw: Any) -> list[dict]:
        """Lista de cuentas desde la respuesta de por-rut ({cuentas:[...]})."""
        if isinstance(raw, dict):
            cuentas = raw.get("cuentas", [])
            return cuentas if isinstance(cuentas, list) else []
        return raw if isinstance(raw, list) else []

    async def _fetch_balance(
        self, page: Page, jwt: str, numero: str, headers: dict[str, str] | None = None
    ) -> int | None:
        """POST cuentas-busquedas/por-numero-cuenta → saldoContable (fallback
        saldoDisponible). Body CONFIRMADO: {"cuentaNumero": "<n>"} (SIN tipo)."""
        if not numero:
            return None
        try:
            data = await self._api_post(
                page, jwt, BALANCE_PATH, {"cuentaNumero": numero}, headers
            )
        except Exception as exc:
            logger.warning("bci_balance_fetch_failed", error=str(exc))
            return None
        if not isinstance(data, dict):
            return None
        saldo = data.get("saldoContable")
        if saldo is None:
            saldo = data.get("saldoDisponible")
        return self._parse_int(saldo) if saldo is not None else None

    async def _fetch_movements(
        self, page: Page, jwt: str, numero: str, headers: dict[str, str] | None = None
    ) -> list[dict]:
        """POST cuentas-movimientos/por-numero-cuenta → movimientos.

        Body CONFIRMADO: {"numeroCuenta": "<n>"} (key ≠ la del saldo, SIN tipo).
        """
        if not numero:
            return []
        try:
            raw = await self._api_post(
                page, jwt, MOVEMENTS_PATH, {"numeroCuenta": numero}, headers
            )
        except Exception as exc:
            logger.warning("bci_movements_fetch_failed", numero_len=len(numero), error=str(exc))
            return []
        if isinstance(raw, dict):
            movs = raw.get("movimientos", [])
            return movs if isinstance(movs, list) else []
        return raw if isinstance(raw, list) else []

    def _body_for(self, captured: dict[str, str], path: str, fallback: dict) -> dict:
        """Body capturado del frontend (parseado) o el fallback construido."""
        raw = captured.get(path)
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except (ValueError, TypeError):
                logger.warning("bci_captured_body_unparseable", path=path)
        return fallback

    def _accounts_body(self, rut: str) -> dict:
        """Body CONFIRMADO de por-rut (test #1): {"rut": "<rut>-<dv>"}."""
        return {"rut": self._rut_with_dv(rut)}

    @staticmethod
    def _rut_with_dv(rut: str) -> str:
        """RUT sin puntos/guiones, con guion-dv: '22.141.522-1' → '22141522-1'.

        Forma exacta del body de por-rut confirmada en el test #1 (igual que
        BChile: se limpia el RUT y se reinserta el guion antes del dígito
        verificador). NO es {rut, dig}."""
        clean = re.sub(r"[.\-\s]", "", rut).upper()
        if len(clean) < 2:
            return clean
        return f"{clean[:-1]}-{clean[-1]}"

    @staticmethod
    def _scrub_body(post_data: str) -> str:
        """Redacta PII de un post_data antes de loguearlo (doctrina §20).

        Redacta RUTs con formato y corridas largas de dígitos (RUT sin formato,
        números de cuenta). Deja la ESTRUCTURA de keys JSON intacta — que es lo
        único que necesitamos para replicar la forma del body.
        """
        s = re.sub(r"\b\d{1,2}(?:\.?\d{3}){2}\s*-\s*[\dkK]\b", "[rut]", post_data)
        s = re.sub(r"\d{6,}", "[digits]", s)
        return s

    @staticmethod
    def _scrub_headers(headers: dict[str, str]) -> dict[str, str]:
        """Headers de un request del frontend, PII-safe (doctrina §20).

        Redacta: el token (`authorization` → solo el esquema + '[redacted]', lo
        que confirma que el frontend manda 'bearer' en minúscula); las cookies
        por completo; y el VALOR de headers cuyo nombre sugiere credencial
        (apikey, token, secret, x-auth*…) — un x-apikey del BFF no debe quedar en
        logs. En el resto redacta RUTs y corridas de dígitos. Las keys SIEMPRE
        quedan visibles (es el diagnóstico: QUÉ headers manda el frontend) y los
        no sensibles (content-type, accept, origin, canal…) muestran su valor.
        """
        out: dict[str, str] = {}
        for key, value in headers.items():
            lk = key.lower()
            if lk == "authorization":
                # Solo se preserva el esquema si tiene forma "<scheme> <token>":
                # un valor sin espacio sería el token crudo → se redacta entero.
                scheme = value.split(" ", 1)[0] if value else ""
                if " " in value and scheme.isalpha() and len(scheme) <= 12:
                    out[key] = f"{scheme} [redacted]"
                else:
                    out[key] = "[redacted]"
            elif lk in ("cookie", "set-cookie") or any(
                hint in lk for hint in SENSITIVE_HEADER_HINTS
            ):
                out[key] = "[redacted]"
            else:
                v = re.sub(r"\b\d{1,2}(?:\.?\d{3}){2}\s*-\s*[\dkK]\b", "[rut]", value)
                out[key] = re.sub(r"\d{6,}", "[digits]", v)
        return out

    @staticmethod
    def _replayable_headers(headers: dict[str, str]) -> dict[str, str]:
        """Subconjunto de headers del frontend que SÍ se replican en _api_post.

        El gateway BFF respondía 400 "Cabeceras incompletas" (test #5): faltaban
        los headers custom que el frontend manda. Se replican TODOS salvo (a) los
        forbidden header names que el browser gestiona/descarta igual (host,
        cookie, origin, user-agent, sec-*…) y (b) los que seteamos nosotros
        (authorization, content-type, accept). Lo que queda — x-apikey, canal,
        id-transaccion, x-bci-*… — es lo que faltaba. Keys a minúscula (como las
        devuelve all_headers)."""
        out: dict[str, str] = {}
        for key, value in headers.items():
            lk = key.lower()
            if lk in HEADER_REPLAY_DENY:
                continue
            if any(lk.startswith(p) for p in HEADER_REPLAY_DENY_PREFIXES):
                continue
            out[lk] = value
        return out

    async def _capture_headers(
        self, requests: list[Request], store: dict[str, str]
    ) -> None:
        """Lee el set COMPLETO de headers de la 1ª request a apilocal y guarda
        los replicables en `store` (los consume _api_post).

        `request.headers` (sync, en el listener) es PARCIAL — omite origin/
        cookie/custom: el header que el gateway exige no aparece ahí.
        `all_headers()` es async, por eso se lee acá (fuera del listener sync).
        First-wins: el 400 es global del gateway, con la 1ª request (la del JWT,
        garantizada) basta. Un fallo jamás rompe el flujo ni la captura del JWT
        (§20). Real para replay; el log va scrubeado."""
        if not requests:
            return
        try:
            complete = await requests[0].all_headers()
        except Exception as exc:
            logger.warning("bci_all_headers_failed", error=str(exc))
            return
        replayable = self._replayable_headers(complete)
        if replayable:
            store.update(replayable)
        if settings.scraper_debug_capture:
            logger.info(
                "bci_request_headers",
                replayed=sorted(replayable.keys()),
                headers=self._scrub_headers(complete),
            )

    # ── Normalización ─────────────────────────────────────────────────────────

    def _to_canonical(
        self, mov: dict, bank_id: str, since: date | None
    ) -> CanonicalMovement | None:
        amount = self._parse_amount(mov)
        desc = str(
            mov.get("glosa") or mov.get("descripcion") or mov.get("descripcionMovimiento") or ""
        ).strip()
        occurred = self._parse_date(
            mov.get("fechaMovimiento") or mov.get("fecha") or mov.get("fechaContable")
        )
        if since and occurred < since:
            return None
        native_id = str(mov.get("idMovimiento") or "").strip() or None
        return CanonicalMovement(
            external_id=build_external_id(
                bank_id, occurred, amount, desc, MovementSource.ACCOUNT,
                native_id=native_id,
            ),
            amount_clp=amount,
            raw_description=desc,
            occurred_at=occurred,
            movement_source=MovementSource.ACCOUNT,
            source_kind=SourceKind.SCRAPER,
            source_metadata={"native_id": native_id},
        )

    def _parse_amount(self, mov: dict) -> int:
        """Magnitud desde `monto` (str/num) + signo desde `tipo`.

        BCI entrega `monto` como magnitud y `tipo` (cargo/abono/débito/crédito)
        da el signo: positivo = ingreso (abono), negativo = gasto (cargo). Si el
        tipo no se reconoce, se respeta el signo que venga en el monto.
        """
        raw = mov.get("monto")
        if raw is None:
            raw = mov.get("montoMovimiento", 0)
        magnitude = self._parse_int(raw)
        tipo = str(mov.get("tipo") or mov.get("tipoMovimiento") or "").strip().lower()
        if tipo in ("cargo", "debito", "débito"):
            return -abs(magnitude)
        if tipo in ("abono", "credito", "crédito"):
            return abs(magnitude)
        return magnitude

    @staticmethod
    def _parse_int(raw: Any) -> int:
        """Parsea un monto CLP a int. Tolera str con separador de miles chileno
        ('12.345'), signo y símbolos; corta en la coma decimal si la hubiera."""
        if isinstance(raw, bool):
            return 0
        if isinstance(raw, (int, float)):
            return int(raw)
        s = str(raw).strip()
        if not s:
            return 0
        # Formato chileno: '.' miles, ',' decimales — la parte entera es lo que importa.
        if "," in s:
            s = s.split(",", 1)[0]
        neg = s.lstrip().startswith("-")
        digits = re.sub(r"[^\d]", "", s)
        if not digits:
            return 0
        value = int(digits)
        return -value if neg else value

    def _parse_date(self, raw: str | int | None) -> date:
        if raw is None:
            return date.today()
        if isinstance(raw, int):
            try:
                return datetime.fromtimestamp(raw / 1000).date()
            except Exception:
                return date.today()
        s = str(raw).strip()
        if "T" in s:
            s = s.split("T")[0]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            try:
                return date.fromisoformat(s)
            except ValueError:
                pass
        m = re.match(r"^(\d{2})[/-](\d{2})[/-](\d{4})$", s)
        if m:
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass
        return date.today()

    def _deduplicate(self, movs: list[CanonicalMovement]) -> list[CanonicalMovement]:
        seen: set[str] = set()
        out: list[CanonicalMovement] = []
        for m in movs:
            if m.external_id in seen:
                continue
            seen.add(m.external_id)
            out.append(m)
        return out

    def _format_rut(self, rut: str) -> str:
        clean = re.sub(r"[.\-]", "", rut).upper()
        if len(clean) < 2:
            return rut
        body, dv = clean[:-1], clean[-1]
        with_dots = ""
        for i, c in enumerate(reversed(body)):
            if i > 0 and i % 3 == 0:
                with_dots = "." + with_dots
            with_dots = c + with_dots
        return f"{with_dots}-{dv}"

    # ── Captura debug (doctrina §20) ──────────────────────────────────────────

    async def _capture_debug(self, page: Page, label: str, *, pii_safe: bool = False) -> None:
        """Captura el estado actual de la página si scraper_debug_capture=True.

        Dos modos:
          · pii_safe=False — screenshot + HTML crudos. SOLO para estados
            pre-fill (campo no encontrado): ahí el form está vacío y no hay PII.
          · pii_safe=True — SOLO HTML scrubeado (_scrub_pii): valores de inputs
            y RUTs redactados. Un screenshot no se puede sanitizar y los estados
            post-submit (error, 2FA) pueden mostrar el RUT en pantalla (§20). Es
            el material para refinar TWO_FA_KEYWORDS cuando un tester real
            dispare el challenge.

        Si scraper_debug_bucket está configurado, la captura además se sube a
        Supabase Storage (el filesystem del contenedor es efímero).
        """
        if not settings.scraper_debug_capture:
            return
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_dir = settings.scraper_debug_dir or tempfile.gettempdir()
            stem = f"bci_{label}_{ts}"
            html_path = os.path.join(base_dir, f"{stem}.html")
            files: list[tuple[str, str, str]] = []

            if not pii_safe:
                screenshot_path = os.path.join(base_dir, f"{stem}.png")
                await page.screenshot(path=screenshot_path)
                files.append((f"bci/{stem}.png", screenshot_path, "image/png"))

            content = await page.content()
            if pii_safe:
                content = self._scrub_pii(content)
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            files.append((f"bci/{stem}.html", html_path, "text/html"))
            logger.info("scraper_debug_captured", label=label, pii_safe=pii_safe, html=html_path)

            if settings.scraper_debug_bucket:
                await self._upload_debug_capture(settings.scraper_debug_bucket, files)
        except Exception as exc:
            logger.warning("scraper_debug_capture_failed", error=str(exc))

    @staticmethod
    def _scrub_pii(html: str) -> str:
        """Redacta PII del HTML capturado antes de persistirlo (doctrina §20).

        Cubre: valores de inputs serializados (value="..."), RUTs con formato y
        cualquier corrida larga de dígitos. Agresivo a propósito: en una captura
        debug sobra redactar de más, jamás de menos.
        """
        html = re.sub(r'value="[^"]*"', 'value="[redacted]"', html)
        html = re.sub(r"value='[^']*'", "value='[redacted]'", html)
        html = re.sub(r"\b\d{1,2}(?:\.?\d{3}){2}\s*-\s*[\dkK]\b", "[rut]", html)
        # \d{6,} (no \d{7,10}): el DOM autenticado puede mostrar números de
        # cuenta de cualquier largo — mejor redactar de más que de menos (§20).
        html = re.sub(r"\d{6,}", "[digits]", html)
        return html

    async def _upload_debug_capture(
        self, bucket: str, files: list[tuple[str, str, str]]
    ) -> None:
        """Sube capturas debug al bucket privado de Supabase Storage.

        Bucket privado, service_role only (doctrina §15). El cliente es sync, así
        que corre en thread para no bloquear el loop.
        """
        try:
            from sky.core.db import get_service_client

            client = get_service_client()
            for key, path, content_type in files:
                with open(path, "rb") as fh:
                    data = fh.read()

                def _upload(k: str = key, d: bytes = data, ct: str = content_type) -> None:
                    client.storage.from_(bucket).upload(k, d, {"content-type": ct, "upsert": "true"})

                await asyncio.to_thread(_upload)
            logger.info("scraper_debug_uploaded", bucket=bucket, files=[k for k, _, _ in files])
        except Exception as exc:
            logger.warning("scraper_debug_upload_failed", error=str(exc))
