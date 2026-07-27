import asyncio
import os
import sys

sys.path.append("/app")

from app.database.session import SessionLocal
from sqlalchemy import select
from app.modules.catalog.infrastructure.models import Product

async def main():
    async with SessionLocal() as s:
        res = await s.execute(select(Product))
        products = res.scalars().all()
        print("Total products in DB:", len(products))
        for p in products:
            print(f"ID: {p.id} | SKU: {p.sku} | Name: {p.name} | Active: {p.is_active} | Org: {p.organization_id}")

if __name__ == "__main__":
    asyncio.run(main())
