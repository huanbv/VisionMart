# =============================================================
# VisionMart Backend - multi-stage image
#  - base    : OS + Python + system deps
#  - deps    : runtime Python deps
#  - dev     : deps + dev tooling (target used by docker-compose)
#  - runtime : deps + source code, NO dev tooling (production)
# =============================================================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# ---------- runtime dependencies only ----------
FROM base AS deps
COPY requirements.txt ./
RUN pip install -r requirements.txt

# ---------- dev (deps + dev tooling, with source mounted at runtime) ----------
FROM deps AS dev
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------- production runtime (slim, no dev tooling) ----------
FROM deps AS runtime
RUN groupadd --system app && useradd --system --gid app --home /app app
COPY --chown=app:app . .
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
