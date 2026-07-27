import asyncio
from app.database.session import SessionLocal
from app.modules.ai_training.infrastructure.models import TrainingJob
from sqlalchemy import select

async def main():
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrainingJob).where(TrainingJob.status.in_(["pending", "running"]))
        )
        jobs = result.scalars().all()
        print(len(jobs))

if __name__ == "__main__":
    asyncio.run(main())
