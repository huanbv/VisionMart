"""Object storage helper backed by MinIO (S3-compatible).

The `minio` library is synchronous; blocking calls are pushed to a worker
thread so async request handlers stay responsive.
"""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import timedelta
from urllib.parse import urlparse, urlunparse

from minio import Minio
from minio.error import S3Error

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class ObjectStorageError(RuntimeError):
    pass


class MinioStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Minio | None = None
        self._presign_client: Minio | None = None

    def _get_client(self) -> Minio:
        if self._client is None:
            self._client = Minio(
                self._settings.MINIO_ENDPOINT,
                access_key=self._settings.MINIO_ROOT_USER,
                secret_key=self._settings.MINIO_ROOT_PASSWORD,
                secure=self._settings.MINIO_USE_SSL,
            )
            bucket = self._settings.MINIO_BUCKET
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)
        return self._client

    def _get_presign_client(self) -> Minio:
        public = self._settings.MINIO_PUBLIC_ENDPOINT
        if not public:
            return self._get_client()
        if self._presign_client is None:
            self._presign_client = Minio(
                public,
                access_key=self._settings.MINIO_ROOT_USER,
                secret_key=self._settings.MINIO_ROOT_PASSWORD,
                secure=self._settings.MINIO_PUBLIC_USE_SSL,
            )
        return self._presign_client

    def _rewrite_url(self, signed_url: str) -> str:
        """Rewrite the host (and optional path prefix) of a presigned URL.

        The minio SDK always signs URLs against the host it was configured
        with. When ``MINIO_PUBLIC_ENDPOINT`` differs from ``MINIO_ENDPOINT``
        (e.g. internal ``minio:9000`` vs. public ``localhost:9000`` or a
        reverse-proxied path), the signature is still valid for the original
        host, so we must rewrite the URL to point at the public endpoint
        while keeping the query string (which carries the signature).
        """
        public = self._settings.MINIO_PUBLIC_ENDPOINT
        if not public:
            return signed_url

        parsed = urlparse(signed_url)
        public_parsed = urlparse(f"//{public}")
        new_netloc = public_parsed.netloc or public_parsed.path
        new_scheme = public_parsed.scheme or parsed.scheme

        # Optional path prefix (e.g. when MinIO is reverse-proxied under
        # ``/visionmart/``). The SDK signs against the bucket path, so we
        # need to inject the prefix here.
        path_prefix = self._settings.MINIO_PUBLIC_PATH_PREFIX.rstrip("/")
        new_path = parsed.path
        if path_prefix and not new_path.startswith(path_prefix + "/"):
            new_path = f"{path_prefix}{new_path}"

        return urlunparse(
            (
                new_scheme,
                new_netloc,
                new_path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        def _put() -> str:
            client = self._get_client()
            client.put_object(
                self._settings.MINIO_BUCKET,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return key

        try:
            return await asyncio.to_thread(_put)
        except S3Error as exc:
            logger.exception("MinIO put failed: %s", key)
            raise ObjectStorageError(str(exc)) from exc

    async def presigned_get(self, key: str, expires_seconds: int = 3600) -> str:
        def _sign() -> str:
            self._get_client()
            client = self._get_presign_client()
            url = client.presigned_get_object(
                self._settings.MINIO_BUCKET,
                key,
                expires=timedelta(seconds=expires_seconds),
            )
            return self._rewrite_url(url)

        try:
            return await asyncio.to_thread(_sign)
        except S3Error as exc:
            logger.exception("MinIO presign failed: %s", key)
            raise ObjectStorageError(str(exc)) from exc

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            client = self._get_client()
            client.remove_object(self._settings.MINIO_BUCKET, key)

        try:
            await asyncio.to_thread(_delete)
        except S3Error as exc:
            logger.warning("MinIO delete failed for %s: %s", key, exc)

    async def delete_many(self, keys: list[str]) -> int:
        from minio.deleteobjects import DeleteObject

        if not keys:
            return 0

        def _delete_many() -> int:
            client = self._get_client()
            errors = list(
                client.remove_objects(
                    self._settings.MINIO_BUCKET,
                    (DeleteObject(k) for k in keys),
                )
            )
            for err in errors:
                logger.warning("MinIO delete error: %s", err)
            return len(keys) - len(errors)

        return await asyncio.to_thread(_delete_many)

