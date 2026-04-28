"""
sky.ingestion.sources.bci_scraper — Scraper Banco BCI (Playwright + REST).

ESTRATEGIA:
    BCI tiene una arquitectura más moderna que BChile:
        - Login en https://www.bci.cl con RUT + clave
        - Sin 2FA (al menos para personas comunes)
        - APIs REST en https://apilocal.bci.cl autenticadas con JWT bearer
        - El JWT lo emite el backend de BCI post-login y se inyecta en los
          requests por la SPA de Angular

CÓMO CAPTURAMOS EL JWT:
    Después del login, escuchamos requests salientes con page.on("request").
    Cuando vemos el primer request a apilocal.bci.cl con header `authorization`,
    extraemos el token. Es más robusto que buscarlo en localStorage porque la
    SPA puede guardarlo en memoria (closure de Angular) y no exponerlo.

FLUJO:
    1. goto sitio público
    2. fill RUT + clave → submit
    3. esperar redirect a portal logueado
    4. navegar a vista de saldos (dispara llamadas a apilocal.bci.cl)
    5. capturar JWT del primer request a la API
    6. con el JWT, hacer requests httpx directos:
        - POST /cuentas-busquedas/por-rut → lista de cuentas
        - POST /cuentas-movimientos/por-numero-cuenta → movimientos
    7. normalizar a CanonicalMovement

VENTAJAS VS BCHILE:
    - Sin 2FA → más rápido
    - APIs REST con httpx (no page.evaluate) → más simple, menos race conditions
    - Una sola request por cuenta para movimientos → sin paginación compleja

LIMITACIÓN ACTUAL:
    El endpoint /por-numero-cuenta devuelve "últimos movimientos" sin parámetro
    de paginación claro. Si BCI permite >30 días de histórico necesitaremos
    descubrir el endpoint de cartola completa. De momento, los syncs frecuentes
    + sync incremental cubren el caso de uso normal.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime
from typing import Any

import httpx
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
    build_external_id,
)

logger = get_logger("bci_scraper")

# URLs de BCI
# El form de login está embebido en la página corporativa, NO en una URL aparte.
# Es la misma URL a donde el botón "BANCO EN LÍNEA" lleva.
BANK_URL = "https://www.bci.cl/corporativo/banco-en-linea/personas"
API_BASE = "https://apilocal.bci.cl/bci-produccion/api-bci/bff-saldosyultimosmovimientoswebpersonas/v3.2"

# Cliente público de BCI — el mismo para todos los usuarios web
# (extraído del header `x-ibm-client-id` de las requests reales del portal)
BCI_CLIENT_ID = "3034b362-00e0-4cb6-977a-c901201b9c5e"

# Selectores reales del form de login de BCI (descubiertos vía discover_bci.py)
RUT_SELECTORS = [
    '#rut_aux',
    'input[name="rut_aux"]',
    'input[placeholder*="RUT" i]',
]
PASS_SELECTORS = [
    '#clave',
    'input[name="clave"]',
    'input[type="password"][placeholder*="clave" i]',
]
# El botón "INGRESAR" no tiene id, solo texto. Lo manejamos via evaluate en _login.

LOGIN_ERROR_KEYWORDS = [
    "clave incorrecta",
    "rut incorrecto",
    "rut inválido",
    "rut invalido",
    "bloqueada",
    "bloqueado",
]


class BCIScraperSource(DataSource):
    """DataSource para Banco BCI personas (sin 2FA, vía REST API moderna)."""

    def __init__(self, login_timeout_sec: int = 60):
        self._login_timeout = login_timeout_sec

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
            typical_latency_ms=45_000,  # mucho más rápido que BChile (sin 2FA)
            estimated_failure_rate=0.10,
            supports_backfill=True,
            backfill_days=30,  # aprox lo que devuelven "últimos movimientos"
            provides_credit_card=False,  # por ahora — endpoint TC no implementado
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
            raise ValueError("BCI requiere BankCredentials (RUT + clave)")

        progress = on_progress or (lambda s: None)
        started_at = datetime.now()
        pool = get_browser_pool()

        async with pool.acquire() as context:
            page = await context.new_page()

            # Container mutable para que el listener escriba el JWT
            captured: dict[str, str | None] = {"jwt": None}

            def on_request(req: Request):
                # BCI emite JWTs DISTINTOS por servicio. El de ms-bciplus-orq
                # no sirve para bff-saldosyultimosmovimientoswebpersonas.
                # Solo capturamos el JWT del path correcto.
                if captured["jwt"] is not None:
                    return
                url = req.url
                if "bff-saldosyultimosmovimientoswebpersonas" not in url:
                    return
                auth = req.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    token = auth.split(" ", 1)[1]
                    if len(token) < 200:
                        return
                    captured["jwt"] = token
                    logger.info("bci_jwt_captured", url_prefix=url[:100])

            page.on("request", on_request)

            try:
                progress("Abriendo sitio del banco...")
                await self._login(page, credentials.rut, credentials.password, progress)

                # Forzar navegación al portal personas para gatillar requests a apilocal
                progress("Capturando token de sesión...")
                await self._navigate_to_portal(page)

                # Esperar hasta tener el JWT (timeout 30s)
                jwt = await self._wait_for_jwt(captured, timeout_sec=30)
                if not jwt:
                    raise RecoverableIngestionError(
                        "No se capturó el JWT de BCI tras el login. "
                        "Puede que la SPA del portal haya cambiado."
                    )

                # Apagamos el listener — ya no lo necesitamos
                page.remove_listener("request", on_request)

                # Reutilizar las cookies del browser para que httpx mantenga la sesión
                cookies = await context.cookies()
                cookie_jar = httpx.Cookies()
                for c in cookies:
                    cookie_jar.set(c["name"], c["value"], domain=c.get("domain", ""))

                async with httpx.AsyncClient(
                    timeout=30,
                    cookies=cookie_jar,
                    headers=self._build_api_headers(jwt),
                ) as client:
                    progress("Listando cuentas...")
                    accounts = await self._list_accounts(client, credentials.rut)

                    progress(f"Extrayendo movimientos de {len(accounts)} cuenta(s)...")
                    all_movs: list[CanonicalMovement] = []
                    first_balance: int | None = None

                    for acc in accounts:
                        movs = await self._fetch_movements(client, acc, since)
                        all_movs.extend(movs)
                        # BCI no expone saldo directo en estos endpoints — lo
                        # inferimos a partir del primer movimiento si trae saldo,
                        # o lo dejamos en None.
                        if first_balance is None:
                            first_balance = self._infer_balance(movs)

                deduped = self._deduplicate(all_movs)
                progress(f"Listo — {len(deduped)} movimientos")
                elapsed_ms = int((datetime.now() - started_at).total_seconds() * 1000)

                return IngestionResult(
                    balance=AccountBalance(balance_clp=first_balance, as_of=datetime.now())
                    if first_balance is not None
                    else None,
                    movements=deduped,
                    source_kind=SourceKind.SCRAPER,
                    source_identifier=self.source_identifier,
                    elapsed_ms=elapsed_ms,
                    metadata={"account_count": len(accounts)},
                )

            except (AuthenticationError,):
                raise
            except Exception as exc:
                logger.error("bci_fetch_failed", error=str(exc))
                raise RecoverableIngestionError(f"Scraper BCI falló: {exc}") from exc

    # ── Login ────────────────────────────────────────────────────────────────

    async def _login(self, page: Page, rut: str, password: str, progress: ProgressCallback) -> None:
        await page.goto(BANK_URL, wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(3)

        # BCI a veces presenta el form en un iframe / submenú. Probar todos los selectores.
        formatted_rut = self._format_rut(rut)
        clean_rut = re.sub(r"[.\-]", "", rut)

        if not await self._fill_field(page, RUT_SELECTORS, formatted_rut, fallback_value=clean_rut):
            raise RecoverableIngestionError("No se encontró el campo de RUT en BCI")

        await asyncio.sleep(0.5)

        if not await self._fill_field(page, PASS_SELECTORS, password):
            raise RecoverableIngestionError("No se encontró el campo de clave en BCI")

        progress("Enviando credenciales...")
        # El botón "INGRESAR" del form de BCI no tiene id. Lo buscamos por texto.
        clicked = await page.evaluate("""() => {
            for (const btn of document.querySelectorAll('button[type="submit"], input[type="submit"]')) {
                const t = (btn.innerText || btn.value || '').trim().toUpperCase();
                if (t === 'INGRESAR') {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")

        if not clicked:
            # Fallback: cualquier submit que diga "ingresar"/"iniciar"/"entrar"
            await page.evaluate("""() => {
                for (const btn of document.querySelectorAll('button, input[type="submit"]')) {
                    const t = (btn.innerText || btn.value || '').trim().toLowerCase();
                    if (t.includes('ingresar') || t.includes('iniciar') || t.includes('entrar')) {
                        btn.click();
                        return;
                    }
                }
            }""")

        # BCI puede mostrar un reCAPTCHA v2 antes de autorizar el login.
        # Aparece intermitentemente (no siempre). Esperamos brevemente y lo manejamos
        # de forma interactiva si el browser está visible.
        await asyncio.sleep(2)
        if await self._detect_captcha(page):
            await self._handle_captcha(page, progress)

        # Esperar el redirect post-login. BCI redirige a contenido.jsf (dashboard viejo).
        # Aceptamos cualquiera de estas URLs como "logueado exitoso".
        try:
            await page.wait_for_url(
                re.compile(r"(personas\.bci\.cl|contenido\.jsf|LoginJSFGenerico)"),
                timeout=self._login_timeout * 1000,
            )
            # Esperar el segundo redirect (de LoginJSFGenerico a contenido.jsf)
            await asyncio.sleep(3)
            try:
                await page.wait_for_url(
                    re.compile(r"contenido\.jsf"),
                    timeout=15_000,
                )
            except Exception:
                pass  # ya está en otra URL válida
        except Exception:
            # Verificar si hubo error en el form
            error = await self._check_login_error(page)
            if error:
                raise AuthenticationError(f"Error de login BCI: {error}")
            raise RecoverableIngestionError(
                f"BCI no redirigió al portal en {self._login_timeout}s tras el login"
            )

        await asyncio.sleep(5)
        progress("Sesión BCI iniciada (dashboard cargado)")

    async def _fill_field(
        self,
        page: Page,
        selectors: list[str],
        value: str,
        fallback_value: str | None = None,
    ) -> bool:
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if not el:
                    continue
                await el.click(click_count=3)
                # Probar el valor primero; si maxLength rechaza, probar fallback
                try:
                    await el.type(value, delay=40)
                except Exception:
                    if fallback_value:
                        await el.type(fallback_value, delay=40)
                return True
            except Exception:
                continue
        return False

    async def _detect_captcha(self, page: Page) -> bool:
        """Detecta si hay un reCAPTCHA v2 checkbox visible en la página."""
        try:
            return await page.evaluate("""() => {
                const selectors = [
                    'iframe[src*="recaptcha"]',
                    'iframe[src*="google.com/recaptcha"]',
                    'iframe[title*="reCAPTCHA"]',
                    'div.g-recaptcha',
                    '[data-sitekey]',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) return true;
                    }
                }
                return false;
            }""")
        except Exception:
            return False

    async def _handle_captcha(self, page: Page, progress: ProgressCallback, timeout_sec: int = 180) -> None:
        """
        Maneja el reCAPTCHA de BCI de forma semi-asistida.
        Si el browser está visible (headed): espera a que el usuario lo resuelva.
        Si está headless: falla con mensaje claro.
        """
        from sky.ingestion.browser_pool import get_browser_pool
        pool = get_browser_pool()
        is_headless = pool._headless

        if is_headless:
            raise RecoverableIngestionError(
                "BCI mostró un reCAPTCHA que requiere interacción humana. "
                "Corre el scraper en modo headed (sin --headless) para resolverlo."
            )

        logger.info("bci_captcha_detected")
        progress("🔐 BCI mostró un CAPTCHA — resuélvelo en la ventana del browser...")
        print("\n" + "=" * 60)
        print("  ⚠️  CAPTCHA detectado en BCI")
        print("  Marca el checkbox 'No soy un robot' en la ventana del browser.")
        print(f"  Tienes {timeout_sec}s para resolverlo.")
        print("=" * 60 + "\n")

        start = datetime.now()
        while True:
            elapsed = int((datetime.now() - start).total_seconds())
            if elapsed >= timeout_sec:
                raise RecoverableIngestionError(
                    f"Timeout esperando resolución del CAPTCHA de BCI ({timeout_sec}s)."
                )
            if not await self._detect_captcha(page):
                logger.info("bci_captcha_solved", elapsed_sec=elapsed)
                progress("✅ CAPTCHA resuelto, continuando...")
                break
            remaining = timeout_sec - elapsed
            if elapsed > 0 and elapsed % 20 == 0:
                progress(f"🔐 Esperando CAPTCHA... ({remaining}s restantes)")
            await asyncio.sleep(2)

    async def _check_login_error(self, page: Page) -> str | None:
        try:
            return await page.evaluate(
                """(keywords) => {
                    const text = (document.body?.innerText || '').toLowerCase();
                    for (const kw of keywords) {
                        if (text.includes(kw)) return kw;
                    }
                    return null;
                }""",
                LOGIN_ERROR_KEYWORDS,
            )
        except Exception:
            return None

    async def _navigate_to_portal(self, page: Page) -> None:
        """
        Después del login, BCI redirige al portal viejo (contenido.jsf con menú).
        Para gatillar el JWT del bff-saldosyultimosmovimientoswebpersonas
        intentamos varias estrategias en cascada.

        Estrategia 1 (más robusta): click en el menú "Saldos / Últimos Movimientos"
            del portal — replica exactamente el comportamiento del usuario real.
        Estrategia 2 (fallback): servlet TokenAutorizacion (puede fallar si BCI lo protege).
        Estrategia 3 (último recurso): URL directa al microfrontend.
        """
        # Estrategia 1: click en enlace del menú "Últimos movimientos" del portal viejo.
        # Los textos y atributos cambian con actualizaciones — probamos varios.
        menu_clicked = await page.evaluate("""() => {
            const candidates = [
                'a[href*="saldosultimosmov"]',
                'a[href*="fe-saldos"]',
                'a[href*="ultimosmov"]',
            ];
            for (const sel of candidates) {
                const el = document.querySelector(sel);
                if (el) { el.click(); return true; }
            }
            // Buscar por texto de menú
            for (const a of document.querySelectorAll('a, li[onclick], span[onclick]')) {
                const t = (a.innerText || a.textContent || '').trim().toLowerCase();
                if (t.includes('últimos movimientos') || t.includes('saldos y movimientos')
                    || t.includes('ultimos movimientos') || t.includes('mis cuentas')) {
                    a.click();
                    return true;
                }
            }
            return false;
        }""")

        if menu_clicked:
            logger.info("bci_navigate_via_menu_click")
            await asyncio.sleep(15)
            return

        # Estrategia 2: servlet TokenAutorizacion (flujo original)
        token_authz_url = (
            "https://www.bci.cl/svcRest/infraestructura/seguridad/servlet/TokenAutorizacion"
            "?url=https://personas.bci.cl/nuevaWeb/fe-saldosultimosmovpersonas/"
        )
        try:
            await page.goto(token_authz_url, wait_until="domcontentloaded", timeout=30_000)
            logger.info("bci_navigate_via_token_authz")
            await asyncio.sleep(15)
            return
        except Exception as exc:
            logger.warning("bci_token_authz_failed", error=str(exc))

        # Estrategia 3: URL directa al microfrontend Angular
        try:
            await page.goto(
                "https://personas.bci.cl/nuevaWeb/fe-saldosultimosmovpersonas/",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            logger.info("bci_navigate_direct")
        except Exception:
            pass

        await asyncio.sleep(15)

    async def _wait_for_jwt(self, captured: dict, timeout_sec: int = 30) -> str | None:
        """Polling hasta que el listener haya capturado el JWT."""
        elapsed = 0
        while elapsed < timeout_sec:
            if captured["jwt"]:
                return captured["jwt"]
            await asyncio.sleep(0.5)
            elapsed += 0.5
        return None

    # ── API REST con JWT ─────────────────────────────────────────────────────

    def _build_api_headers(self, jwt: str) -> dict[str, str]:
        """Headers para todas las llamadas a apilocal.bci.cl, copiados del portal real."""
        return {
            "authorization": f"bearer {jwt}",
            "x-ibm-client-id": BCI_CLIENT_ID,
            "channel": "110",
            "application-id": "1",
            "tracking-id": "1",
            "reference-operation": "refope",
            "reference-service": "refser",
            "origin": "https://personas.bci.cl",
            "referer": "https://personas.bci.cl/",
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            ),
        }

    async def _list_accounts(self, client: httpx.AsyncClient, rut: str) -> list[dict[str, Any]]:
        """POST /cuentas-busquedas/por-rut → [{numero, tipo}, ...]"""
        url = f"{API_BASE}/cuentas-busquedas/por-rut"
        rut_normalized = self._normalize_rut(rut)

        r = await client.post(url, json={"rut": rut_normalized})
        if r.status_code == 401:
            raise AuthenticationError(f"BCI rechazó el JWT (401): {r.text[:200]}")
        if not r.is_success:
            raise RecoverableIngestionError(f"BCI por-rut {r.status_code}: {r.text[:200]}")

        data = r.json()
        return data.get("cuentas", [])

    async def _fetch_movements(
        self,
        client: httpx.AsyncClient,
        account: dict[str, Any],
        since: date | None,
    ) -> list[CanonicalMovement]:
        """POST /cuentas-movimientos/por-numero-cuenta → últimos movimientos."""
        url = f"{API_BASE}/cuentas-movimientos/por-numero-cuenta"
        body = {"numeroCuenta": account.get("numero")}

        r = await client.post(url, json=body)
        if r.status_code == 401:
            raise AuthenticationError("BCI rechazó el JWT al consultar movimientos")
        if not r.is_success:
            logger.warning(
                "bci_movements_fetch_failed",
                account=account.get("numero"),
                status=r.status_code,
            )
            return []

        data = r.json()
        movs_raw = data.get("movimientos", [])

        result: list[CanonicalMovement] = []
        for m in movs_raw:
            cm = self._mov_to_canonical(m, "bci")
            if since and cm.occurred_at < since:
                # BCI devuelve ordenados de más nuevo a más viejo, así que podemos cortar
                break
            result.append(cm)
        return result

    def _mov_to_canonical(self, mov: dict, bank_id: str) -> CanonicalMovement:
        """
        Mapeo del JSON de BCI a nuestro modelo canónico.
        BCI devuelve montos como string en 'monto' (ej: "125000.0000")
        y fecha en 'fechaMovimiento' (ISO 8601 con tiempo).
        Tipo: "A" = abono (positivo), "C" = cargo (negativo).
        """
        amount_raw_str = mov.get("monto", "0")
        try:
            amount_raw = int(float(amount_raw_str))
        except (TypeError, ValueError):
            amount_raw = 0

        # En BCI: tipo "A" = abono (in), tipo "C" o ausente = cargo (out)
        is_abono = mov.get("tipo", "").upper() == "A"
        amount = abs(amount_raw) if is_abono else -abs(amount_raw)

        desc = (mov.get("glosa") or "").strip()
        occurred = self._parse_bci_date(mov.get("fechaMovimiento"))

        return CanonicalMovement(
            external_id=build_external_id(bank_id, occurred, amount, desc, MovementSource.ACCOUNT),
            amount_clp=amount,
            raw_description=desc,
            occurred_at=occurred,
            movement_source=MovementSource.ACCOUNT,
            source_kind=SourceKind.SCRAPER,
            source_metadata={
                "bci_id": mov.get("idMovimiento"),
                "bci_serie": mov.get("serie"),
                "bci_tipo": mov.get("tipo"),
            },
        )

    def _parse_bci_date(self, raw: str | None) -> date:
        """BCI devuelve '2026-04-24T16:24:20.800' (ISO con tiempo)."""
        if not raw:
            return date.today()
        try:
            return datetime.fromisoformat(raw.split(".")[0]).date()
        except (ValueError, AttributeError):
            return date.today()

    def _infer_balance(self, movs: list[CanonicalMovement]) -> int | None:
        """
        BCI no expone saldo directo en estos endpoints. Por ahora None.
        Cuando descubramos el endpoint de saldo (probablemente
        /productos/cuentas/saldos o similar), lo cableamos.
        """
        return None

    # ── Helpers ──────────────────────────────────────────────────────────────

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
        """Formato 22.141.522-1 (con puntos y guion)."""
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

    def _normalize_rut(self, rut: str) -> str:
        """Formato '22141522-1' (sin puntos, con guion). Es lo que la API espera."""
        clean = re.sub(r"[.]", "", rut).upper()
        if "-" not in clean and len(clean) >= 2:
            clean = f"{clean[:-1]}-{clean[-1]}"
        return clean