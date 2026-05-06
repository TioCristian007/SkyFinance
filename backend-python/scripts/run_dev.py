"""Helper de arranque para Windows — fuerza SelectorEventLoop (evita WinError 64 con Docker)."""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run("sky.api.main:app", host="0.0.0.0", port=port, reload=False)
