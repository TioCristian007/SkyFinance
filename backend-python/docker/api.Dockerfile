FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir --no-build-isolation \
    $(python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(' '.join(d['project']['dependencies']))")

COPY src/ ./src/

ENV PYTHONPATH=/app/src

CMD ["sh", "-c", "uvicorn sky.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]