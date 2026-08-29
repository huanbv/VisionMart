"""Shared-secret auth for AI Engine endpoints.

The AI Engine has no user auth of its own — it's a trusted-network service
only the backend (and operators on the internal docker network) should call.
Every route here does something expensive or sensitive (run inference,
open an arbitrary RTSP/HTTP stream, start a training job that consumes all
available RAM/CPU, or forward a fabricated cart event that results in a real
order), so leaving them wide open lets anyone who can reach this port cause
resource exhaustion or fraud with zero credentials.

This mirrors the `X-AI-Engine-Key` scheme the backend already uses for the
opposite direction (see app/modules/sales/api/ai_events_router.py on the
backend side) so both services trust each other with the same shared secret.
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException, status


def _expected_key() -> str:
    return os.getenv("AI_ENGINE_API_KEY", "change-me-ai-engine-key")


def require_api_key(
    x_ai_engine_key: str | None = Header(default=None, alias="X-AI-Engine-Key"),
) -> None:
    expected = _expected_key()
    if not expected or x_ai_engine_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-AI-Engine-Key",
        )
