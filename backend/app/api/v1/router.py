"""Versioned API router aggregator."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.ai_training.api.router import router as ai_training_router
from app.modules.audit.api.audit_router import router as audit_router
from app.modules.camera.api.camera_router import router as camera_router
from app.modules.catalog.api.category_router import router as category_router
from app.modules.catalog.api.product_router import router as product_router
from app.modules.customer.api.customer_router import router as customer_router
from app.modules.dashboard.api.dashboard_router import router as dashboard_router
from app.modules.detection.api.detection_router import router as detection_router
from app.modules.employee.api.employee_router import router as employee_router
from app.modules.identity.api.auth_router import router as auth_router
from app.modules.identity.api.role_router import router as role_router
from app.modules.identity.api.user_router import router as user_router
from app.modules.inventory.api.inventory_router import router as inventory_router
from app.modules.notification.api.notification_router import router as notification_router
from app.modules.reports.api.reports_router import router as reports_router
from app.modules.sales.api.ai_events_router import router as ai_events_router
from app.modules.sales.api.cart_router import router as cart_router
from app.modules.sales.api.order_router import router as order_router
from app.modules.tenancy.api.branch_router import router as branch_router
from app.modules.tenancy.api.organization_router import router as organization_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(organization_router)
api_router.include_router(branch_router)
api_router.include_router(user_router)
api_router.include_router(role_router)
api_router.include_router(category_router)
api_router.include_router(product_router)
api_router.include_router(inventory_router)
api_router.include_router(order_router)
api_router.include_router(cart_router)
api_router.include_router(ai_events_router)
api_router.include_router(customer_router)
api_router.include_router(employee_router)
api_router.include_router(camera_router)
api_router.include_router(dashboard_router)
api_router.include_router(notification_router)
api_router.include_router(audit_router)
api_router.include_router(reports_router)
api_router.include_router(detection_router)
api_router.include_router(ai_training_router)
