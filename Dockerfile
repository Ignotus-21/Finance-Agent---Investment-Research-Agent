# syntax=docker/dockerfile:1
# Multi-stage security-hardened container build for the IRA Multi-Agent Service

# --- Stage 1: Build & Dependencies ---
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# --- Stage 2: Production Runtime ---
FROM python:3.11-slim AS runtime

WORKDIR /app

# Create non-root user for security compliance (Principle of Least Privilege)
RUN groupadd -r irauser && useradd -r -g irauser -d /app -s /sbin/nologin irauser

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY src/ ./src/
COPY configs/ ./configs/
COPY openapi.yaml .

# Set non-root ownership
RUN chown -R irauser:irauser /app

USER irauser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    ENVIRONMENT=production

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

ENTRYPOINT ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
