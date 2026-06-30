"""Seed demo data: branches, catalog, inventory, customers, employees, cameras, orders.

Designed for development / demo environments. Idempotent: re-running is safe —
existing rows (by stable code / sku / slug) are reused, no duplicates are made.

Run inside the backend container:
    docker compose exec backend python -m app.scripts.seed_demo

Requires `seed_initial` to have run first (creates the demo organization).
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app import models as _models  # noqa: F401  - register all ORM mappers
from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.modules.camera.infrastructure.models import Camera
from app.modules.catalog.infrastructure.models import Category, Product
from app.modules.customer.infrastructure.models import Customer
from app.modules.employee.infrastructure.models import Employee
from app.modules.inventory.infrastructure.models import (
    Inventory,
    StockMovement,
    StockMovementType,
)
from app.modules.sales.infrastructure.models import (
    Order,
    OrderItem,
    OrderStatus,
)
from app.modules.tenancy.infrastructure.models import Branch, Organization

logger = logging.getLogger("seed-demo")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


BRANCHES = [
    {
        "code": "HQ",
        "name": "Trụ sở chính",
        "address": {"street": "123 Nguyễn Trãi", "city": "Hà Nội"},
        "timezone": "Asia/Ho_Chi_Minh",
    },
    {
        "code": "BR01",
        "name": "Chi nhánh Cầu Giấy",
        "address": {"street": "45 Trần Duy Hưng", "city": "Hà Nội"},
        "timezone": "Asia/Ho_Chi_Minh",
    },
]

CATEGORIES = [
    {"slug": "drinks", "name": "Đồ uống"},
    {"slug": "snacks", "name": "Bánh kẹo"},
    {"slug": "dairy", "name": "Sữa & sản phẩm từ sữa"},
    {"slug": "personal-care", "name": "Chăm sóc cá nhân"},
]

# (sku, name, category_slug, unit_price_vnd, barcode)
PRODUCTS = [
    ("DRK-001", "Coca-Cola 330ml", "drinks", 12_000, "8934567000011"),
    ("DRK-002", "Pepsi 330ml", "drinks", 11_500, "8934567000028"),
    ("DRK-003", "Trà xanh 0 độ 500ml", "drinks", 10_000, "8934567000035"),
    ("SNK-001", "Bánh Oreo gói 137g", "snacks", 28_000, "8934567000042"),
    ("SNK-002", "Snack Lay's 75g", "snacks", 18_000, "8934567000059"),
    ("SNK-003", "Kẹo Chocolate Kitkat", "snacks", 22_000, "8934567000066"),
    ("DRY-001", "Sữa Vinamilk 1L", "dairy", 35_000, "8934567000073"),
    ("DRY-002", "Sữa chua TH 100g", "dairy", 7_000, "8934567000080"),
    ("DRY-003", "Phô mai Con bò cười 8 miếng", "dairy", 45_000, "8934567000097"),
    ("PC-001", "Kem đánh răng PS 100g", "personal-care", 28_500, "8934567000103"),
    ("PC-002", "Dầu gội Clear 340g", "personal-care", 85_000, "8934567000110"),
    ("PC-003", "Sữa tắm Lifebuoy 500g", "personal-care", 65_000, "8934567000127"),
]

CUSTOMERS = [
    ("Nguyễn Văn An", "an.nguyen@example.com", "0901234567"),
    ("Trần Thị Bình", "binh.tran@example.com", "0901234568"),
    ("Lê Hoàng Cường", "cuong.le@example.com", "0901234569"),
    ("Phạm Minh Đức", None, "0901234570"),
    ("Hoàng Thu Hương", "huong.hoang@example.com", None),
]

EMPLOYEES = [
    ("EMP-001", "Nguyễn Thị Hà", "Quản lý"),
    ("EMP-002", "Phạm Văn Long", "Thu ngân"),
    ("EMP-003", "Đỗ Minh Tâm", "Thu ngân"),
    ("EMP-004", "Vũ Thị Lan", "Nhân viên kho"),
    ("EMP-005", "Bùi Quốc Huy", "Bảo vệ"),
]

# (code, name, location)
CAMERAS_PER_BRANCH = [
    ("CAM-ENT", "Camera cửa chính", "Lối vào chính"),
    ("CAM-POS", "Camera quầy thu ngân", "Quầy thu ngân"),
    ("CAM-AISLE", "Camera kệ hàng", "Lối đi giữa siêu thị"),
]


async def _seed() -> None:
    settings = get_settings()
    rng = random.Random(42)

    async with SessionLocal() as session:
        org = (
            await session.execute(
                select(Organization).where(
                    Organization.slug == settings.SEED_ORGANIZATION_SLUG
                )
            )
        ).scalar_one_or_none()
        if org is None:
            raise SystemExit(
                "Demo organization not found. Run `seed_initial` first."
            )

        # 1. Branches
        branch_by_code: dict[str, Branch] = {}
        for spec in BRANCHES:
            br = (
                await session.execute(
                    select(Branch).where(
                        Branch.organization_id == org.id,
                        Branch.code == spec["code"],
                    )
                )
            ).scalar_one_or_none()
            if br is None:
                br = Branch(
                    organization_id=org.id,
                    code=spec["code"],
                    name=spec["name"],
                    address=spec["address"],
                    timezone=spec["timezone"],
                    is_active=True,
                )
                session.add(br)
                await session.flush()
                logger.info("Created branch %s", br.code)
            branch_by_code[br.code] = br

        # 2. Categories
        category_by_slug: dict[str, Category] = {}
        for spec in CATEGORIES:
            cat = (
                await session.execute(
                    select(Category).where(
                        Category.organization_id == org.id,
                        Category.slug == spec["slug"],
                    )
                )
            ).scalar_one_or_none()
            if cat is None:
                cat = Category(
                    organization_id=org.id,
                    slug=spec["slug"],
                    name=spec["name"],
                    is_active=True,
                )
                session.add(cat)
                await session.flush()
                logger.info("Created category %s", cat.slug)
            category_by_slug[cat.slug] = cat

        # 3. Products
        product_by_sku: dict[str, Product] = {}
        for sku, name, cat_slug, price, barcode in PRODUCTS:
            prod = (
                await session.execute(
                    select(Product).where(
                        Product.organization_id == org.id,
                        Product.sku == sku,
                    )
                )
            ).scalar_one_or_none()
            if prod is None:
                prod = Product(
                    organization_id=org.id,
                    category_id=category_by_slug[cat_slug].id,
                    sku=sku,
                    barcode=barcode,
                    name=name,
                    unit_price=Decimal(price),
                    currency="VND",
                    is_active=True,
                )
                session.add(prod)
                await session.flush()
                logger.info("Created product %s", sku)
            product_by_sku[sku] = prod

        # 4. Inventory + opening stock movement (only when missing)
        for prod in product_by_sku.values():
            for br in branch_by_code.values():
                inv = (
                    await session.execute(
                        select(Inventory).where(
                            Inventory.product_id == prod.id,
                            Inventory.branch_id == br.id,
                        )
                    )
                ).scalar_one_or_none()
                if inv is None:
                    qty = rng.randint(5, 120)
                    reorder = rng.choice([5, 10, 15])
                    inv = Inventory(
                        product_id=prod.id,
                        branch_id=br.id,
                        quantity=qty,
                        reserved_quantity=0,
                        reorder_level=reorder,
                    )
                    session.add(inv)
                    session.add(
                        StockMovement(
                            organization_id=org.id,
                            product_id=prod.id,
                            branch_id=br.id,
                            movement_type=StockMovementType.IN,
                            delta=qty,
                            quantity_after=qty,
                            reason="Demo opening stock",
                            reference="seed_demo",
                        )
                    )
        await session.flush()

        # 5. Customers
        customer_pool: list[Customer] = []
        for full_name, email, phone in CUSTOMERS:
            cust = None
            if phone:
                cust = (
                    await session.execute(
                        select(Customer).where(
                            Customer.organization_id == org.id,
                            Customer.phone == phone,
                        )
                    )
                ).scalar_one_or_none()
            if cust is None and email:
                cust = (
                    await session.execute(
                        select(Customer).where(
                            Customer.organization_id == org.id,
                            Customer.email == email,
                        )
                    )
                ).scalar_one_or_none()
            if cust is None:
                cust = Customer(
                    organization_id=org.id,
                    branch_id=branch_by_code["HQ"].id,
                    full_name=full_name,
                    email=email,
                    phone=phone,
                    is_active=True,
                )
                session.add(cust)
                await session.flush()
                logger.info("Created customer %s", full_name)
            customer_pool.append(cust)

        # 6. Employees
        employee_pool: list[Employee] = []
        branch_list = list(branch_by_code.values())
        for idx, (code, full_name, position) in enumerate(EMPLOYEES):
            emp = (
                await session.execute(
                    select(Employee).where(
                        Employee.organization_id == org.id,
                        Employee.code == code,
                    )
                )
            ).scalar_one_or_none()
            if emp is None:
                emp = Employee(
                    organization_id=org.id,
                    branch_id=branch_list[idx % len(branch_list)].id,
                    code=code,
                    full_name=full_name,
                    position=position,
                    is_active=True,
                )
                session.add(emp)
                await session.flush()
                logger.info("Created employee %s", code)
            employee_pool.append(emp)

        # 7. Cameras (3 per branch)
        for br in branch_list:
            for code_suffix, name, location in CAMERAS_PER_BRANCH:
                cam_code = f"{br.code}-{code_suffix}"
                cam = (
                    await session.execute(
                        select(Camera).where(
                            Camera.organization_id == org.id,
                            Camera.code == cam_code,
                        )
                    )
                ).scalar_one_or_none()
                if cam is None:
                    cam = Camera(
                        organization_id=org.id,
                        branch_id=br.id,
                        code=cam_code,
                        name=f"{name} - {br.name}",
                        stream_url=f"rtsp://demo.local/{br.code.lower()}/{code_suffix.lower()}",
                        location=location,
                        resolution="1920x1080",
                        fps=25,
                        is_active=True,
                        is_online=rng.random() < 0.7,
                    )
                    session.add(cam)
                    await session.flush()
                    logger.info("Created camera %s", cam_code)

        # 8. Orders (skip if any demo order already exists)
        existing_demo_order = (
            await session.execute(
                select(Order.id).where(
                    Order.organization_id == org.id,
                    Order.code.like("DEMO-%"),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if existing_demo_order is None:
            now = datetime.now(timezone.utc)
            products = list(product_by_sku.values())
            for n in range(20):
                paid_at = now - timedelta(
                    days=rng.randint(0, 13),
                    hours=rng.randint(0, 23),
                    minutes=rng.randint(0, 59),
                )
                branch = rng.choice(branch_list)
                customer = rng.choice(customer_pool) if rng.random() < 0.7 else None
                employee = rng.choice(
                    [e for e in employee_pool if e.branch_id == branch.id]
                    or employee_pool
                )

                line_count = rng.randint(1, 4)
                chosen = rng.sample(products, line_count)
                items: list[OrderItem] = []
                total = Decimal("0")
                for prod in chosen:
                    qty = rng.randint(1, 3)
                    unit_price = Decimal(prod.unit_price)
                    subtotal = unit_price * qty
                    total += subtotal
                    items.append(
                        OrderItem(
                            product_id=prod.id,
                            quantity=qty,
                            unit_price=unit_price,
                            discount_amount=Decimal("0"),
                            subtotal=subtotal,
                        )
                    )

                order = Order(
                    organization_id=org.id,
                    branch_id=branch.id,
                    customer_id=customer.id if customer else None,
                    employee_id=employee.id,
                    code=f"DEMO-{paid_at.strftime('%y%m%d')}-{n + 1:03d}",
                    status=OrderStatus.PAID,
                    total_amount=total,
                    currency="VND",
                    paid_at=paid_at,
                    items=items,
                )
                order.created_at = paid_at
                order.updated_at = paid_at
                session.add(order)
            logger.info("Created 20 demo orders")
        else:
            logger.info("Demo orders already present, skipping order seeding")

        await session.commit()
        logger.info("Demo seed complete.")


if __name__ == "__main__":
    asyncio.run(_seed())
