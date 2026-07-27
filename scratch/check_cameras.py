import asyncio
import os
import sys

sys.path.append("/app")

from app.database.session import SessionLocal
from sqlalchemy import select
from app.modules.camera.infrastructure.models import Camera

async def main():
    async with SessionLocal() as s:
        res = await s.execute(select(Camera))
        cameras = res.scalars().all()
        print("Total cameras in DB:", len(cameras))
        for c in cameras:
            print(f"ID: {c.id} | Name: {c.name} | Org: {c.organization_id} | Branch: {c.branch_id}")

if __name__ == "__main__":
    asyncio.run(main())
