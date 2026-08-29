"""WebSocket endpoint streaming realtime notification events to clients.

Authentication: JWT access token passed as `?token=` query parameter.
Subscribes to Redis channels matching the user and each of their roles.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.realtime import open_pubsub
from app.database.session import SessionLocal
from app.modules.identity.application.jwt_service import get_jwt_service
from app.modules.identity.infrastructure.models import UserRole

logger = logging.getLogger(__name__)

router = APIRouter(tags=["notification"])


async def _user_role_ids(
    session: AsyncSession, user_id: uuid.UUID
) -> list[uuid.UUID]:
    rows = await session.execute(
        select(UserRole.role_id).where(UserRole.user_id == user_id)
    )
    return [r for (r,) in rows.all()]


@router.websocket("/notifications")
async def notifications_ws(
    websocket: WebSocket, token: str = Query(...)
) -> None:
    jwt = get_jwt_service()
    try:
        claims = jwt.verify_access_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = uuid.UUID(claims.sub)
    org_id = uuid.UUID(claims.organization_id)

    async with SessionLocal() as session:
        role_ids = await _user_role_ids(session, user_id)

    channels = [f"user:{user_id}"] + [
        f"org:{org_id}:role:{rid}" for rid in role_ids
    ]

    await websocket.accept()

    client, pubsub = open_pubsub()
    try:
        await pubsub.subscribe(*channels)
    except Exception:
        logger.exception("ws subscribe failed")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        await client.aclose()
        return

    async def forward() -> None:
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            try:
                await websocket.send_text(msg["data"])
            except Exception:
                return

    async def reader() -> None:
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            return

    forward_task = asyncio.create_task(forward())
    reader_task = asyncio.create_task(reader())
    try:
        done, pending = await asyncio.wait(
            {forward_task, reader_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        try:
            await pubsub.unsubscribe(*channels)
        except Exception:
            pass
        await pubsub.aclose()
        await client.aclose()
        try:
            await websocket.close()
        except Exception:
            pass
