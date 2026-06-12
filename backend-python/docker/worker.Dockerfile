FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
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

CMD ["arq", "sky.worker.main.WorkerSettings"]
