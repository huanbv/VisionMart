#!/usr/bin/env bash
# Wait until a TCP host:port becomes reachable. Useful in container entrypoints.
# Usage: ./wait-for.sh <host> <port> [timeout_seconds]
set -euo pipefail

HOST="${1:?host required}"
PORT="${2:?port required}"
TIMEOUT="${3:-60}"

start=$(date +%s)
until (echo > /dev/tcp/"${HOST}"/"${PORT}") >/dev/null 2>&1; do
  now=$(date +%s)
  if [ $((now - start)) -ge "${TIMEOUT}" ]; then
    echo "Timeout: ${HOST}:${PORT} not reachable after ${TIMEOUT}s" >&2
    exit 1
  fi
  sleep 1
done
echo "${HOST}:${PORT} is reachable"
