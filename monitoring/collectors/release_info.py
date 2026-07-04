"""Release Information -- merges the static build-time manifest
(`release_info.json`, produced by `scripts/generate_release_info.py`)
with facts that can only be read at runtime: this container's own
Python version and OS/kernel (accurate for the monitoring service
itself; since Linux containers share the host kernel, this is also an
honest proxy for the host's kernel -- never claimed to be anything more
than that), plus PostgreSQL's server version (reused from
`system_resources.collect_postgres_status` rather than opening a second
DB connection here -- see requirement to "avoid duplicate functionality").

If `release_info.json` isn't present (script never run, or the repo
mount is absent), every static field degrades to "unknown" rather than
raising -- this collector must never crash a poll or an API request.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path


def _read_version_file(repo_root: str) -> str | None:
    """Fallback for when `release_info.json` hasn't been generated yet --
    reads the centralized `VERSION` file directly (see
    docs/44_VERSIONING.md) so `application_version` is still correct even
    if `scripts/generate_release_info.py` was never run. Every other
    field (git commit, build time, pinned images) genuinely requires that
    script to have run and stays "unknown" without it."""
    path = Path(repo_root) / "VERSION"
    if not path.exists():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None


def _read_release_info_json(repo_root: str) -> dict:
    path = Path(repo_root) / "release_info.json"
    if not path.exists():
        return {
            "application_version": _read_version_file(repo_root) or "unknown",
            "component_versions": {"backend": "unknown", "ai_engine": "unknown"},
            "git": {"commit": "unknown", "commit_short": "unknown", "branch": "unknown", "dirty": None},
            "build_time_utc": None,
            "docker_image_tag": "unknown",
            "environment": "unknown",
            "pinned_runtimes": {"backend_python_image": "unknown", "ai_engine_python_image": "unknown", "frontend_node_image": "unknown"},
            "_source": f"release_info.json not found at {path} -- run scripts/generate_release_info.py at build/deploy time. "
                       f"application_version was read directly from the VERSION file as a fallback.",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_source"] = str(path)
        return data
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "application_version": _read_version_file(repo_root) or "unknown",
            "_source": str(path), "_error": f"Failed to read/parse release_info.json: {exc}",
        }


def collect_release_info(repo_root: str, postgres_version: str | None = None) -> dict:
    static_info = _read_release_info_json(repo_root)

    return {
        **static_info,
        "runtime": {
            "monitoring_python_version": sys.version.split()[0],
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "database_version": postgres_version or "unknown (PostgreSQL unreachable or not yet polled)",
        },
        "honesty_note": (
            "OS/kernel above are the monitoring container's own -- on Linux this is "
            "the shared host kernel, but it is not a substitute for checking each "
            "service container individually if they ever run on different base images."
        ),
    }
