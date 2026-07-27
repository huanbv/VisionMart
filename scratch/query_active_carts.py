import asyncio
import os
import sys

sys.path.append("/app")

from app.database.session import SessionLocal
from sqlalchemy import select
from app.modules.sales.infrastructure.models import ShoppingCart

async def main():
    async with SessionLocal() as s:
        res = await s.execute(select(ShoppingCart).where(ShoppingCart.status == "active"))
        carts = res.scalars().all()
        print("Total ACTIVE carts in DB:", len(carts))
        for c in carts:
            items_summary = []
            # c.items is a list of dicts
            for item in (c.items or []):
                items_summary.append({
                    "sku": item.get("sku"),
                    "quantity": item.get("quantity"),
                    "added_at": item.get("added_at"),
                })
            print(f"ID: {c.id} | Session: {c.session_id} | CustomerID: {c.customer_id} | Items: {items_summary}")

if __name__ == "__main__":
    asyncio.run(main())
