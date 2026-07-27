# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# OpenCV runtime deps; full CV/ML deps will be added in later sprints.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential curl ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

FROM base AS deps
COPY requirements.txt requirements-dev.txt ./
# Install CPU-only PyTorch first from the dedicated wheel index to avoid
# pulling the huge CUDA-bundled wheels from PyPI.
RUN pip install \
        --index-url https://download.pytorch.org/whl/cu121 \
        torch==2.4.1 torchvision==0.19.1
RUN pip install -r requirements.txt -r requirements-dev.txt

FROM deps AS runtime
COPY . .

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8100/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
