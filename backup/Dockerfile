# Build context must be the repo root (like monitoring/Dockerfile) so this
# image can also mount the rest of the repo read-only for config-file and
# evaluation-report backups.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backup/requirements.txt /app/backup/requirements.txt
RUN pip install --no-cache-dir -r /app/backup/requirements.txt

COPY backup/ /app/backup/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Default: run the cron-scheduled daemon in the foreground. Operators who
# prefer host cron instead should override the command with
# `python -m backup.cli run` via a one-shot `docker compose run`.
CMD ["python", "-m", "backup.cli", "schedule"]
