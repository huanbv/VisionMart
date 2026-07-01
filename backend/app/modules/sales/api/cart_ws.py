"""WebSocket endpoint streaming live shopping-cart updates for a branch.

Auth: JWT access token as `?token=` query param.
Filter: `?branch_id=` query param (required).
Publishes any cart mutation for that branch via Redis pub/sub.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.config.settings import get_settings
from app.core.realtime import open_pubsub
from app.modules.identity.application.jwt_service import JWTService
from app.modules.sales.application.cart_realtime import cart_channel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sales"])


@router.websocket("/carts")
async def carts_ws(
    websocket: WebSocket,
    token: str = Query(...),
    branch_id: uuid.UUID = Query(...),
) -> None:
    settings = get_settings()
    jwt = JWTService(settings)
    try:
        claims = jwt.verify_access_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    _ = claims  # branch-level scope check happens at REST layer; token validity is enough here.

    channel = cart_channel(branch_id)
    await websocket.accept()

    client, pubsub = open_pubsub()
    try:
        await pubsub.subscribe(channel)
    except Exception:
        logger.exception("carts ws subscribe failed")
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
        _, pending = await asyncio.wait(
            {forward_task, reader_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        try:
            await pubsub.unsubscribe(channel)
        except Exception:
            pass
        await pubsub.aclose()
        await client.aclose()
        try:
            await websocket.close()
        except Exception:
            pass
