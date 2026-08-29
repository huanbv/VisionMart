"""AI Engine FastAPI application.

This service is intentionally kept separate from the backend API so it can be
deployed independently (GPU node, edge gateway, etc.) without changing the
public contract.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from app import __version__
from app.api.capture import router as capture_router
from app.api.cart_simulate import router as cart_router
from app.api.detect import router as detect_router
from app.api.frame import router as frame_router
from app.api.live import router as live_router
from app.api.trace import router as trace_router
from app.api.vision_config import router as vision_config_router
from app.api.training import router as training_router
from app.api.class_sku import router as class_sku_router

logger = logging.getLogger("ai-engine")


class HealthStatus(BaseModel):
    status: str
    service: str
    version: str


app = FastAPI(
    title="VisionMart AI Engine",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/health", response_model=HealthStatus, tags=["health"])
async def health() -> HealthStatus:
    return HealthStatus(status="ok", service="ai-engine", version=__version__)


@app.get("/ready", response_model=HealthStatus, tags=["health"])
async def ready() -> HealthStatus:
    return HealthStatus(status="ready", service="ai-engine", version=__version__)


app.include_router(detect_router)
app.include_router(capture_router)
app.include_router(cart_router)
app.include_router(frame_router)
app.include_router(live_router)
app.include_router(trace_router)
app.include_router(vision_config_router)
app.include_router(training_router)
app.include_router(class_sku_router)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.on_event("startup")
async def _start_step_writer() -> None:
    """Start the DEBUG_AI background writer if it is switched on.

    Started here rather than lazily on first use because the workers must
    live on the same event loop that serves requests, and creating tasks
    from inside a request handler makes their lifetime depend on whichever
    request happened to be first.

    Not started when DEBUG_AI is off, so the default deployment pays
    nothing — no queue, no tasks. Flipping the flag at runtime takes effect
    on the next restart; see step_writer.submit(), which safely reports a
    drop when the writer is not running.
    """
    from app.vision.config import get_vision_config
    from app.vision.storage import step_writer

    cfg = get_vision_config()
    if not getattr(cfg, "debug_ai", False):
        return
    await step_writer.start_writer(
        queue_size=cfg.debug_ai_queue_size,
        workers=cfg.debug_ai_workers,
        jpeg_quality=cfg.debug_ai_jpeg_quality,
    )


@app.on_event("shutdown")
async def _stop_step_writer() -> None:
    from app.vision.storage import step_writer

    await step_writer.stop_writer()


@app.on_event("startup")
async def _start_telemetry() -> None:
    """Start the dashboard telemetry pusher if enabled.

    Same reasoning as the step writer: the flush task must live on the
    request-serving event loop, and when the flag is off nothing is
    created at all.
    """
    from app.services import telemetry_client
    from app.vision.config import get_vision_config

    await telemetry_client.start(get_vision_config())


@app.on_event("shutdown")
async def _stop_telemetry() -> None:
    from app.services import telemetry_client

    await telemetry_client.stop()


@app.get("/active-persons/{camera_id}")
async def get_active_persons(camera_id: str):
    import time
    from app.api.frame import _TRACK_LAST_SEEN
    now = time.time()
    active = []
    prefix = f"{camera_id}:person-"
    for key, last_seen in list(_TRACK_LAST_SEEN.items()):
        if key.startswith(prefix) and (now - last_seen) < 10.0:
            try:
                mapped_id = int(key.split("person-")[-1])
                active.append({
                    "mapped_id": mapped_id,
                    "crop_url": f"/ai/person-crop/{camera_id}/{mapped_id}"
                })
            except Exception:
                pass
    return {"active_persons": active}


@app.get("/person-crop/{camera_id}/{mapped_id}")
async def get_person_crop(camera_id: str, mapped_id: int):
    from fastapi import HTTPException
    from app.services.person_tracker import get_person_crop_bytes
    crop_bytes = get_person_crop_bytes(camera_id, mapped_id)
    if crop_bytes is None:
        raise HTTPException(status_code=404, detail="Crop not found")
    return Response(content=crop_bytes, media_type="image/jpeg")
