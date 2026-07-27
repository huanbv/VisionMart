import asyncio
from app.database.session import SessionLocal
from app.modules.camera.infrastructure.models import Camera
from sqlalchemy import select

async def main():
    async with SessionLocal() as session:
        result = await session.execute(select(Camera))
        cameras = result.scalars().all()
        print(f"Total cameras: {len(cameras)}")
        for c in cameras:
            print(f"Camera ID: {c.id} - Code: {c.code} - Name: {c.name} - Is Checkout Zone: {c.is_checkout_zone}")

if __name__ == "__main__":
    asyncio.run(main())
