"""
sky.ingestion.sources.bci_scraper — Scraper BCI (Playwright + JWT Bearer).

ESTRATEGIA:
    BCI expone APIs REST internas en apilocal.bci.cl (BFF v3.2) autenticadas
    con JWT Bearer. El scraper hace login en el portal web, navega al menú de
    cuentas para que el frontend dispare las requests con el JWT, lo intercepta
    del tráfico de red, y luego llama directamente a la API sin más navegación.

FLUJO:
    1. goto portal BCI (www.bci.cl/corporativo/banco-en-linea/personas)
    2. type RUT en #rut_aux (el form parte en los hidden #rut/#dig) + fill #clave
    3. verificación post-fill (incl. que los hidden #rut/#dig se poblaron)
    4. submit DENTRO del form de #clave → resolver post-submit (error/2FA/éxito)
    5. navegar a "Saldos y movimientos" → interceptar JWT Bearer + bodies POST
    6. API: POST cuentas-busquedas/por-rut → lista de cuentas
    7. API: POST cuentas-busquedas/por-numero-cuenta → saldoContable por cuenta
    8. API: POST cuentas-movimientos/por-numero-cuenta → movimientos por cuenta
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
ACCOUNTS_PATH = "cuentas-busquedas/por-rut"
BALANCE_PATH = "cuentas-busquedas/por-numero-cuenta"
MOVEMENTS_PATH = "cuentas-movimientos/por-numero-cuenta"
# Paths cuyo body conoce el frontend y nosotros no del todo: se captura el
# post_data real al navegar a "Saldos y movimientos" y se replica esa forma
# exacta (capture-and-replay). por-numero-cuenta ya es {numero,tipo} (conocido).
BODY_CAPTURE_PATHS = (ACCOUNTS_PATH, MOVEMENTS_PATH)

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
]


class BCIScraperSource(DataSource):
    """DataSource para BCI vía Playwright + JWT REST (BFF v3.2)."""

    def __init__(
        self,
        two_fa_timeout_sec: int = 120,
        *,
        post_submit_grace_sec: float = 25.0,
        poll_interval_sec: float = 1.0,
    ):
        self._timeout_sec = two_fa_timeout_sec
        # Cuánto esperar señales post-submit (error / 2FA / redirect) antes de
        # decidir por estructura. Override solo en tests (acelerar el loop).
        self._post_submit_grace_sec = post_submit_grace_sec
        self._poll_interval_sec = poll_interval_sec

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

            def capture_request(request: Request) -> None:
                if JWT_HOST not in request.url:
                    return
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer ") and not jwt_token:
                    jwt_token.append(auth[len("Bearer "):])
                    logger.info("bci_jwt_captured", url_prefix=request.url[:80])
                if request.method == "POST":
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

            page.on("request", capture_request)

            try:
                progress("Abriendo sitio del banco...")
                await self._login(
                    page, credentials.rut, credentials.password, jwt_token, progress
                )

                progress("Capturando token de sesión...")
                await self._navigate_to_accounts_menu(page)

                for _ in range(20):
                    if jwt_token:
                        break
                    await asyncio.sleep(0.5)

                if not jwt_token:
                    raise RecoverableIngestionError(
                        "No se capturó el JWT de BCI — la navegación al menú "
                        "de cuentas no disparó la request esperada."
                    )

                jwt = jwt_token[0]

                progress("Listando cuentas...")
                accounts = await self._list_accounts(
                    page, jwt, credentials.rut, captured_bodies
                )
                if not accounts:
                    raise RecoverableIngestionError("BCI no devolvió cuentas")

                progress(f"Extrayendo movimientos de {len(accounts)} cuenta(s)...")
                all_movs: list[CanonicalMovement] = []
                first_balance: int | None = None

                for acct in accounts:
                    numero = str(acct.get("numero") or "")
                    tipo = str(acct.get("tipo") or "CCT")

                    balance = await self._fetch_balance(page, jwt, numero, tipo)
                    if first_balance is None and balance is not None:
                        first_balance = balance

                    movs_raw = await self._fetch_movements(
                        page, jwt, numero, tipo, captured_bodies
                    )
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

    # ── Navegación al menú de cuentas ────────────────────────────────────────

    async def _navigate_to_accounts_menu(self, page: Page) -> None:
        """Clickea "Saldos y movimientos" → el frontend dispara las requests con
        el JWT Bearer Y los bodies POST que el listener captura."""
        clicked = await page.evaluate(
            """(keywords) => {
                for (const el of Array.from(document.querySelectorAll("a, button, li, span"))) {
                    const text = el.innerText?.trim().toLowerCase() || "";
                    if (keywords.some((kw) => text === kw || text.startsWith(kw))) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }""",
            ACCOUNTS_MENU_TEXT,
        )
        if clicked:
            logger.info("bci_navigate_via_menu_click")
            await asyncio.sleep(4)
        else:
            logger.warning("bci_accounts_menu_not_found")
            await asyncio.sleep(2)

    # ── API REST con JWT Bearer ───────────────────────────────────────────────

    async def _api_post(self, page: Page, jwt: str, path: str, body: dict) -> Any:
        return await page.evaluate(
            """async ([url, jwt, bodyStr]) => {
                const r = await fetch(url, {
                    method: "POST",
                    credentials: "include",
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Authorization": `Bearer ${jwt}`,
                    },
                    body: bodyStr,
                    referrer: window.location.href,
                });
                if (!r.ok) {
                    const text = await r.text().catch(() => "");
                    throw new Error(`POST ${url} -> ${r.status} :: ${text.slice(0, 200)}`);
                }
                return r.json();
            }""",
            [f"{BCI_API_BASE}/{path}", jwt, json.dumps(body)],
        )

    async def _list_accounts(
        self, page: Page, jwt: str, rut: str, captured: dict[str, str]
    ) -> list[dict]:
        """POST cuentas-busquedas/por-rut → lista de cuentas.

        El body lo conoce el frontend (capture-and-replay); si no se capturó,
        fallback a {rut, dig} (BCI parte el RUT así en el propio form de login).
        """
        body = self._body_for(captured, ACCOUNTS_PATH, self._accounts_fallback_body(rut))
        raw = await self._api_post(page, jwt, ACCOUNTS_PATH, body)
        if isinstance(raw, dict):
            cuentas = raw.get("cuentas", [])
            return cuentas if isinstance(cuentas, list) else []
        return raw if isinstance(raw, list) else []

    async def _fetch_balance(
        self, page: Page, jwt: str, numero: str, tipo: str
    ) -> int | None:
        """POST cuentas-busquedas/por-numero-cuenta → saldoContable (fallback
        saldoDisponible). Body conocido: {numero, tipo}."""
        if not numero:
            return None
        try:
            data = await self._api_post(
                page, jwt, BALANCE_PATH, {"numero": numero, "tipo": tipo}
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
        self, page: Page, jwt: str, numero: str, tipo: str, captured: dict[str, str]
    ) -> list[dict]:
        """POST cuentas-movimientos/por-numero-cuenta → movimientos.

        El body se replica de la plantilla capturada y se le overlaya
        {numero, tipo} por cuenta (preserva campos extra como paginación/rango);
        fallback {numero, tipo} si no hubo captura.
        """
        template = self._body_for(captured, MOVEMENTS_PATH, {})
        body = dict(template) if isinstance(template, dict) else {}
        body.update({"numero": numero, "tipo": tipo})
        try:
            raw = await self._api_post(page, jwt, MOVEMENTS_PATH, body)
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

    def _accounts_fallback_body(self, rut: str) -> dict:
        """Fallback {rut, dig} para por-rut cuando no se capturó el body real."""
        clean = re.sub(r"[.\-]", "", rut).upper()
        if len(clean) < 2:
            return {"rut": clean}
        return {"rut": clean[:-1], "dig": clean[-1]}

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
        html = re.sub(r"\b\d{7,10}\b", "[digits]", html)
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
