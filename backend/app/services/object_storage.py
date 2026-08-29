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
                region=self._settings.MINIO_REGION,
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
            # `region` is passed explicitly so the SDK skips its
            # auto-detection call (GET /{bucket}?location=), which many
            # reverse-proxy path rules don't route correctly (see
            # Settings.MINIO_REGION docstring).
            self._presign_client = Minio(
                public,
                access_key=self._settings.MINIO_ROOT_USER,
                secret_key=self._settings.MINIO_ROOT_PASSWORD,
                secure=self._settings.MINIO_PUBLIC_USE_SSL,
                region=self._settings.MINIO_REGION,
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

    async def get_bytes(self, key: str) -> bytes:
        """Read a small object into memory.

        Added for the pipeline dashboard, which reads each debug frame's
        ``pipeline.json`` manifest. Intended for *small* objects only —
        images are served to the browser via ``presigned_get`` instead, so
        their bytes never pass through this process. Reading a frame's
        worth of JPEGs through here would move megabytes per dashboard
        click across a thread the API also serves requests on.
        """

        def _get() -> bytes:
            client = self._get_client()
            response = client.get_object(self._settings.MINIO_BUCKET, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        try:
            return await asyncio.to_thread(_get)
        except S3Error as exc:
            logger.warning("MinIO get failed: %s (%s)", key, exc)
            raise ObjectStorageError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — same reasoning as presigned_get
            logger.warning("MinIO get failed (non-S3 error): %s (%s)", key, exc)
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
        except Exception as exc:  # noqa: BLE001
            # minio-py raises plain urllib3/requests exceptions (e.g.
            # MaxRetryError, ConnectionError) — not S3Error — when it can't
            # even reach the endpoint (wrong host, DNS failure, refused
            # connection, misrouted reverse proxy). Those previously escaped
            # uncaught and turned a single broken image link into a 500 for
            # the whole /ai/training/images request. Treat them the same as
            # an S3Error: caller degrades to preview_url=None instead of
            # crashing.
            logger.exception("MinIO presign failed (non-S3 error): %s", key)
            raise ObjectStorageError(str(exc)) from exc

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            client = self._get_client()
            client.remove_object(self._settings.MINIO_BUCKET, key)

        try:
            await asyncio.to_thread(_delete)
        except S3Error as exc:
            logger.warning("MinIO delete failed for %s: %s", key, exc)

    async def list_keys(self, prefix: str, limit: int = 10000) -> list[str]:
        """Liệt kê object dưới một prefix.

        Thêm cho job dọn dẹp telemetry: một khung hình debug ghi ra 9 file
        dưới cùng prefix, và số lượng thực tế thay đổi (bước nào chạy thì
        có file đó), nên phải liệt kê chứ không thể dựng tên file theo
        công thức — dựng theo công thức sẽ bỏ sót file và để lại rác.

        ``limit`` chặn trên để một prefix bất thường không nạp hàng triệu
        khoá vào bộ nhớ của worker.
        """

        def _list() -> list[str]:
            client = self._get_client()
            out: list[str] = []
            for obj in client.list_objects(
                self._settings.MINIO_BUCKET, prefix=prefix, recursive=True
            ):
                out.append(obj.object_name)
                if len(out) >= limit:
                    logger.warning(
                        "list_keys đạt trần %d ở prefix %s", limit, prefix
                    )
                    break
            return out

        try:
            return await asyncio.to_thread(_list)
        except S3Error as exc:
            logger.warning("MinIO list thất bại: %s (%s)", prefix, exc)
            raise ObjectStorageError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("MinIO list thất bại (không phải S3): %s (%s)", prefix, exc)
            raise ObjectStorageError(str(exc)) from exc

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

