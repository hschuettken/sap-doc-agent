FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN pip install --prefer-binary --no-cache-dir -e ".[all]"

# Default: web
CMD ["uvicorn", "sap_doc_agent.web.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
