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
import re
from datetime import date, datetime
from typing import Any

from playwright.async_api import Page

from sky.core.logging import get_logger
from sky.ingestion.browser_pool import get_browser_pool
from sky.ingestion.contracts import (
    AccountBalance,
    AuthenticationError,
    BankCredentials,
    CanonicalMovement,
    DataSource,
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

TWO_FA_KEYWORDS = [
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
LOGIN_ERROR_KEYWORDS = [
    "clave incorrecta",
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

    def __init__(self, two_fa_timeout_sec: int = 120):
        self._timeout_sec = two_fa_timeout_sec

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

            except (AuthenticationError, TwoFactorTimeoutError):
                raise
            except Exception as exc:
                logger.error("bchile_fetch_failed", error=str(exc))
                raise RecoverableIngestionError(f"Scraper falló: {exc}") from exc

    # ── Login ────────────────────────────────────────────────────────────────

    async def _login(self, page: Page, rut: str, password: str, progress: ProgressCallback) -> None:
        await page.goto(BANK_URL, wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(3)

        formatted_rut = self._format_rut(rut)
        clean_rut = re.sub(r"[.\-]", "", rut)

        if not await self._fill_rut(page, formatted_rut, clean_rut):
            raise RecoverableIngestionError("No se encontró el campo de RUT")

        await asyncio.sleep(0.5)

        if not await self._fill_password(page, password):
            raise RecoverableIngestionError("No se encontró el campo de clave")

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

        # BChile hace múltiples redirects post-submit. Esperamos doble:
        # primero DOM listo, luego networkidle. Sin esto el context se
        # destruye mientras intentamos leer el DOM.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=25_000)
        except Exception:
            pass
        await asyncio.sleep(5)
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        await asyncio.sleep(2)

        # Retry wrapper por si aún hay navegaciones tardías
        login_error = await self._retry_dom_read(
            lambda: self._check_login_error(page), retries=3
        )
        if login_error:
            raise AuthenticationError(f"Error de login: {login_error}")

        is_2fa = await self._retry_dom_read(lambda: self._detect_2fa(page), retries=3)
        if is_2fa:
            progress("⏳ Esperando aprobación 2FA en tu app Banco de Chile...")
            if not await self._wait_for_2fa(page, progress):
                raise TwoFactorTimeoutError(
                    "Timeout esperando aprobación 2FA. "
                    "Abre tu app Banco de Chile y aprueba cuando inicies el sync."
                )

        if "/login" in page.url:
            raise AuthenticationError("Login falló — aún en página de login")

        progress("Sesión iniciada correctamente")

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

    async def _fill_rut(self, page: Page, formatted: str, clean: str) -> bool:
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
                return True
            except Exception:
                continue
        return False

    async def _fill_password(self, page: Page, password: str) -> bool:
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
                await el.click()
                await el.type(password, delay=45)
                return True
            except Exception:
                continue
        return False

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
        text = await page.evaluate("() => (document.body?.innerText || '').toLowerCase()")
        return any(kw in text for kw in TWO_FA_KEYWORDS)

    async def _wait_for_2fa(self, page: Page, progress: ProgressCallback) -> bool:
        start = datetime.now()
        while (elapsed := int((datetime.now() - start).total_seconds())) < self._timeout_sec:
            text = await page.evaluate("() => (document.body?.innerText || '').toLowerCase()")

            if any(kw in text for kw in REJECTION_KEYWORDS):
                logger.info("bchile_2fa_rejected")
                return False

            if not any(kw in text for kw in TWO_FA_KEYWORDS):
                logger.info("bchile_2fa_approved", elapsed_sec=elapsed)
                return True

            if elapsed > 0 and elapsed % 15 == 0:
                remaining = self._timeout_sec - elapsed
                progress(f"⏳ Esperando aprobación 2FA ({remaining}s restantes)...")

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

        import json as _json
        for acct in unique:
            # LOG temporal para debugging — ver qué campos viene desde BChile
            logger.info("bchile_account_raw", producto=_json.dumps(acct, default=str)[:500])

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
            logger.info("bchile_account_cuenta_payload", cuenta=_json.dumps(cuenta, default=str))

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
                for mov in no_fact.get("listaMovNoFactur", []):
                    cm = self._cc_unbilled_to_canonical(mov, "bchile")
                    if since and cm.occurred_at < since:
                        continue
                    movements.append(cm)
            except Exception as exc:
                logger.warning("bchile_cc_unbilled_failed", error=str(exc))

        return movements

    # ── Conversión a CanonicalMovement ───────────────────────────────────────

    def _cartola_to_canonical(self, mov: dict, bank_id: str) -> CanonicalMovement:
        amount_raw = int(mov.get("monto", 0))
        amount = -abs(amount_raw) if mov.get("tipo") == "cargo" else abs(amount_raw)
        desc = (mov.get("descripcion") or "").strip()
        occurred = normalize_date(mov.get("fechaContable"))
        return CanonicalMovement(
            external_id=build_external_id(bank_id, occurred, amount, desc, MovementSource.ACCOUNT),
            amount_clp=amount,
            raw_description=desc,
            occurred_at=occurred,
            movement_source=MovementSource.ACCOUNT,
            source_kind=SourceKind.SCRAPER,
            source_metadata={"balance_after": mov.get("saldo")},
        )

    def _cc_unbilled_to_canonical(self, mov: dict, bank_id: str) -> CanonicalMovement:
        raw_amount = int(mov.get("montoCompra", 0))
        amount = -abs(raw_amount) if raw_amount > 0 else abs(raw_amount)
        desc = (mov.get("glosaTransaccion") or "").strip()
        occurred = normalize_date(mov.get("fechaTransaccionString"))
        return CanonicalMovement(
            external_id=build_external_id(bank_id, occurred, amount, desc, MovementSource.CREDIT_CARD),
            amount_clp=amount,
            raw_description=desc,
            occurred_at=occurred,
            movement_source=MovementSource.CREDIT_CARD,
            source_kind=SourceKind.SCRAPER,
            source_metadata={"status": "unbilled", "installments": mov.get("despliegueCuotas")},
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