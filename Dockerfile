FROM node:20-bookworm-slim AS widget-builder

WORKDIR /widget
COPY src/spec2sphere/widget/package.json src/spec2sphere/widget/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY src/spec2sphere/widget/ ./
RUN npm run build


FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN pip install --prefer-binary --no-cache-dir -e ".[all]"

# Copy prebuilt widget bundle from the Node stage
COPY --from=widget-builder /widget/dist /app/src/spec2sphere/widget/dist

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "spec2sphere.web.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
