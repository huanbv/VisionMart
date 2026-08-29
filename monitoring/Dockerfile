# VisionMart Operational Monitoring service.
#
# Standalone image: does NOT reuse backend's or ai-engine's image/base, by
# design (see monitoring/__init__.py — this package never imports either
# service's `app` package). Runs as its own container in docker-compose,
# polling the rest of the stack over the network / a mounted Docker socket.

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY monitoring/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY monitoring /app/monitoring
# `visionmart` (deployment validation / production readiness -- Parts 5 &
# 6 of the Final Production Readiness spec) reuses this image's collectors
# and installed dependencies rather than shipping its own image; see
# visionmart/__init__.py for why this is safe (no app-package collision).
COPY visionmart /app/visionmart

RUN mkdir -p /data/logs

EXPOSE 8200

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -fsS http://localhost:8200/health || exit 1

CMD ["uvicorn", "monitoring.server:app", "--host", "0.0.0.0", "--port", "8200"]
