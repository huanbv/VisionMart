"""MinIO helper for the AI Engine.

The engine talks to the same bucket the backend uses so training images and
model weights can flow between the two services.
"""

from __future__ import annotations

import io
import logging
import os
from typing import Iterable

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger("ai-engine.storage")


def _client() -> tuple[Minio, str]:
    endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
    access = os.getenv("MINIO_ROOT_USER") or os.getenv("MINIO_ACCESS_KEY", "")
    secret = os.getenv("MINIO_ROOT_PASSWORD") or os.getenv(
        "MINIO_SECRET_KEY", ""
    )
    secure = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
    bucket = os.getenv("MINIO_BUCKET", "visionmart")
    return (
        Minio(endpoint, access_key=access, secret_key=secret, secure=secure),
        bucket,
    )


def download(key: str, dest_path: str) -> None:
    client, bucket = _client()
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        client.fget_object(bucket, key, dest_path)
    except S3Error as exc:
        logger.warning("minio download failed key=%s: %s", key, exc)
        raise


def upload(key: str, source_path: str, content_type: str = "application/octet-stream") -> str:
    client, bucket = _client()
    client.fput_object(bucket, key, source_path, content_type=content_type)
    return key


def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload an in-memory payload without round-tripping through a temp file.

    Added for pipeline tracing (`app/vision/trace.py`), which encodes frames
    to JPEG in memory — writing each stage to disk just to re-read it would
    double the I/O for no benefit.
    """
    client, bucket = _client()
    client.put_object(
        bucket, key, io.BytesIO(data), length=len(data), content_type=content_type
    )
    return key


def download_to_local(key: str, local_dir: str) -> str:
    """Download a key to ``local_dir`` preserving the file name and return the path."""
    name = key.rsplit("/", 1)[-1]
    dest = os.path.join(local_dir, name)
    download(key, dest)
    return dest


def download_many(keys: Iterable[str], local_dir: str) -> list[str]:
    paths: list[str] = []
    for key in keys:
        try:
            paths.append(download_to_local(key, local_dir))
        except Exception:  # noqa: BLE001
            logger.warning("skip broken key: %s", key)
    return paths
