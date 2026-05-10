FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

# Non-editable, no dev extras, sin playwright install chromium
RUN pip install --no-cache-dir .

EXPOSE 8000

# DB-less health check — responde aunque DB y Redis no estén disponibles.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

CMD ["uvicorn", "sky.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
