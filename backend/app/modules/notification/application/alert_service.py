"""Auto-alert scanning service.

Scans low-stock inventory items and offline cameras for an organization
and produces deduplicated in-app notifications targeted at the
`org_admin` role.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.realtime import channels_for_notification, publish_event
from app.modules.camera.infrastructure.models import Camera
from app.modules.catalog.infrastructure.models import Product
from app.modules.identity.infrastructure.models import Role
from app.modules.inventory.infrastructure.models import Inventory
from app.modules.notification.infrastructure.models import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
)
from app.modules.tenancy.infrastructure.models import Branch, Organization


class AlertService:
    """Cross-context read aggregator that emits domain notifications."""

    LOW_STOCK_TYPE = "low_stock"
    CAMERA_OFFLINE_TYPE = "camera_offline"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._settings = get_settings()
        self._pending: list[Notification] = []

    async def _admin_role_id(
        self, organization_id: uuid.UUID
    ) -> uuid.UUID | None:
        stmt = select(Role.id).where(
            Role.organization_id == organization_id,
            Role.code == "org_admin",
            Role.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _has_recent(
        self,
        organization_id: uuid.UUID,
        notif_type: str,
        key: str,
        value: str,
        since: datetime,
    ) -> bool:
        stmt = select(Notification.id).where(
            Notification.organization_id == organization_id,
            Notification.is_deleted.is_(False),
            Notification.type == notif_type,
            Notification.created_at >= since,
            Notification.payload[key].astext == value,
        )
        return (await self._session.execute(stmt)).first() is not None

    def _create(
        self,
        *,
        organization_id: uuid.UUID,
        role_id: uuid.UUID,
        notif_type: str,
        title: str,
        body: str,
        priority: NotificationPriority,
        payload: dict,
    ) -> Notification:
        n = Notification(
            organization_id=organization_id,
            recipient_role_id=role_id,
            channel=NotificationChannel.IN_APP,
            type=notif_type,
            title=title,
            body=body,
            payload=payload,
            priority=priority,
            status=NotificationStatus.SENT,
            sent_at=datetime.now(timezone.utc),
        )
        self._session.add(n)
        self._pending.append(n)
        return n

    async def scan_organization(self, organization_id: uuid.UUID) -> dict:
        role_id = await self._admin_role_id(organization_id)
        if role_id is None:
            return {"low_stock": 0, "camera_offline": 0, "skipped": True}

        dedup_since = datetime.now(timezone.utc) - timedelta(
            hours=self._settings.ALERT_DEDUP_HOURS
        )

        self._pending = []
        low_created = await self._scan_low_stock(
            organization_id, role_id, dedup_since
        )
        cam_created = await self._scan_offline_cameras(
            organization_id, role_id, dedup_since
        )

        if low_created or cam_created:
            await self._session.commit()
            for n in self._pending:
                await publish_event(
                    channels_for_notification(
                        organization_id=n.organization_id,
                        recipient_user_id=n.recipient_user_id,
                        recipient_role_id=n.recipient_role_id,
                    ),
                    {
                        "event": "notification.created",
                        "id": str(n.id),
                        "type": n.type,
                        "title": n.title,
                        "priority": n.priority.value,
                    },
                )
        return {"low_stock": low_created, "camera_offline": cam_created}

    async def _scan_low_stock(
        self,
        organization_id: uuid.UUID,
        role_id: uuid.UUID,
        dedup_since: datetime,
    ) -> int:
        stmt = (
            select(
                Inventory.id,
                Inventory.quantity,
                Inventory.reorder_level,
                Product.sku,
                Product.name,
                Branch.name,
            )
            .join(Product, Product.id == Inventory.product_id)
            .join(Branch, Branch.id == Inventory.branch_id)
            .where(
                Product.organization_id == organization_id,
                Inventory.is_deleted.is_(False),
                Inventory.reorder_level > 0,
                Inventory.quantity <= Inventory.reorder_level,
            )
        )
        rows = (await self._session.execute(stmt)).all()
        count = 0
        for inv_id, qty, level, sku, prod_name, branch_name in rows:
            if await self._has_recent(
                organization_id,
                self.LOW_STOCK_TYPE,
                "inventory_id",
                str(inv_id),
                dedup_since,
            ):
                continue
            priority = (
                NotificationPriority.CRITICAL
                if qty == 0
                else NotificationPriority.HIGH
            )
            self._create(
                organization_id=organization_id,
                role_id=role_id,
                notif_type=self.LOW_STOCK_TYPE,
                title=f"Tồn kho thấp: {sku} — {prod_name}",
                body=(
                    f"Chi nhánh {branch_name}: còn {qty} (ngưỡng {level})."
                ),
                priority=priority,
                payload={
                    "inventory_id": str(inv_id),
                    "sku": sku,
                    "product_name": prod_name,
                    "branch_name": branch_name,
                    "quantity": qty,
                    "reorder_level": level,
                },
            )
            count += 1
        return count

    async def _scan_offline_cameras(
        self,
        organization_id: uuid.UUID,
        role_id: uuid.UUID,
        dedup_since: datetime,
    ) -> int:
        threshold = datetime.now(timezone.utc) - timedelta(
            seconds=self._settings.CAMERA_OFFLINE_THRESHOLD_SECONDS
        )
        stmt = (
            select(Camera.id, Camera.code, Camera.name, Camera.last_seen_at)
            .where(
                Camera.organization_id == organization_id,
                Camera.is_deleted.is_(False),
                Camera.is_active.is_(True),
                or_(
                    Camera.is_online.is_(False),
                    and_(
                        Camera.last_seen_at.is_not(None),
                        Camera.last_seen_at < threshold,
                    ),
                ),
            )
        )
        rows = (await self._session.execute(stmt)).all()
        count = 0
        for cam_id, code, name, last_seen in rows:
            if await self._has_recent(
                organization_id,
                self.CAMERA_OFFLINE_TYPE,
                "camera_id",
                str(cam_id),
                dedup_since,
            ):
                continue
            self._create(
                organization_id=organization_id,
                role_id=role_id,
                notif_type=self.CAMERA_OFFLINE_TYPE,
                title=f"Camera offline: {code} — {name}",
                body=(
                    f"Lần online cuối: {last_seen.isoformat() if last_seen else 'chưa có dữ liệu'}."
                ),
                priority=NotificationPriority.HIGH,
                payload={
                    "camera_id": str(cam_id),
                    "code": code,
                    "name": name,
                    "last_seen_at": last_seen.isoformat() if last_seen else None,
                },
            )
            count += 1
        return count

    async def scan_all_organizations(self) -> dict[str, dict]:
        org_ids = (
            await self._session.execute(
                select(Organization.id).where(Organization.is_deleted.is_(False))
            )
        ).scalars().all()
        results: dict[str, dict] = {}
        for org_id in org_ids:
            results[str(org_id)] = await self.scan_organization(org_id)
        return results
