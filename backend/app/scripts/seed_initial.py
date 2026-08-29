"""Seed initial data: demo organization, super_admin role, admin user.

Idempotent: re-runs are safe — existing rows are reused.

Run inside the backend container:
    python -m app.scripts.seed_initial
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.modules.identity.application.password_hasher import PasswordHasher
from app.modules.identity.infrastructure.models import Role, User, UserRole
from app.modules.tenancy.infrastructure.models import Organization

logger = logging.getLogger("seed")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


SYSTEM_ROLES = [
    ("super_admin", "Super Administrator", "Platform-wide unrestricted access."),
    ("org_admin", "Organization Administrator", "Full control within one organization."),
    ("branch_manager", "Branch Manager", "Manages a single branch."),
    ("cashier", "Cashier", "Operates POS and cart confirmations."),
    ("staff", "Staff", "General store staff."),
    ("viewer", "Viewer", "Read-only access."),
]


async def _seed() -> None:
    settings = get_settings()
    hasher = PasswordHasher()

    async with SessionLocal() as session:
        # 1. Organization
        org = (
            await session.execute(
                select(Organization).where(Organization.slug == settings.SEED_ORGANIZATION_SLUG)
            )
        ).scalar_one_or_none()
        if org is None:
            org = Organization(
                name=settings.SEED_ORGANIZATION_NAME,
                slug=settings.SEED_ORGANIZATION_SLUG,
            )
            session.add(org)
            await session.flush()
            logger.info("Created organization %s", org.slug)
        else:
            logger.info("Organization %s already exists", org.slug)

        # 2. Roles
        existing_roles = {
            r.code: r
            for r in (
                await session.execute(
                    select(Role).where(Role.organization_id == org.id)
                )
            ).scalars()
        }
        roles_by_code: dict[str, Role] = {}
        for code, name, description in SYSTEM_ROLES:
            role = existing_roles.get(code)
            if role is None:
                role = Role(
                    organization_id=org.id,
                    code=code,
                    name=name,
                    description=description,
                )
                session.add(role)
                await session.flush()
                logger.info("Created role %s", code)
            roles_by_code[code] = role

        # 3. Admin user
        admin = (
            await session.execute(
                select(User).where(
                    User.organization_id == org.id,
                    User.email == settings.SEED_ADMIN_EMAIL,
                )
            )
        ).scalar_one_or_none()
        if admin is None:
            admin = User(
                organization_id=org.id,
                email=settings.SEED_ADMIN_EMAIL,
                username=settings.SEED_ADMIN_USERNAME,
                hashed_password=hasher.hash(settings.SEED_ADMIN_PASSWORD),
                full_name="Administrator",
                is_active=True,
                is_superuser=True,
            )
            session.add(admin)
            await session.flush()
            logger.info("Created admin user %s", admin.email)
        else:
            logger.info("Admin user %s already exists", admin.email)

        # 4. Assign super_admin role
        link = (
            await session.execute(
                select(UserRole).where(
                    UserRole.user_id == admin.id,
                    UserRole.role_id == roles_by_code["super_admin"].id,
                )
            )
        ).scalar_one_or_none()
        if link is None:
            session.add(UserRole(user_id=admin.id, role_id=roles_by_code["super_admin"].id))
            logger.info("Linked admin -> super_admin")

        await session.commit()
        logger.info("Seed complete.")


if __name__ == "__main__":
    asyncio.run(_seed())
