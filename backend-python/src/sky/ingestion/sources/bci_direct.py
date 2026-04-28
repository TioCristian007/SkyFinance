"""
sky.ingestion.sources.bci_direct — Scraper BCI (Playwright + JWT Bearer).

ESTRATEGIA:
    BCI expone APIs REST internas en apilocal.bci.cl autenticadas con JWT Bearer.
    El scraper hace login en el portal web, navega al menú de cuentas para que
    el frontend dispare las requests con el JWT, lo intercepta del tráfico de red,
    y luego llama directamente a la API sin más navegación.

FLUJO:
    1. goto portal BCI
    2. fill RUT + password → submit
    3. detectar 2FA (app BCI Digital Pass) → esperar aprobación
    4. click en menú "Cuentas" / "Saldos y movimientos"
    5. interceptar JWT Bearer de las requests a apilocal.bci.cl
    6. API: GET /cuentas → lista de cuentas + últimos movimientos
    7. API: POST /cuentas-busquedas/por-numero-cuenta → saldoContable por cuenta
    8. Normalizar a CanonicalMovement con build_external_id determinístico

BALANCE:
    El saldoContable viene del endpoint /cuentas-busquedas/por-numero-cuenta,
    NO del listado /cuentas. Hay que llamarlo explícitamente por cada cuenta
    usando su número y tipo (ej. "CCT" para cuenta corriente).
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime
from typing import Any

from playwright.async_api import Page, Request

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

logger = get_logger("bci_scraper")

BCI_BANK_URL = "https://portalpersonas.bci.cl/mibci/login"
BCI_API_BASE = (
    "https://apilocal.bci.cl/bci-produccion/api-bci"
    "/bff-saldosyultimosmovimientoswebpersonas/v3.2"
)

RUT_SELECTORS = [
    'input[name="rut"]',
    "#rut",
    'input[id*="rut"]',
    'input[placeholder*="RUT"]',
    'input[placeholder*="rut"]',
]
PASS_SELECTORS = [
    'input[type="password"]',
    'input[name="password"]',
    'input[name="clave"]',
    "#password",
    "#clave",
]
SUBMIT_SELECTORS = [
    'button[type="submit"]',
    "#btn-ingresar",
    "#btn-login",
    "#btnIngresar",
]

TWO_FA_KEYWORDS = [
    "digital pass",
    "segundo factor",
    "clave dinámica",
    "clave dinamica",
    "código de verificación",
    "codigo de verificacion",
    "aprobar en tu app",
    "bci pass",
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
    "intentos fallidos",
]
REJECTION_KEYWORDS = ["rechazad", "denegad", "cancelad"]

ACCOUNTS_MENU_TEXT = [
    "saldos y movimientos",
    "mis cuentas",
    "cuentas",
    "saldos",
]


class BCIDirectSource(DataSource):
    """DataSource para BCI vía Playwright + JWT REST."""

    def __init__(self, two_fa_timeout_sec: int = 120):
        self._timeout_sec = two_fa_timeout_sec

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

            jwt_token: list[str] = []

            async def capture_jwt(request: Request) -> None:
                if BCI_API_BASE in request.url:
                    auth = request.headers.get("authorization", "")
                    if auth.startswith("Bearer ") and not jwt_token:
                        jwt_token.append(auth[len("Bearer "):])
                        logger.info("bci_jwt_captured", url_prefix=request.url[:80])

            page.on("request", capture_jwt)

            try:
                progress("Abriendo sitio del banco...")
                await self._login(page, credentials.rut, credentials.password, progress)

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
                raw = await self._api_get(page, jwt, "cuentas")
                accounts = raw if isinstance(raw, list) else raw.get("cuentas", [])

                if not accounts:
                    raise RecoverableIngestionError("BCI no devolvió cuentas")

                progress(f"Extrayendo movimientos de {len(accounts)} cuenta(s)...")
                all_movs: list[CanonicalMovement] = []
                first_balance: int | None = None

                for acct in accounts:
                    numero = acct.get("numero") or acct.get("numeroCuenta") or ""
                    tipo = acct.get("tipo") or acct.get("tipoCuenta") or "CCT"

                    balance = await self._fetch_balance(page, jwt, numero, tipo)
                    if first_balance is None and balance is not None:
                        first_balance = balance

                    movs_raw = (
                        acct.get("movimientos")
                        or acct.get("ultimosMovimientos")
                        or acct.get("ultimosmovimientos")
                        or []
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

            except (AuthenticationError, TwoFactorTimeoutError):
                raise
            except Exception as exc:
                logger.error("bci_fetch_failed", error=str(exc))
                raise RecoverableIngestionError(f"Scraper BCI falló: {exc}") from exc

    # ── Login ────────────────────────────────────────────────────────────────

    async def _login(
        self, page: Page, rut: str, password: str, progress: ProgressCallback
    ) -> None:
        await page.goto(BCI_BANK_URL, wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(3)

        formatted_rut = self._format_rut(rut)
        clean_rut = re.sub(r"[.\-]", "", rut)

        if not await self._fill_field(page, RUT_SELECTORS, formatted_rut, clean_rut):
            raise RecoverableIngestionError("No se encontró el campo de RUT en BCI")

        await asyncio.sleep(0.5)

        if not await self._fill_field(page, PASS_SELECTORS, password):
            raise RecoverableIngestionError("No se encontró el campo de clave en BCI")

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
                    if (text.includes("ingresar") || text.includes("acceder") || text.includes("continuar")) {
                        btn.click();
                        return;
                    }
                }
            }""")

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

        error = await self._check_login_error(page)
        if error:
            raise AuthenticationError(f"Error de login BCI: {error}")

        if await self._detect_2fa(page):
            progress("Esperando aprobacion 2FA en tu app BCI...")
            if not await self._wait_for_2fa(page, progress):
                raise TwoFactorTimeoutError(
                    "Timeout esperando aprobacion 2FA BCI. "
                    "Abre tu app BCI y aprueba cuando inicies el sync."
                )

        progress("Sesion BCI iniciada (dashboard cargado)")

    async def _fill_field(
        self, page: Page, selectors: list[str], value: str, alt_value: str | None = None
    ) -> bool:
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if not el:
                    continue
                max_len = await page.evaluate(
                    "(s) => document.querySelector(s)?.maxLength ?? -1", sel
                )
                await el.click(click_count=3)
                use_value = alt_value if (alt_value and 0 < max_len <= 10) else value
                await el.type(use_value, delay=45)
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

    async def _detect_2fa(self, page: Page) -> bool:
        text = await page.evaluate("() => (document.body?.innerText || '').toLowerCase()")
        return any(kw in text for kw in TWO_FA_KEYWORDS)

    async def _wait_for_2fa(self, page: Page, progress: ProgressCallback) -> bool:
        start = datetime.now()
        while (elapsed := int((datetime.now() - start).total_seconds())) < self._timeout_sec:
            text = await page.evaluate("() => (document.body?.innerText || '').toLowerCase()")

            if any(kw in text for kw in REJECTION_KEYWORDS):
                return False

            if not any(kw in text for kw in TWO_FA_KEYWORDS):
                return True

            if elapsed > 0 and elapsed % 15 == 0:
                remaining = self._timeout_sec - elapsed
                progress(f"Esperando aprobacion 2FA ({remaining}s restantes)...")

            await asyncio.sleep(3)

        return False

    # ── Navegación al menú de cuentas ────────────────────────────────────────

    async def _navigate_to_accounts_menu(self, page: Page) -> None:
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
            await asyncio.sleep(3)
        else:
            logger.warning("bci_accounts_menu_not_found")

    # ── API REST con JWT Bearer ───────────────────────────────────────────────

    async def _api_get(self, page: Page, jwt: str, path: str) -> Any:
        return await page.evaluate(
            """async ([url, jwt]) => {
                const r = await fetch(url, {
                    credentials: "include",
                    headers: {
                        "Accept": "application/json",
                        "Authorization": `Bearer ${jwt}`,
                    },
                    referrer: window.location.href,
                });
                if (!r.ok) {
                    const text = await r.text().catch(() => "");
                    throw new Error(`GET ${url} -> ${r.status} :: ${text.slice(0, 200)}`);
                }
                return r.json();
            }""",
            [f"{BCI_API_BASE}/{path}", jwt],
        )

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

    async def _fetch_balance(
        self, page: Page, jwt: str, numero: str, tipo: str
    ) -> int | None:
        """Obtiene saldoContable desde /cuentas-busquedas/por-numero-cuenta."""
        if not numero:
            return None
        try:
            data = await self._api_post(
                page, jwt,
                "cuentas-busquedas/por-numero-cuenta",
                {"numero": numero, "tipo": tipo},
            )
            saldo = data.get("saldoContable")
            if saldo is not None:
                return int(saldo)
        except Exception as exc:
            logger.warning("bci_balance_fetch_failed", numero=numero, error=str(exc))
        return None

    # ── Normalización ─────────────────────────────────────────────────────────

    def _to_canonical(
        self, mov: dict, bank_id: str, since: date | None
    ) -> CanonicalMovement | None:
        amount = self._parse_amount(mov)
        desc = (
            mov.get("descripcion")
            or mov.get("glosa")
            or mov.get("descripcionMovimiento")
            or ""
        ).strip()
        occurred = self._parse_date(
            mov.get("fecha")
            or mov.get("fechaMovimiento")
            or mov.get("fechaContable")
            or mov.get("fechaTransaccion")
        )
        if since and occurred < since:
            return None
        return CanonicalMovement(
            external_id=build_external_id(bank_id, occurred, amount, desc, MovementSource.ACCOUNT),
            amount_clp=amount,
            raw_description=desc,
            occurred_at=occurred,
            movement_source=MovementSource.ACCOUNT,
            source_kind=SourceKind.SCRAPER,
            source_metadata={"raw": mov},
        )

    def _parse_amount(self, mov: dict) -> int:
        monto = mov.get("monto") or mov.get("montoMovimiento") or 0
        try:
            monto = int(monto)
        except (TypeError, ValueError):
            monto = 0
        tipo = (mov.get("tipo") or mov.get("tipoMovimiento") or "").lower()
        if tipo in ("cargo", "debito", "débito"):
            return -abs(monto)
        if tipo in ("abono", "credito", "crédito"):
            return abs(monto)
        return monto

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
