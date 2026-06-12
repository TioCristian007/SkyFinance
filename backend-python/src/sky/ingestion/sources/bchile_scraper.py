"""
sky.ingestion.sources.bchile_scraper — Scraper Banco de Chile (Playwright).

ESTRATEGIA:
    Después del login (browser), BChile expone APIs REST internas en
    /mibancochile/rest/persona/. El scraper usa esas APIs vía page.evaluate()
    con el token XSRF de las cookies de sesión. Eso es MUCHO más estable
    que scrapear HTML — no depende de cómo bchile renderice su frontend.

FLUJO:
    1. goto portal
    2. fill RUT + password → submit
    3. detectar 2FA (keywords en texto) → esperar aprobación con timeout
    4. API: GET productos + datos cliente
    5. API: GET balance
    6. API: POST getCartola (movimientos cuenta, con paginación)
    7. API: POST tarjeta-credito-digital (movimientos TC)
    8. Normalizar a CanonicalMovement con build_external_id determinístico

SYNC INCREMENTAL:
    fetch() acepta `since: date`. Si se provee, corta paginación al ver
    movimientos anteriores a esa fecha. Reduce duplicados y trabajo repetido.
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

from playwright.async_api import Page

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
from sky.ingestion.parsers.bchile_parser import normalize_date

logger = get_logger("bchile_scraper")

BANK_URL = "https://portalpersonas.bancochile.cl/persona/"
API_BASE = "https://portalpersonas.bancochile.cl/mibancochile/rest/persona"
# Dominio Auth0 del login post-migración (B-7). Mientras la URL siga aquí,
# el login NO terminó: o hay error, o hay 2FA pendiente, o el form no avanzó.
LOGIN_DOMAIN = "login.portales.bancochile.cl"

RUT_SELECTORS = [
    "#ppriv_per-login-click-input-rut",
    'input[name="userRut"]',
    "#rut",
    'input[name="rut"]',
    'input[placeholder*="RUT"]',
]
PASS_SELECTORS = [
    "#ppriv_per-login-click-input-password",
    'input[name="userPassword"]',
    "#pass",
    "#password",
    'input[type="password"]',
]
SUBMIT_SELECTORS = [
    "#ppriv_per-login-click-ingresar-login",
    'button[type="submit"]',
    "#btn-login",
    "#btn_login",
]

# Detección POSITIVA de la pantalla 2FA. Dos generaciones de portal con
# listas SEPARADAS a propósito:
#   · CLASSIC — portal pre-Auth0. Es la lista del flujo verificado en prod
#     2026-06-12 y la ÚNICA que corre post-login sobre portalpersonas (el
#     dashboard podría mencionar "notificación"/"app" en marketing y un falso
#     positivo ahí colgaría el sync 120s).
#   · AUTH0 — challenge "aprueba en tu app" (Banco de Chile Pass) dentro de
#     login.portales.bancochile.cl. Solo se evalúa mientras la URL siga en el
#     dominio de login (_post_submit_flow). Frases compuestas a propósito —
#     palabras sueltas como "app" o "aprueba" matchearían el marketing del
#     propio form. Cuando un tester real dispare el 2FA, la captura debug
#     (pii_safe) trae el DOM para refinar esta lista.
TWO_FA_KEYWORDS_CLASSIC = [
    "clave dinámica",
    "clave dinamica",
    "superclave",
    "segundo factor",
    "código de verificación",
    "codigo de verificacion",
    "ingresa tu token",
    "aprobar en tu app",
    "digital pass",
    "bchile pass",
]
TWO_FA_KEYWORDS_AUTH0 = [
    "banco de chile pass",
    "aprueba el ingreso",
    "aprueba la notificación",
    "aprueba la notificacion",
    "aprueba desde tu app",
    "aprueba en tu app",
    "te enviamos una notificación",
    "te enviamos una notificacion",
    "notificación a tu celular",
    "notificacion a tu celular",
    "notificación push",
    "notificacion push",
    "autoriza el ingreso",
    "autoriza esta operación",
    "autoriza esta operacion",
    "revisa tu app",
    "verificación adicional",
    "verificacion adicional",
]
TWO_FA_KEYWORDS = TWO_FA_KEYWORDS_CLASSIC + TWO_FA_KEYWORDS_AUTH0
LOGIN_ERROR_KEYWORDS = [
    "clave incorrecta",
    # Mensaje real del portal Auth0 post-migración: "Los datos ingresados no
    # son correctos". Solo se busca dentro de elementos error/alert, así que
    # el fragmento corto no produce falsos positivos.
    "no son correctos",
    "rut inválido",
    "rut invalido",
    "bloqueada",
    "bloqueado",
    "suspendida",
    "sesión activa",
    "sesion activa",
]
REJECTION_KEYWORDS = ["rechazad", "denegad", "cancelad"]


class BChileScraperSource(DataSource):
    """DataSource para Banco de Chile vía Playwright + REST interna."""

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
        return "scraper.bchile"

    @property
    def source_kind(self) -> SourceKind:
        return SourceKind.SCRAPER

    @property
    def supported_banks(self) -> list[str]:
        return ["bchile"]

    def capabilities(self) -> IngestionCapabilities:
        return IngestionCapabilities(
            typical_latency_ms=180_000,
            estimated_failure_rate=0.15,
            supports_backfill=True,
            backfill_days=90,
            provides_credit_card=True,
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
            raise ValueError("BChile requiere BankCredentials (RUT + password)")

        progress = on_progress or (lambda s: None)
        started_at = datetime.now()
        pool = get_browser_pool()

        async with pool.acquire() as context:
            page = await context.new_page()

            try:
                progress("Abriendo sitio del banco...")
                await self._login(page, credentials.rut, credentials.password, progress)

                await self._close_popups(page)

                progress("Obteniendo productos y datos del cliente...")
                products = await self._api_get(
                    page, "selectorproductos/selectorProductos/obtenerProductos?incluirTarjetas=true"
                )
                client_data = await self._api_get(page, "bff-ppersonas-clientes/clientes/")

                balance_clp = await self._fetch_balance(page)
                full_name = products.get("nombre") or self._build_full_name(client_data)

                progress("Extrayendo movimientos de cuenta...")
                account_movs, acc_balance = await self._fetch_account_movements(
                    page, products.get("productos", []), full_name, credentials.rut, since
                )
                if balance_clp is None:
                    balance_clp = acc_balance

                progress("Extrayendo datos de tarjeta de crédito...")
                cc_movs = await self._fetch_credit_card_movements(page, full_name, since)

                all_movs = self._deduplicate(account_movs + cc_movs)

                progress(f"Listo — {len(all_movs)} movimientos")
                elapsed_ms = int((datetime.now() - started_at).total_seconds() * 1000)

                return IngestionResult(
                    balance=AccountBalance(balance_clp=balance_clp or 0, as_of=datetime.now())
                    if balance_clp is not None
                    else None,
                    movements=all_movs,
                    source_kind=SourceKind.SCRAPER,
                    source_identifier=self.source_identifier,
                    elapsed_ms=elapsed_ms,
                    metadata={"account_count": len(account_movs), "credit_card_count": len(cc_movs)},
                )

            except (AuthenticationError, TwoFactorTimeoutError, FieldFillError):
                raise
            except Exception as exc:
                logger.error("bchile_fetch_failed", error=str(exc), tb=traceback.format_exc())
                raise RecoverableIngestionError(f"Scraper falló: {exc}") from exc

    # ── Login ────────────────────────────────────────────────────────────────

    async def _login(self, page: Page, rut: str, password: str, progress: ProgressCallback) -> None:
        await page.goto(BANK_URL, wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(3)

        formatted_rut = self._format_rut(rut)
        clean_rut = re.sub(r"[.\-]", "", rut)

        rut_fill = await self._fill_rut(page, formatted_rut, clean_rut)
        if not rut_fill:
            await self._capture_debug(page, "fill_rut_failed")
            raise RecoverableIngestionError("No se encontró el campo de RUT")

        await asyncio.sleep(0.5)

        pass_selector = await self._fill_password(page, password)
        if not pass_selector:
            await self._capture_debug(page, "fill_password_failed")
            raise RecoverableIngestionError("No se encontró el campo de clave")

        rut_selector, rut_typed = rut_fill
        await self._verify_login_fields(page, rut_selector, rut_typed, pass_selector, password)

        progress("Enviando credenciales...")
        submitted = False
        for sel in SUBMIT_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    submitted = True
                    break
            except Exception:
                continue

        if not submitted:
            await page.evaluate("""() => {
                for (const btn of Array.from(document.querySelectorAll("button, a, input[type='submit']"))) {
                    const text = btn.innerText?.trim().toLowerCase() || "";
                    if (text.includes("ingresar") || text.includes("continuar")) {
                        btn.click();
                        return;
                    }
                }
            }""")

        # BChile hace múltiples redirects post-submit: dejar que el DOM asiente
        # antes de empezar a leer señales.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=25_000)
        except Exception:
            pass
        await asyncio.sleep(2)

        # Resolver el estado post-submit en el dominio Auth0: éxito (la URL
        # sale del dominio), error del banco, challenge 2FA o form pegado.
        await self._post_submit_flow(page, progress)

        # Dar tiempo a portalpersonas a asentarse (la SPA inicializa tokens
        # de sesión). Mismo settle que el flujo verificado en prod 2026-06-12.
        await asyncio.sleep(5)
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        await asyncio.sleep(2)

        # Portal clásico: el 2FA podía aparecer DESPUÉS de salir del login
        # (en portalpersonas). Se mantiene ese camino tal cual.
        is_2fa = await self._retry_dom_read(lambda: self._detect_2fa(page), retries=3)
        if is_2fa:
            progress(f"{PROGRESS_2FA_WAIT_PREFIX} en tu app Banco de Chile...")
            if not await self._wait_for_2fa(page, progress):
                raise TwoFactorTimeoutError(
                    "Timeout esperando aprobación 2FA. "
                    "Abre tu app Banco de Chile y aprueba cuando inicies el sync."
                )

        progress(PROGRESS_LOGIN_OK)

    async def _retry_dom_read(self, fn, retries: int = 3):
        """
        Reintenta lecturas de DOM si el execution context se destruye
        por navegación. Común en SPAs con redirects tardíos post-login.
        """
        last_exc = None
        for _ in range(retries):
            try:
                return await fn()
            except Exception as exc:
                if "execution context was destroyed" in str(exc).lower():
                    last_exc = exc
                    await asyncio.sleep(2)
                    continue
                raise
        if last_exc:
            raise last_exc
        return None

    async def _post_submit_flow(self, page: Page, progress: ProgressCallback) -> None:
        """Resuelve el estado post-submit en el dominio Auth0 (sprint testers 2026-06-12).

        Poll cada `_poll_interval_sec` con cuatro salidas posibles:
          · La URL sale de LOGIN_DOMAIN → login OK (return).
          · Mensaje de error del banco (LOGIN_ERROR_KEYWORDS) en CUALQUIER tick
            → AuthenticationError. Los mensajes pueden aparecer tarde; antes
            solo se chequeaban una vez.
          · Pantalla 2FA detectada POSITIVAMENTE (TWO_FA_KEYWORDS) → modo
            espera con el timeout 2FA completo y progreso visible al usuario.
          · Sin señales tras `_post_submit_grace_sec`: si el form de clave
            DESAPARECIÓ, se asume un challenge 2FA con texto desconocido
            (espera + captura debug para refinar keywords); si el form sigue
            visible, el submit no avanzó → RecoverableIngestionError.

        REGLA (la razón de ser de este método): la ambigüedad JAMÁS se castiga
        como AuthenticationError — eso mandaría la cuenta a needs_reconnection
        (hard-stop B2) con la clave buena, exactamente el falso "credenciales
        rechazadas" que destruyó la confianza en la era B-7. Clave mala se
        declara SOLO con el mensaje del banco en pantalla.
        """
        start = datetime.now()
        two_fa_started: datetime | None = None
        last_progress_emit = 0.0

        while True:
            if LOGIN_DOMAIN not in page.url:
                return  # éxito: Auth0 redirigió a portalpersonas

            # Lecturas de DOM tolerantes: una navegación en curso destruye el
            # execution context — ese tick se pierde y la URL decide el próximo.
            try:
                login_error = await self._check_login_error(page)
            except Exception:
                login_error = None
            if login_error:
                logger.warning(
                    "bchile_auth_error", reason="check_login_error", detail=login_error[:200]
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
                    logger.info("bchile_2fa_detected", positive=True, url=page.url)
                    progress(f"{PROGRESS_2FA_WAIT_PREFIX} en tu app Banco de Chile...")
                    await self._capture_debug(page, "2fa_screen", pii_safe=True)
                elif elapsed >= self._post_submit_grace_sec:
                    if await self._password_field_present(page):
                        # Form completo en pantalla, sin error y sin redirect:
                        # el submit no avanzó. Posible challenge anti-bot.
                        logger.warning("bchile_post_submit_stuck", url=page.url)
                        await self._capture_debug(page, "post_submit_form_stuck", pii_safe=True)
                        raise RecoverableIngestionError(
                            "El formulario de login no avanzó tras el envío "
                            "(posible challenge anti-bot)"
                        )
                    # El form desapareció pero seguimos en el dominio de login:
                    # lo más probable es un challenge 2FA con texto que aún no
                    # conocemos. Beneficio de la duda + captura para refinar.
                    two_fa_started = datetime.now()
                    logger.warning(
                        "bchile_2fa_assumed", reason="unrecognized_screen", url=page.url
                    )
                    progress(f"{PROGRESS_2FA_WAIT_PREFIX} en tu app Banco de Chile...")
                    await self._capture_debug(page, "2fa_unrecognized_screen", pii_safe=True)

            if two_fa_started is not None:
                if any(kw in body_text for kw in REJECTION_KEYWORDS):
                    logger.info("bchile_2fa_rejected")
                    raise TwoFactorTimeoutError(
                        "La aprobación 2FA fue rechazada o cancelada. "
                        "Reintenta el sync y aprueba la notificación en tu app."
                    )
                elapsed_2fa = (datetime.now() - two_fa_started).total_seconds()
                if elapsed_2fa >= self._timeout_sec:
                    logger.warning("bchile_2fa_timeout", timeout_sec=self._timeout_sec)
                    await self._capture_debug(page, "2fa_timeout", pii_safe=True)
                    raise TwoFactorTimeoutError(
                        "Timeout esperando aprobación 2FA. "
                        "Abre tu app Banco de Chile y aprueba cuando inicies el sync."
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

        El challenge 2FA de Auth0 reemplaza el form — si el campo de clave
        sigue presente, lo que vemos NO es un 2FA sino el form pegado.
        """
        for sel in PASS_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el:
                    return True
            except Exception:
                continue
        return False

    async def _fill_rut(self, page: Page, formatted: str, clean: str) -> tuple[str, str] | None:
        """Llena el RUT con type() — SE QUEDA con type().

        El input tiene la directiva Angular `delete-zero-left` que requiere
        keystrokes reales; cambiarlo a fill() lo rompe (error del commit 6fdae84).

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
        clave incorrecta (causa raíz del sprint 2026-06-12). El campo password
        NO tiene `delete-zero-left` (esa directiva es exclusiva del RUT), así
        que fill() es seguro aquí.

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
        mayúsculas y sin ceros a la izquierda (delete-zero-left los elimina)."""
        return re.sub(r"[.\-\s]", "", value or "").upper().lstrip("0")

    async def _verify_login_fields(
        self, page: Page, rut_selector: str, rut_typed: str, pass_selector: str, password: str
    ) -> None:
        """Verificación post-fill (keystone del sprint 2026-06-12).

        Lee de vuelta input.value de RUT y clave ANTES del submit y compara con
        lo que se quiso escribir. Un mismatch significa que el valor correcto
        nunca va a llegar al banco — eso es FieldFillError (técnico, recoverable),
        no AuthenticationError. RUT se compara normalizado (el sitio reformatea
        con puntos/guion); la clave, exacta.

        PII: jamás se loguean los valores — solo longitudes (doctrina §20).
        Tampoco se captura debug acá: el form ya tiene el RUT en pantalla.
        """
        values = await page.evaluate(
            """(sels) => sels.map((s) => {
                const el = document.querySelector(s);
                return el ? el.value : null;
            })""",
            [rut_selector, pass_selector],
        )
        rut_value, pass_value = values[0], values[1]

        if self._normalize_rut_value(rut_value or "") != self._normalize_rut_value(rut_typed):
            logger.warning(
                "bchile_field_mismatch", field="rut",
                expected_len=len(rut_typed), got_len=len(rut_value or ""),
            )
            raise FieldFillError("rut", expected_len=len(rut_typed), got_len=len(rut_value or ""))

        if pass_value != password:
            logger.warning(
                "bchile_field_mismatch", field="password",
                expected_len=len(password), got_len=len(pass_value or ""),
            )
            raise FieldFillError(
                "password", expected_len=len(password), got_len=len(pass_value or "")
            )

        logger.info("bchile_fields_verified", rut_len=len(rut_typed), password_len=len(password))

    async def _check_login_error(self, page: Page) -> str | None:
        return await page.evaluate(
            """(keywords) => {
                for (const sel of ['[class*="error"]', '[class*="alert"]', '[role="alert"]']) {
                    for (const el of document.querySelectorAll(sel)) {
                        const text = el.innerText?.trim();
                        if (text && keywords.some((kw) => text.toLowerCase().includes(kw))) {
                            return text;
                        }
                    }
                }
                return null;
            }""",
            LOGIN_ERROR_KEYWORDS,
        )

    async def _detect_2fa(self, page: Page) -> bool:
        """2FA del portal clásico, post-login. SOLO keywords clásicas: el
        dashboard de portalpersonas puede mencionar "app"/"notificación" en
        marketing y un falso positivo acá colgaría el sync 120s."""
        text = await page.evaluate("() => (document.body?.innerText || '').toLowerCase()")
        return self._match_2fa_text(text, TWO_FA_KEYWORDS_CLASSIC)

    async def _wait_for_2fa(self, page: Page, progress: ProgressCallback) -> bool:
        """Espera 2FA del portal clásico: aprobado = las keywords desaparecen."""
        start = datetime.now()
        while (elapsed := int((datetime.now() - start).total_seconds())) < self._timeout_sec:
            text = await page.evaluate("() => (document.body?.innerText || '').toLowerCase()")

            if any(kw in text for kw in REJECTION_KEYWORDS):
                logger.info("bchile_2fa_rejected")
                return False

            if not self._match_2fa_text(text, TWO_FA_KEYWORDS_CLASSIC):
                logger.info("bchile_2fa_approved", elapsed_sec=elapsed)
                return True

            if elapsed > 0 and elapsed % 15 == 0:
                remaining = self._timeout_sec - elapsed
                progress(f"{PROGRESS_2FA_WAIT_PREFIX} ({remaining}s restantes)...")

            await asyncio.sleep(3)

        logger.warning("bchile_2fa_timeout", timeout_sec=self._timeout_sec)
        return False

    async def _close_popups(self, page: Page) -> None:
        try:
            await page.evaluate("""() => {
                const closeBtn = document.querySelector("#modal_emergente_close");
                if (closeBtn) { closeBtn.click(); return; }
                const noMasBtn = document.querySelector(".btn-no-mas");
                if (noMasBtn) noMasBtn.click();
                for (const btn of Array.from(document.querySelectorAll('button, a'))) {
                    const t = btn.innerText?.trim().toLowerCase() || '';
                    if (t === 'cerrar' || t === 'no gracias' || t === 'entendido') btn.click();
                }
            }""")
            await asyncio.sleep(1.5)
        except Exception:
            pass

    # ── API REST interna ─────────────────────────────────────────────────────

    async def _api_get(self, page: Page, path: str) -> Any:
        return await page.evaluate(
            """async (url) => {
                const m = document.cookie.match(/(?:^|;\\s*)XSRF-TOKEN=([^;]*)/);
                const xsrf = m ? decodeURIComponent(m[1]) : "";
                const headers = {
                    "Accept": "application/json, text/plain, */*",
                    "X-Requested-With": "XMLHttpRequest",
                };
                if (xsrf) headers["X-XSRF-TOKEN"] = xsrf;
                const r = await fetch(url, {
                    credentials: "include",
                    headers,
                    referrer: window.location.href,
                });
                if (!r.ok) {
                    const text = await r.text().catch(() => "");
                    throw new Error(`API GET ${url} -> ${r.status} :: ${text.slice(0, 200)}`);
                }
                return r.json();
            }""",
            f"{API_BASE}/{path}",
        )

    async def _api_post(self, page: Page, path: str, body: dict) -> Any:
        return await page.evaluate(
            """async ([url, bodyStr]) => {
                const m = document.cookie.match(/(?:^|;\\s*)XSRF-TOKEN=([^;]*)/);
                const xsrf = m ? decodeURIComponent(m[1]) : "";
                const headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/plain, */*",
                };
                if (xsrf) headers["X-XSRF-TOKEN"] = xsrf;
                const r = await fetch(url, {
                    method: "POST",
                    credentials: "include",
                    headers,
                    body: bodyStr,
                    referrer: window.location.href,
                });
                if (!r.ok) {
                    const text = await r.text().catch(() => "");
                    throw new Error(`API POST ${url} -> ${r.status} :: ${text.slice(0, 200)}`);
                }
                return r.json();
            }""",
            [f"{API_BASE}/{path}", json.dumps(body)],
        )

    async def _fetch_balance(self, page: Page) -> int | None:
        try:
            saldos = await self._api_get(page, "bff-pp-prod-ctas-saldos/productos/cuentas/saldos")
            for s in saldos:
                if s.get("moneda") == "CLP" and s.get("tipo") == "CUENTA_CORRIENTE":
                    return int(s.get("disponible", 0))
        except Exception as exc:
            logger.warning("bchile_balance_fetch_failed", error=str(exc))
        return None

    async def _fetch_account_movements(
        self, page: Page, products: list[dict], full_name: str, rut: str, since: date | None
    ) -> tuple[list[CanonicalMovement], int | None]:
        accounts = [p for p in products if p.get("tipo") in ("cuenta", "cuentaCorrienteMonedaLocal")]
        seen: set[str] = set()
        unique: list[dict] = []
        for a in accounts:
            num = a.get("numero")
            if num and num not in seen:
                seen.add(num)
                unique.append(a)

        if not unique:
            return [], None

        base_url = page.url.split("#")[0]
        # BChile es una SPA con conexiones activas permanentes — "networkidle"
        # nunca se dispara. Usamos "domcontentloaded" (mucho más rápido) y
        # después damos un sleep generoso para que la SPA pinte.
        await page.goto(
            f"{base_url}#/movimientos/cuenta/saldos-movimientos",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        # BChile inicializa tokens específicos de movimientos al montar la vista.
        # Sin este wait, getCartola devuelve 403.
        await asyncio.sleep(8)

        all_movs: list[CanonicalMovement] = []
        first_balance: int | None = None

        for acct in unique:
            # BChile espera el RUT sin puntos, con guion: "22141522-1"
            rut_clean = re.sub(r"[.]", "", rut).upper()
            if "-" not in rut_clean and len(rut_clean) >= 2:
                rut_clean = f"{rut_clean[:-1]}-{rut_clean[-1]}"

            cuenta = {
                "nombreCliente": full_name,
                "rutCliente": rut_clean,
                "numero": acct.get("numero"),
                "mascara": acct.get("mascara"),
                "selected": True,
                "codigoProducto": acct.get("codigo"),
                "claseCuenta": acct.get("claseCuenta"),
                "moneda": acct.get("codigoMoneda"),
            }

            try:
                await self._api_post(
                    page, "movimientos/getConfigConsultaMovimientos",
                    {"cuentasSeleccionadas": [cuenta]},
                )
                cartola = await self._api_post(
                    page,
                    "bff-pper-prd-cta-movimientos/movimientos/getCartola",
                    {"cuentaSeleccionada": cuenta, "cabecera": {"statusGenerico": True, "paginacionDesde": 1}},
                )

                movs_raw = cartola.get("movimientos", [])
                stop_paginating = False
                for mov in movs_raw:
                    cm = self._cartola_to_canonical(mov, "bchile")
                    if cm is None:
                        continue
                    if since and cm.occurred_at < since:
                        stop_paginating = True
                        continue
                    all_movs.append(cm)

                if first_balance is None and acct.get("codigoMoneda") == "CLP" and movs_raw:
                    first_balance = int(movs_raw[0].get("saldo", 0))

                has_more = bool(movs_raw) and cartola.get("pagina", [{}])[0].get("masPaginas", False)
                offset = 1 + len(movs_raw)

                for _ in range(2, 26):
                    if not has_more or stop_paginating:
                        break
                    try:
                        nxt = await self._api_post(
                            page,
                            "bff-pper-prd-cta-movimientos/movimientos/getCartola",
                            {"cuentaSeleccionada": cuenta, "cabecera": {"statusGenerico": True, "paginacionDesde": offset}},
                        )
                        nxt_movs = nxt.get("movimientos", [])
                        if not nxt_movs:
                            break
                        for mov in nxt_movs:
                            cm = self._cartola_to_canonical(mov, "bchile")
                            if cm is None:
                                continue
                            if since and cm.occurred_at < since:
                                stop_paginating = True
                                break
                            all_movs.append(cm)
                        offset += len(nxt_movs)
                        has_more = nxt.get("pagina", [{}])[0].get("masPaginas", False)
                    except Exception:
                        break

            except Exception as exc:
                logger.warning("bchile_account_fetch_failed", error=str(exc))

        return all_movs, first_balance

    async def _fetch_credit_card_movements(
        self, page: Page, full_name: str, since: date | None
    ) -> list[CanonicalMovement]:
        movements: list[CanonicalMovement] = []
        try:
            cards = await self._api_post(page, "tarjetas/widget/informacion-tarjetas", {})
        except Exception:
            return movements
        if not cards:
            return movements

        for card in cards:
            mascara_raw = card.get("numero", "")
            mascara = (
                f"****{mascara_raw[-4:]}"
                if len(mascara_raw.replace("*", "")) <= 4
                else mascara_raw
            )
            base_body = {
                "idTarjeta": card.get("idProducto"),
                "codigoProducto": "TNM",
                "tipoTarjeta": f"{card.get('marca', '')} {card.get('tipo', '')}".strip(),
                "mascara": mascara,
                "nombreTitular": full_name,
            }
            body = {**base_body, "tipoCliente": "T"}

            try:
                no_fact = await self._api_post(
                    page, "tarjeta-credito-digital/movimientos-no-facturados", body
                )
                lista_mov = no_fact.get("listaMovNoFactur", [])
                for mov in lista_mov:
                    cm = self._cc_unbilled_to_canonical(mov, "bchile")
                    if cm is None:
                        continue
                    if since and cm.occurred_at < since:
                        continue
                    movements.append(cm)
            except Exception as exc:
                logger.warning("bchile_cc_unbilled_failed", error=str(exc))

        return movements

    # ── Conversión a CanonicalMovement ───────────────────────────────────────

    def _cartola_to_canonical(self, mov: dict, bank_id: str) -> CanonicalMovement | None:
        amount_raw = int(mov.get("monto", 0))
        amount = -abs(amount_raw) if mov.get("tipo") == "cargo" else abs(amount_raw)
        desc = (mov.get("descripcion") or "").strip()
        # fechaContable ("DD/MM/YYYY") es la fuente primaria; fechaContableMovimiento (epoch ms) como fallback.
        occurred = normalize_date(mov.get("fechaContable")) or normalize_date(mov.get("fechaContableMovimiento"))
        if occurred is None:
            logger.warning("bchile_mov_invalid_date_skipped", mov_id=mov.get("id"))
            return None
        native_id = (mov.get("id") or "").strip() or None
        balance_val = mov.get("saldo")
        balance = int(balance_val) if balance_val is not None else None
        return CanonicalMovement(
            external_id=build_external_id(
                bank_id, occurred, amount, desc, MovementSource.ACCOUNT,
                native_id=native_id, balance=balance,
            ),
            amount_clp=amount,
            raw_description=desc,
            occurred_at=occurred,
            movement_source=MovementSource.ACCOUNT,
            source_kind=SourceKind.SCRAPER,
            source_metadata={"balance_after": balance, "native_id": native_id},
        )

    def _cc_unbilled_to_canonical(self, mov: dict, bank_id: str) -> CanonicalMovement | None:
        raw_amount = int(mov.get("montoCompra", 0))
        amount = -abs(raw_amount) if raw_amount > 0 else abs(raw_amount)
        desc = (mov.get("glosaTransaccion") or "").strip()
        occurred = normalize_date(mov.get("fechaTransaccionString"))
        if occurred is None:
            logger.warning("bchile_cc_mov_invalid_date_skipped", mov_id=mov.get("id"))
            return None
        native_id = (mov.get("id") or "").strip() or None
        return CanonicalMovement(
            external_id=build_external_id(
                bank_id, occurred, amount, desc, MovementSource.CREDIT_CARD,
                native_id=native_id,
            ),
            amount_clp=amount,
            raw_description=desc,
            occurred_at=occurred,
            movement_source=MovementSource.CREDIT_CARD,
            source_kind=SourceKind.SCRAPER,
            source_metadata={"status": "unbilled", "installments": mov.get("despliegueCuotas"), "native_id": native_id},
        )

    def _deduplicate(self, movs: list[CanonicalMovement]) -> list[CanonicalMovement]:
        seen: set[str] = set()
        out: list[CanonicalMovement] = []
        for m in movs:
            if m.external_id in seen:
                continue
            seen.add(m.external_id)
            out.append(m)
        return out

    async def _capture_debug(self, page: Page, label: str, *, pii_safe: bool = False) -> None:
        """Captura el estado actual de la página si scraper_debug_capture=True.

        Dos modos:
          · pii_safe=False — screenshot + HTML crudos. SOLO para estados
            pre-fill (campo no encontrado): ahí el form está vacío y no hay PII.
          · pii_safe=True — SOLO HTML scrubeado (_scrub_pii): valores de inputs
            y RUTs redactados. Un screenshot no se puede sanitizar y los estados
            post-submit (error de login, pantalla 2FA) pueden mostrar el RUT en
            pantalla (doctrina §20). Es el modo de las capturas 2FA del sprint
            testers — el material para refinar TWO_FA_KEYWORDS cuando un tester
            real dispare el challenge.

        C3 (sprint 2026-06-12): si scraper_debug_bucket está configurado, la
        captura además se sube a Supabase Storage — el filesystem del contenedor
        es efímero y las capturas morían con cada deploy.
        """
        if not settings.scraper_debug_capture:
            return
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_dir = settings.scraper_debug_dir or tempfile.gettempdir()
            stem = f"bchile_{label}_{ts}"
            html_path = os.path.join(base_dir, f"{stem}.html")
            files: list[tuple[str, str, str]] = []

            if not pii_safe:
                screenshot_path = os.path.join(base_dir, f"{stem}.png")
                await page.screenshot(path=screenshot_path)
                files.append((f"bchile/{stem}.png", screenshot_path, "image/png"))

            content = await page.content()
            if pii_safe:
                content = self._scrub_pii(content)
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            files.append((f"bchile/{stem}.html", html_path, "text/html"))
            logger.info("scraper_debug_captured", label=label, pii_safe=pii_safe, html=html_path)

            if settings.scraper_debug_bucket:
                await self._upload_debug_capture(settings.scraper_debug_bucket, files)
        except Exception as exc:
            logger.warning("scraper_debug_capture_failed", error=str(exc))

    @staticmethod
    def _scrub_pii(html: str) -> str:
        """Redacta PII del HTML capturado antes de persistirlo (doctrina §20).

        Cubre: valores de inputs serializados (value="..."), RUTs con formato
        (12.345.678-9 y variantes) y cualquier corrida larga de dígitos
        (RUT sin formato, números de cuenta/teléfono). Agresivo a propósito:
        en una captura debug sobra redactar de más, jamás de menos.
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

        Bucket privado, service_role only (doctrina §15). Sin TTL nativo en
        Supabase: la purga es manual o por job — documentado en el runbook.
        El cliente es sync, así que corre en thread para no bloquear el loop.
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
            logger.info(
                "scraper_debug_uploaded", bucket=bucket, files=[k for k, _, _ in files]
            )
        except Exception as exc:
            logger.warning("scraper_debug_upload_failed", error=str(exc))

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

    def _build_full_name(self, client_data: dict) -> str:
        datos = client_data.get("datosCliente", {})
        return f"{datos.get('nombres', '')} {datos.get('apellidoPaterno', '')}".strip()
