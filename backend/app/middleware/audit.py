"""HTTP audit middleware.

Records non-idempotent write requests against the immutable audit log.
Body capture is intentionally omitted to avoid leaking sensitive data.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.modules.audit.application.audit_service import AuditService
from app.modules.audit.infrastructure.repositories import (
    SqlAlchemyAuditRepository,
)
from app.modules.identity.application.jwt_service import JWTService

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _segments(path: str, api_prefix: str) -> list[str]:
    if not path.startswith(api_prefix):
        return []
    tail = path[len(api_prefix):].lstrip("/")
    return [s for s in tail.split("/") if s]


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


class AuditMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, skip_prefixes: Iterable[str] = ()) -> None:
        super().__init__(app)
        self._settings = get_settings()
        self._jwt = JWTService(self._settings)
        self._skip = tuple(skip_prefixes)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        try:
            if not self._should_record(request, response):
                return response
            await self._record(request, response)
        except Exception:
            logger.exception("audit middleware failed")
        return response

    def _should_record(self, request: Request, response: Response) -> bool:
        if request.method not in _WRITE_METHODS:
            return False
        path = request.url.path
        prefix = self._settings.BACKEND_API_PREFIX
        if not path.startswith(prefix):
            return False
        if any(path.startswith(prefix + s) for s in self._skip):
            return False
        if response.status_code >= 500:
            return False
        return True

    def _decode_claims(self, request: Request):
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        token = auth.split(" ", 1)[1].strip()
        try:
            return self._jwt.verify_access_token(token)
        except Exception:
            return None

    def _parse_resource(self, request: Request) -> tuple[str, str | None]:
        segs = _segments(request.url.path, self._settings.BACKEND_API_PREFIX)
        if not segs:
            return "unknown", None
        resource_type = segs[0]
        resource_id: str | None = None
        if len(segs) >= 2 and _UUID_RE.match(segs[1]):
            resource_id = segs[1]
        return resource_type, resource_id

    async def _record(self, request: Request, response: Response) -> None:
        claims = self._decode_claims(request)
        user_id = uuid.UUID(claims.sub) if claims else None
        organization_id = (
            uuid.UUID(claims.organization_id) if claims else None
        )
        resource_type, resource_id = self._parse_resource(request)
        action = f"{request.method} {response.status_code}"
        user_agent = request.headers.get("user-agent")
        if user_agent and len(user_agent) > 512:
            user_agent = user_agent[:512]

        async with SessionLocal() as session:
            service = AuditService(SqlAlchemyAuditRepository(session))
            await service.record(
                organization_id=organization_id,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=_client_ip(request),
                user_agent=user_agent,
            )
