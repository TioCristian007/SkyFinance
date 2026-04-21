FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY src/ src/

CMD ["arq", "sky.worker.main.WorkerSettings"]
