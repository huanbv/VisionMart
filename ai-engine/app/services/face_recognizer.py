"""Face recognizer stub.

For Sprint 61 we ship a stub that returns `None` unless a real embedding
backend (e.g. InsightFace, face_recognition, or a Qdrant lookup) is wired in
by later sprints. The stub exists so `POST /ai/frame` can already accept the
`recognize_face=true` flag without breaking when no backend is available.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("ai-engine.face")


@dataclass(frozen=True)
class FaceMatch:
    face_embedding_ref: str
    similarity: float


class FaceRecognizer:
    def __init__(self) -> None:
        self._enabled = os.getenv("FACE_RECOGNIZER_ENABLED", "false").lower() == "true"
        if self._enabled:
            logger.warning(
                "FACE_RECOGNIZER_ENABLED=true but no backend is wired in yet; "
                "face recognition will still return no matches."
            )

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def find_match(self, image_bytes: bytes) -> FaceMatch | None:
        # Placeholder — real implementation slated for a future sprint.
        return None


_singleton: FaceRecognizer | None = None


def get_face_recognizer() -> FaceRecognizer:
    global _singleton
    if _singleton is None:
        _singleton = FaceRecognizer()
    return _singleton
