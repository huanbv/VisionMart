"""cart pending_checkout status + checkout token

Adds a new cart_status enum value ("pending_checkout") plus
checkout_token / checkout_requested_at columns on shopping_carts, so an
AI-detected checkout_initiated (or a staff-initiated AI-cart checkout) can
freeze the bill and wait for an explicit customer/staff confirmation
before charging, instead of billing instantly.

Revision ID: 2f4a6c8e0b13
Revises: 1bcd2e3f4a56
Create Date: 2026-07-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "2f4a6c8e0b13"
down_revision = "1bcd2e3f4a56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres cannot add an enum value inside the same transaction it's
    # used in (and, on PG < 12, not inside any open transaction at all).
    # Alembic wraps each migration in a transaction by default, so end it
    # explicitly before ALTER TYPE; the column adds below don't depend on
    # being in that same transaction.
    op.execute("COMMIT")
    op.execute("ALTER TYPE cart_status ADD VALUE IF NOT EXISTS 'pending_checkout'")

    op.add_column(
        "shopping_carts",
        sa.Column("checkout_token", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_shopping_carts_checkout_token",
        "shopping_carts",
        ["checkout_token"],
    )
    op.add_column(
        "shopping_carts",
        sa.Column(
            "checkout_requested_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_shopping_carts_checkout_token", table_name="shopping_carts")
    op.drop_column("shopping_carts", "checkout_requested_at")
    op.drop_column("shopping_carts", "checkout_token")
    # Postgres has no ALTER TYPE ... DROP VALUE — removing an enum value
    # requires recreating the type and rewriting every dependent column.
    # Not worth the risk/downtime for a downgrade path; any existing
    # PENDING_CHECKOUT rows would need to be resolved (converted/abandoned)
    # manually first anyway. Left as a documented no-op.
