"""Pipeline-trace endpoints — "show me every preprocessing step".

The existing `/ai/frame` endpoint answers *what the model detected*; these
endpoints answer *what the model was given, and what each preprocessing
stage did to it*. That is the difference the admin UI needs to move from
"click and see one result image" to a step-by-step view of the chain.

Two endpoints:

* ``POST /ai/trace/frame`` — run the preprocessing pipeline over an
  uploaded frame with tracing forced on, store one JPEG per stage, and
  return the stage list (metrics + object-storage keys). Detection is
  deliberately *not* run here: this is about the OpenCV chain, and keeping
  YOLO out makes the endpoint cheap enough to call interactively.
* ``GET /ai/trace/{trace_id}/{stage}`` — stream back one stored stage
  image so the frontend can render the chain without needing MinIO
  credentials of its own.

Both require the same API key as the rest of the engine.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.security import require_api_key
from app.vision.config import get_vision_config
from app.vision.pipeline import preprocess_for_detection
from app.vision.trace import flush_trace

router = APIRouter(prefix="/ai/trace", tags=["ai-trace"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger("ai-engine.api.trace")


@router.post("/frame")
async def trace_frame(
    file: UploadFile = File(...),
    camera_key: str = Form("default"),
) -> dict:
    """Preprocess one frame with per-stage tracing forced on.

    Returns the ordered stage list — each with the parameters used, the
    brightness/contrast/blur measured *after* that stage, the elapsed time,
    and the storage key of the stage image. The frontend renders this as
    the input → … → final chain.
    """
    cfg = get_vision_config()
    if not cfg.enable_pipeline_trace:
        # Explicit over silent: tracing writes to object storage, so it
        # must be switched on deliberately rather than inferred from the
        # request.
        # Thông điệp chỉ đúng một đường bật là .env — nhưng cờ này nằm
        # trong lớp cấu hình runtime, nên đường nhanh và đúng hơn là bật
        # từ Admin: có hiệu lực ngay, không cần restart container. Chỉ
        # đường sai khiến người vận hành đi sửa .env rồi restart cả dịch
        # vụ cho một việc lẽ ra là một cú bấm.
        raise HTTPException(
            status_code=409,
            detail=(
                "Tính năng lưu vết pipeline đang tắt. Bật tại "
                "Admin → Cấu hình xử lý ảnh → 'Bật lưu vết' "
                "(có hiệu lực ngay, không cần khởi động lại). "
                "Hoặc đặt ENABLE_PIPELINE_TRACE=true trong .env rồi restart ai-engine."
            ),
        )

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty upload.")

    try:
        result = preprocess_for_detection(
            image_bytes, camera_key, cfg, force_trace=True
        )
    except Exception as exc:
        logger.exception("trace preprocessing failed camera_key=%s", camera_key)
        raise HTTPException(status_code=400, detail=f"Could not process frame: {exc}") from exc

    if result.trace is None:  # should not happen given the check above
        raise HTTPException(status_code=500, detail="Tracing produced no trace.")

    payload = flush_trace(result.trace)
    payload["quality"] = (
        {
            "brightness": result.quality.brightness,
            "contrast": result.quality.contrast,
            "blur_score": result.quality.blur_score,
            "noise_estimate": result.quality.noise_estimate,
            "quality_score": result.quality.quality_score,
            "is_blurry": result.quality.is_blurry,
            "is_low_quality": result.quality.is_low_quality,
            "reason": result.quality.reason,
        }
        if result.quality is not None
        else None
    )
    payload["opencv_ms"] = round(result.opencv_ms, 2)
    return payload


@router.get("/debug/stats")
def debug_writer_stats() -> dict:
    """Health of the DEBUG_AI background writer.

    ``dropped`` is the number that matters: a steadily rising value means
    object storage cannot keep up with capture, and the fix is to lower
    ``DEBUG_AI_SAMPLE_RATE`` (or raise ``DEBUG_AI_WORKERS``) — not to
    enlarge the queue, which only delays the same problem. ``last_lag_ms``
    is the early warning: it climbs before drops begin.
    """
    from app.vision.storage import step_writer

    cfg = get_vision_config()
    stats = step_writer.get_stats()
    return {
        "enabled": bool(getattr(cfg, "debug_ai", False)),
        "sample_rate": getattr(cfg, "debug_ai_sample_rate", 1.0),
        "queue_size": getattr(cfg, "debug_ai_queue_size", 0),
        "workers": getattr(cfg, "debug_ai_workers", 0),
        "submitted": stats.submitted,
        "written": stats.written,
        "dropped": stats.dropped,
        "failed": stats.failed,
        "queue_depth": stats.queue_depth,
        "last_write_ms": stats.last_write_ms,
        "last_lag_ms": stats.last_lag_ms,
    }


@router.get("/debug/{camera_key}/{date_path:path}/{frame_uid}/manifest")
def debug_frame_manifest(camera_key: str, date_path: str, frame_uid: str) -> dict:
    """Return one debug frame's ``pipeline.json``.

    The manifest lists every step that was actually written, so the
    dashboard renders from it rather than guessing which of the eight
    filenames exist — a partially-written set (one failed upload) then
    displays the seven steps that succeeded instead of showing broken
    images.
    """
    import json

    from app.services import object_storage as storage
    from app.vision.storage.step_writer import build_prefix

    for part in (camera_key, frame_uid):
        if "/" in part or ".." in part:
            raise HTTPException(status_code=400, detail="Invalid path component.")
    if ".." in date_path:
        raise HTTPException(status_code=400, detail="Invalid date path.")

    prefix = build_prefix(camera_key, frame_uid).rsplit("/", 3)[0]
    key = f"{prefix}/{date_path}/{frame_uid}/pipeline.json"
    try:
        client, bucket = storage._client()
        response = client.get_object(bucket, key)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
    except Exception as exc:
        logger.warning("debug manifest not found key=%s: %s", key, exc)
        raise HTTPException(status_code=404, detail="Debug manifest not found.") from exc

    return json.loads(data.decode("utf-8"))


@router.get("/debug/image")
def debug_step_image(key: str) -> Response:
    """Stream one debug step image by its storage key.

    Keyed rather than path-segmented because the manifest already carries
    the exact key, so reconstructing it here would be a second place to get
    the layout wrong. Constrained to the ``ai-debug/`` prefix so this cannot
    be used to read arbitrary objects out of the bucket.
    """
    from app.services import object_storage as storage

    if not key.startswith("ai-debug/") or ".." in key:
        raise HTTPException(status_code=400, detail="Key outside the debug prefix.")

    try:
        client, bucket = storage._client()
        response = client.get_object(bucket, key)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
    except Exception as exc:
        logger.warning("debug image not found key=%s: %s", key, exc)
        raise HTTPException(status_code=404, detail="Debug image not found.") from exc

    return Response(content=data, media_type="image/jpeg")


@router.get("/{trace_id}/{stage_file}")
def get_trace_image(trace_id: str, stage_file: str, camera_key: str = "default") -> Response:
    """Stream one stored stage image back to the frontend.

    ``stage_file`` is the ``NN_stage.jpg`` filename from the trace payload,
    so the caller doesn't have to reconstruct the storage key format.
    """
    from app.services import object_storage as storage

    # Reject path traversal — these values land in an object-storage key.
    for part in (trace_id, stage_file, camera_key):
        if "/" in part or ".." in part:
            raise HTTPException(status_code=400, detail="Invalid trace path component.")

    key = f"traces/{camera_key}/{trace_id}/{stage_file}"
    try:
        client, bucket = storage._client()
        response = client.get_object(bucket, key)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
    except Exception as exc:
        logger.warning("trace image not found key=%s: %s", key, exc)
        raise HTTPException(status_code=404, detail="Trace image not found.") from exc

    return Response(content=data, media_type="image/jpeg")
