"""Camera simulation storage (course project — no physical cameras yet).

Uploads a demo video for a camera to a *separate*, public-read MinIO
bucket and maintains a small JSON index that the standalone
"camera-sim-runner" container (docker-compose.yml) polls to know when to
(re)start the RTSP loop for that camera.

Deliberately kept separate from `app.services.object_storage.MinioStorage`
(private bucket, presigned-only): the runner container reads video bytes
over plain HTTP with no credentials, so this MUST be a small, distinct,
public-read bucket — never `Settings.MINIO_BUCKET`, which holds private
snapshots/evidence.

See docs/21_CAMERA_MANAGER.md and docker-compose.yml's "camera-sim" block
for the full design. Safe to delete this whole module once real cameras
are wired in (nothing else depends on it).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time

from minio import Minio
from minio.error import S3Error

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_INDEX_KEY = "_index.json"
_ALLOWED_SUFFIXES = {"mp4", "mov", "mkv", "avi", "webm"}
_MAX_VIDEO_BYTES = 200 * 1024 * 1024  # 200 MB — generous for a short demo loop clip


class CameraSimError(RuntimeError):
    pass


def _public_read_policy(bucket: str) -> str:
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                }
            ],
        }
    )


class CameraSimStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Minio | None = None

    def _get_client(self) -> Minio:
        if self._client is None:
            s = self._settings
            client = Minio(
                s.MINIO_ENDPOINT,
                access_key=s.MINIO_ROOT_USER,
                secret_key=s.MINIO_ROOT_PASSWORD,
                secure=s.MINIO_USE_SSL,
                region=s.MINIO_REGION,
            )
            bucket = s.MINIO_CAMERA_SIM_BUCKET
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
            # Idempotent — re-applied on every fresh client so a manually
            # tweaked bucket policy self-heals on the next backend restart.
            client.set_bucket_policy(bucket, _public_read_policy(bucket))
            self._client = client
        return self._client

    def stream_url_for(self, camera_id: str) -> str:
        s = self._settings
        return f"rtsp://{s.CAMERA_SIM_RTSP_HOST}:{s.CAMERA_SIM_RTSP_PORT}/cam-{camera_id}"

    async def upload_video(
        self,
        camera_id: str,
        *,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> str:
        """Uploads the video and refreshes the index. Returns the new
        stream_url the caller should save on the Camera row."""
        if not content:
            raise CameraSimError("File video rỗng")
        if len(content) > _MAX_VIDEO_BYTES:
            raise CameraSimError("File video vượt quá 200 MB")
        suffix = (filename.rsplit(".", 1)[-1] if "." in filename else "mp4").lower()
        if suffix not in _ALLOWED_SUFFIXES:
            raise CameraSimError(
                f"Định dạng '.{suffix}' không được hỗ trợ "
                f"(chỉ nhận: {', '.join(sorted(_ALLOWED_SUFFIXES))})"
            )
        key = f"{camera_id}.{suffix}"

        def _put_and_index() -> None:
            client = self._get_client()
            bucket = self._settings.MINIO_CAMERA_SIM_BUCKET

            # Best-effort read-modify-write. Concurrent uploads for
            # *different* cameras racing on this single index object are
            # rare enough in a course-project context that we don't add
            # locking — worst case one of two racing writers' index update
            # is briefly overwritten and picked up on the runner's next
            # poll a few seconds later.
            try:
                resp = client.get_object(bucket, _INDEX_KEY)
                try:
                    index = json.loads(resp.read())
                finally:
                    resp.close()
                    resp.release_conn()
            except S3Error:
                index = {}
            except ValueError:
                index = {}

            old_entry = index.get(camera_id)

            client.put_object(
                bucket,
                key,
                io.BytesIO(content),
                length=len(content),
                content_type=content_type or "video/mp4",
            )

            index[camera_id] = {"key": key, "updated_at": time.time()}
            payload = json.dumps(index).encode("utf-8")
            client.put_object(
                bucket,
                _INDEX_KEY,
                io.BytesIO(payload),
                length=len(payload),
                content_type="application/json",
            )

            # Clean up the old object if this upload changed the file
            # extension (e.g. .mp4 -> .mov) — otherwise it'd linger
            # unreferenced in the bucket forever.
            old_key = old_entry.get("key") if old_entry else None
            if old_key and old_key != key:
                try:
                    client.remove_object(bucket, old_key)
                except S3Error:
                    pass

        try:
            await asyncio.to_thread(_put_and_index)
        except S3Error as exc:
            logger.exception("camera-sim MinIO upload failed for camera=%s", camera_id)
            raise CameraSimError(str(exc)) from exc

        return self.stream_url_for(camera_id)
