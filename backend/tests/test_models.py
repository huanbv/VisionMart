"""Smoke tests for the database mixins (no live DB required)."""

from __future__ import annotations

import importlib


def test_model_registry_imports_all_modules() -> None:
    """`app.models` side-effect imports must register every module's tables."""
    models = importlib.import_module("app.models")
    metadata = models.Base.metadata

    expected_tables = {
        # tenancy
        "organizations",
        "branches",
        "system_settings",
        # identity
        "users",
        "roles",
        "permissions",
        "user_roles",
        "role_permissions",
        # customer / employee / camera
        "customers",
        "employees",
        "cameras",
        # catalog / inventory
        "categories",
        "products",
        "inventory",
        # sales
        "shopping_carts",
        "orders",
        "order_items",
        # notification / audit
        "notifications",
        "audit_logs",
    }
    missing = expected_tables - set(metadata.tables.keys())
    assert not missing, f"Models not registered: {missing}"


def test_entity_has_audit_columns() -> None:
    from app.modules.tenancy.infrastructure.models import Organization

    cols = {c.name for c in Organization.__table__.columns}
    assert {"id", "created_at", "updated_at", "is_deleted", "deleted_at", "created_by", "updated_by"} <= cols
