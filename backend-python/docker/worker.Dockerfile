FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# Chromium + todas sus dependencias de sistema en una pasada
RUN playwright install chromium --with-deps

RUN rm -rf /var/lib/apt/lists/*

CMD ["arq", "sky.worker.main.WorkerSettings"]
