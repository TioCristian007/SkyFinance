"""
scripts/test_bci_scraper.py — Test manual del scraper de BCI.

USO:
    1. Activar el venv: .venv\Scripts\activate  (Windows)
    2. Asegurar Playwright instalado: pip install -e ".[dev]"
    3. Instalar el browser: playwright install chromium
    4. Correr:
        python scripts/test_bci_scraper.py TU_RUT TU_PASSWORD

    Opcional:
        python scripts/test_bci_scraper.py TU_RUT TU_PASSWORD --since 2026-04-01
        python scripts/test_bci_scraper.py TU_RUT TU_PASSWORD --headless

QUÉ HACE:
    - Abre Chromium (con GUI para que veas el proceso)
    - Login a BCI con tus credenciales
    - Intercepta el JWT Bearer del tráfico de red
    - Extrae balance (saldoContable) + movimientos
    - Los imprime en pantalla

NO GUARDA NADA. Es solo para probar que el scraper funciona end-to-end.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sky.ingestion.browser_pool import BrowserPool, set_browser_pool
from sky.ingestion.contracts import BankCredentials
from sky.ingestion.sources.bci_direct import BCIDirectSource


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("rut")
    parser.add_argument("password")
    parser.add_argument("--since", help="YYYY-MM-DD — solo movimientos desde esta fecha")
    parser.add_argument("--timeout-2fa", type=int, default=120)
    parser.add_argument("--headless", action="store_true", help="Correr sin GUI")
    args = parser.parse_args()

    since = date.fromisoformat(args.since) if args.since else None

    pool = BrowserPool(pool_size=1, headless=args.headless)
    await pool.start()
    set_browser_pool(pool)

    try:
        scraper = BCIDirectSource(two_fa_timeout_sec=args.timeout_2fa)
        creds = BankCredentials(rut=args.rut, password=args.password)

        def on_progress(msg: str):
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] {msg}")

        print(f"\n{'='*60}")
        print(f"  Test scraper BCI")
        print(f"  RUT: {args.rut}")
        print(f"  Since: {since or 'sin filtro'}")
        print(f"{'='*60}\n")

        result = await scraper.fetch(
            "bci",
            creds,
            on_progress=on_progress,
            since=since,
        )

        print(f"\n{'='*60}")
        if result.balance:
            print(f"  SUCCESS")
        else:
            print(f"  SUCCESS (sin balance)")
        print(f"{'='*60}")
        balance_str = f"${result.balance.balance_clp:,}" if result.balance else "N/A"
        print(f"  Balance: {balance_str}")
        print(f"  Movimientos: {len(result.movements)}")
        print(f"  Tiempo: {result.elapsed_ms / 1000:.1f}s")
        print(f"  Metadata: {result.metadata}")
        print()

        print(f"  Primeros 10 movimientos:")
        print(f"  {'-'*56}")
        for m in result.movements[:10]:
            sign = "+ " if m.amount_clp > 0 else "  "
            print(f"  {m.occurred_at} | {sign}{m.amount_clp:>10} | {m.raw_description[:40]}")

        if len(result.movements) > 10:
            print(f"  ... y {len(result.movements) - 10} más")

    except Exception as exc:
        print(f"\nERROR: {exc}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await pool.stop()


if __name__ == "__main__":
    asyncio.run(main())
