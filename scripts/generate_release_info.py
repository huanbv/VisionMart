#!/usr/bin/env python3
"""Generate `release_info.json` at the repo root -- a small, static
manifest of "what is this build" facts (Application Version, Git Commit,
Build Time, Docker Image Version, Environment, pinned Python/Node
versions) that don't change at runtime and therefore don't belong in a
live collector.

`application_version` is read from the centralized `VERSION` file at the
repo root (see docs/44_VERSIONING.md) -- the single source of truth for
the project's version string, currently "1.0.0-rc1". If that file is
missing, falls back to `RELEASE_VERSION` env, then to whichever of
backend/ai-engine's `__init__.py` `__version__` is set, then "unknown".
A mismatch between the VERSION file and backend/ai-engine's `__version__`
literals is printed as a warning (not fatal) so drift is caught early.

Run this once per build/deploy, e.g. in CI right before `docker compose
build`, or manually on the VPS after `git pull`:

    python3 scripts/generate_release_info.py
    # or, to stamp a specific image tag / environment label:
    DOCKER_IMAGE_TAG=2026.07.04 RELEASE_ENVIRONMENT_LABEL=production \\
        python3 scripts/generate_release_info.py

`monitoring/collectors/release_info.py` reads this file (via the
monitoring service's read-only `.:/app/repo:ro` mount) and merges it
with facts that ARE only knowable at runtime (the monitoring
container's own Python version/OS/kernel, and PostgreSQL's version via
the existing `system_resources` collector) -- see docs/44_VERSIONING.md.

This script never imports `backend.app.*` or `ai_engine.app.*` (same
app-package-collision rule as every other standalone package here); it
only reads plain text files (`__init__.py`, `Dockerfile`) with simple
string search, never executing them.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _extract_version(init_py: Path) -> str | None:
    if not init_py.exists():
        return None
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_py.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def _read_version_file(repo_root: Path) -> str | None:
    """The single centralized version definition for the whole project
    (see docs/44_VERSIONING.md) -- a plain-text `VERSION` file at the repo
    root, e.g. "1.0.0-rc1". This is the highest-priority source for
    `application_version`: every component is expected to match it."""
    path = repo_root / "VERSION"
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def _extract_base_image(dockerfile: Path, prefix: str) -> str | None:
    if not dockerfile.exists():
        return None
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.upper().startswith("FROM") and prefix in line:
            # e.g. "FROM python:3.12-slim AS base" -> "python:3.12-slim"
            parts = line.split()
            if len(parts) >= 2:
                return parts[1]
    return None


def generate() -> dict:
    git_commit = _run(["git", "rev-parse", "HEAD"])
    git_commit_short = _run(["git", "rev-parse", "--short", "HEAD"])
    git_branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    git_dirty = _run(["git", "status", "--porcelain"])

    backend_version = _extract_version(REPO_ROOT / "backend" / "app" / "__init__.py")
    ai_engine_version = _extract_version(REPO_ROOT / "ai-engine" / "app" / "__init__.py")
    # Priority: centralized VERSION file (docs/44_VERSIONING.md) > explicit
    # RELEASE_VERSION env override (e.g. a CI-supplied build number) >
    # component __init__.py literals > "unknown". The VERSION file is the
    # canonical source; the others are fallbacks for when it's absent.
    version_file = _read_version_file(REPO_ROOT)
    app_version = version_file or os.getenv("RELEASE_VERSION") or backend_version or ai_engine_version or "unknown"
    version_mismatch = [
        f"{name}={v}" for name, v in (("backend", backend_version), ("ai_engine", ai_engine_version))
        if version_file and v and v != version_file
    ]
    if version_mismatch:
        print(f"WARNING: VERSION file is '{version_file}' but found mismatched component version(s): {', '.join(version_mismatch)}. "
              f"Update backend/app/__init__.py and/or ai-engine/app/__init__.py to match.", file=sys.stderr)

    backend_python_image = _extract_base_image(REPO_ROOT / "backend" / "Dockerfile", "python")
    ai_engine_python_image = _extract_base_image(REPO_ROOT / "ai-engine" / "Dockerfile", "python")
    frontend_node_image = _extract_base_image(REPO_ROOT / "frontend" / "Dockerfile", "node")

    info = {
        "application_version": app_version,
        "component_versions": {
            "backend": backend_version or "unknown",
            "ai_engine": ai_engine_version or "unknown",
        },
        "git": {
            "commit": git_commit or "unknown",
            "commit_short": git_commit_short or "unknown",
            "branch": git_branch or "unknown",
            "dirty": bool(git_dirty) if git_dirty is not None else None,
        },
        "build_time_utc": datetime.now(timezone.utc).isoformat(),
        "docker_image_tag": os.getenv("DOCKER_IMAGE_TAG", "dev"),
        "environment": os.getenv("RELEASE_ENVIRONMENT_LABEL") or os.getenv("APP_ENV", "development"),
        "pinned_runtimes": {
            "backend_python_image": backend_python_image or "unknown",
            "ai_engine_python_image": ai_engine_python_image or "unknown",
            "frontend_node_image": frontend_node_image or "unknown",
        },
        "version_source": "VERSION file" if version_file else ("RELEASE_VERSION env" if os.getenv("RELEASE_VERSION") else "component __init__.py fallback"),
        "version_consistent": not version_mismatch,
        "generator": "scripts/generate_release_info.py",
    }
    return info


def main() -> int:
    info = generate()
    out_path = REPO_ROOT / "release_info.json"
    out_path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
