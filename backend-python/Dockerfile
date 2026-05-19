FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

CMD ["sh", "-c", "uvicorn sky.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
