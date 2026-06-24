FROM python:3.12-slim

WORKDIR /app

# xvfb: display virtual para correr Chrome HEADFUL en el worker. El managed
# challenge de Cloudflare de BCI se dispara contra Chrome HEADLESS (diagnóstico
# 2026-06-24, Fase 0 2×2: MISMA IP residencial, headful pasa / headless recibe
# el challenge → el gatillo es headless, NO la IP). Correr headful en un display
# virtual replica la huella validada en local sin costo de proxy residencial.
# Ver backend-python/docs/SPRINT_BCI_SCRAPER_REWORK.md (Fase 0 bis) y B-2.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# Chrome real (canal branded) como browser primario — misma huella y
# comportamiento que el entorno local validado. Chromium bundled headless
# tecleaba mal caracteres con Shift ('$') en el form de BChile (causa raíz
# del sprint 2026-06-12). El pool usa channel="chrome" si está disponible.
RUN playwright install chrome --with-deps

# Chromium bundled queda como fallback explícito del pool (loguea warning
# si cae acá; la verificación post-fill del scraper es la red de seguridad).
RUN playwright install chromium

RUN rm -rf /var/lib/apt/lists/*

# scripts/ va al final (editar un script no invalida los layers caros de pip /
# playwright). Habilita el test manual DENTRO del contenedor — Cell C del
# diagnóstico: `railway ssh` → `python scripts/test_bci_scraper.py <rut> '<clave>'`
# (headful vía DISPLAY=:99, desde la IP de datacenter, SIN activar `bci`).
COPY scripts/ ./scripts/

# El worker corre HEADFUL dentro del Xvfb. browser_headless=false hace que el
# pool lance Chrome con ventana (render real → pasa el Turnstile que bloquea a
# headless). Palanca operativa (§14): Railway puede override por env si hiciera
# falta. NO setear BROWSER_HEADLESS=true en el servicio del worker.
ENV BROWSER_HEADLESS=false
ENV DISPLAY=:99

# Arranca Xvfb en :99 y exec arq (arq reemplaza al shell → recibe el SIGTERM de
# Railway directo, shutdown limpio; Xvfb queda de fondo y muere con el
# contenedor). Pantalla holgada (1920x1080x24) para no clipear la ventana.
CMD ["sh", "-c", "Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp & exec arq sky.worker.main.WorkerSettings"]
