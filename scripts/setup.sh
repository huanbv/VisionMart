#!/usr/bin/env bash
# Initial developer environment bootstrap.
set -euo pipefail

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if command -v pre-commit >/dev/null 2>&1; then
  pre-commit install
  echo "Installed pre-commit hooks"
else
  echo "pre-commit not found - skipping (install via 'pip install pre-commit')"
fi

echo "Setup complete. Next: 'make up'"
