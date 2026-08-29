"""add AI pipeline telemetry tables (session/frame/track/detection/...)

Revision ID: 6d8e0a2b4c57
Revises: 5c7d9e1f3a46
Create Date: 2026-07-23

Migration plan
--------------
Purely additive: nine new tables, no change to any existing table, no
backfill. Nothing reads or writes them until the ai-engine's storage worker
is enabled (P2.2), so this can be applied to production ahead of the code
that uses it and have no effect at all.

Order matters — children reference parents, so creation runs
sessions -> frames -> tracks -> detections -> {classifications, ocr,
embeddings} -> {logs, events}, and downgrade() is the exact reverse.

Rollback: ``alembic downgrade 5c7d9e1f3a46`` drops all nine. Because the
tables are diagnostic rather than transactional, dropping them loses
dashboard history but breaks no business data.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "6d8e0a2b4c57"
down_revision = "5c7d9e1f3a46"
branch_labels = None
depends_on = None


def _immutable_columns() -> list[sa.Column]:
    """Column set for ``ImmutableEntity``: UUID PK + timestamps only.

    Deliberately without the soft-delete and audit columns the ``Entity``
    tables carry. These tables are append-only observations that will reach
    millions of rows; five extra columns per row that nothing ever reads is
    a cost with no benefit, and a soft-deletable detection record would let
    the dashboard misrepresent what the model actually did.
    """
    return [
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    ]


def upgrade() -> None:
    # ---------------------------------------------------------------- sessions
    op.create_table(
        "ai_sessions",
        *_immutable_columns(),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("branch_id", sa.UUID(), nullable=True),
        sa.Column("camera_id", sa.UUID(), nullable=True),
        sa.Column("camera_key", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column("frame_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "detection_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("detector_version", sa.String(length=120), nullable=True),
        sa.Column("classifier_version", sa.String(length=120), nullable=True),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_ai_sessions_started_at", "ai_sessions", ["started_at"])
    op.create_index("ix_ai_sessions_org_started", "ai_sessions", ["organization_id", "started_at"])
    op.create_index("ix_ai_sessions_camera_started", "ai_sessions", ["camera_id", "started_at"])

    # ------------------------------------------------------------------ frames
    op.create_table(
        "ai_frames",
        *_immutable_columns(),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("storage_prefix", sa.String(length=512), nullable=True),
        sa.Column("brightness", sa.Float(), nullable=True),
        sa.Column("contrast", sa.Float(), nullable=True),
        sa.Column("blur_score", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column(
            "gate_passed", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("reject_reason", sa.String(length=120), nullable=True),
        sa.Column("preprocess_ms", sa.Float(), nullable=True),
        sa.Column("detect_ms", sa.Float(), nullable=True),
        sa.Column("classify_ms", sa.Float(), nullable=True),
        sa.Column("ocr_ms", sa.Float(), nullable=True),
        sa.Column("total_ms", sa.Float(), nullable=True),
        sa.Column("steps_applied", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["ai_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ai_frames_session_seq", "ai_frames", ["session_id", "seq"])
    op.create_index("ix_ai_frames_org_captured", "ai_frames", ["organization_id", "captured_at"])

    # ------------------------------------------------------------------ tracks
    op.create_table(
        "ai_tracks",
        *_immutable_columns(),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("class_name", sa.String(length=128), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frame_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("resolved_sku", sa.String(length=80), nullable=True),
        sa.Column("resolved_product_id", sa.UUID(), nullable=True),
        sa.Column("resolved_confidence", sa.Float(), nullable=True),
        sa.Column("resolved_source", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["ai_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_product_id"], ["products.id"], ondelete="SET NULL"),
    )
    # Unique so the writer can upsert on (session, track) instead of
    # racing a SELECT-then-INSERT when two frames arrive together.
    op.create_index(
        "uq_ai_tracks_session_track", "ai_tracks", ["session_id", "track_id"], unique=True
    )
    op.create_index("ix_ai_tracks_resolved_sku", "ai_tracks", ["resolved_sku"])
    op.create_index("ix_ai_tracks_org_last_seen", "ai_tracks", ["organization_id", "last_seen_at"])

    # -------------------------------------------------------------- detections
    op.create_table(
        "ai_detections",
        *_immutable_columns(),
        sa.Column("frame_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("track_pk", sa.UUID(), nullable=True),
        sa.Column("track_id", sa.Integer(), nullable=True),
        sa.Column("class_name", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("x1", sa.Float(), nullable=False),
        sa.Column("y1", sa.Float(), nullable=False),
        sa.Column("x2", sa.Float(), nullable=False),
        sa.Column("y2", sa.Float(), nullable=False),
        sa.Column("crop_key", sa.String(length=512), nullable=True),
        sa.Column("combined_confidence", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["frame_id"], ["ai_frames.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["track_pk"], ["ai_tracks.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_ai_detections_frame", "ai_detections", ["frame_id"])
    op.create_index("ix_ai_detections_track", "ai_detections", ["track_pk"])
    op.create_index("ix_ai_detections_org_conf", "ai_detections", ["organization_id", "confidence"])

    # ---------------------------------------------------------- classifications
    op.create_table(
        "ai_classifications",
        *_immutable_columns(),
        sa.Column("detection_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("label_index", sa.Integer(), nullable=True),
        sa.Column("runner_up_sku", sa.String(length=80), nullable=True),
        sa.Column("runner_up_confidence", sa.Float(), nullable=True),
        sa.Column("margin", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("inference_ms", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["detection_id"], ["ai_detections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ai_classifications_detection", "ai_classifications", ["detection_id"])
    op.create_index(
        "ix_ai_classifications_org_sku", "ai_classifications", ["organization_id", "sku"]
    )

    # --------------------------------------------------------------------- ocr
    op.create_table(
        "ai_ocr",
        *_immutable_columns(),
        sa.Column("detection_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("engine", sa.String(length=32), nullable=True),
        sa.Column("parsed_brand", sa.String(length=120), nullable=True),
        sa.Column("parsed_volume_ml", sa.Integer(), nullable=True),
        sa.Column("parsed_weight_g", sa.Integer(), nullable=True),
        sa.Column("inference_ms", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["detection_id"], ["ai_detections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ai_ocr_detection", "ai_ocr", ["detection_id"])

    # -------------------------------------------------------------- embeddings
    op.create_table(
        "ai_embeddings",
        *_immutable_columns(),
        sa.Column("detection_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        # JSONB today; see the model docstring for the pgvector migration path.
        sa.Column("vector", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["detection_id"], ["ai_detections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_ai_embeddings_detection", "ai_embeddings", ["detection_id"])
    op.create_index(
        "ix_ai_embeddings_org_model", "ai_embeddings", ["organization_id", "model_version"]
    )

    # -------------------------------------------------------------------- logs
    op.create_table(
        "ai_logs",
        *_immutable_columns(),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("frame_id", sa.UUID(), nullable=True),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, server_default=sa.text("'INFO'")),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("elapsed_ms", sa.Float(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["ai_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["frame_id"], ["ai_frames.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ai_logs_frame", "ai_logs", ["frame_id"])
    op.create_index("ix_ai_logs_session_created", "ai_logs", ["session_id", "created_at"])
    op.create_index(
        "ix_ai_logs_org_level_created", "ai_logs", ["organization_id", "level", "created_at"]
    )

    # ------------------------------------------------------------------ events
    op.create_table(
        "ai_events",
        *_immutable_columns(),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("frame_id", sa.UUID(), nullable=True),
        sa.Column("track_pk", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["ai_sessions.id"], ondelete="CASCADE"),
        # SET NULL rather than CASCADE: an event is a business fact that must
        # survive the retention job deleting the diagnostic frame it came from.
        sa.ForeignKeyConstraint(["frame_id"], ["ai_frames.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["track_pk"], ["ai_tracks.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_ai_events_session_created", "ai_events", ["session_id", "created_at"])
    op.create_index(
        "ix_ai_events_org_type_created",
        "ai_events",
        ["organization_id", "event_type", "created_at"],
    )


def downgrade() -> None:
    # Reverse creation order so no FK is left dangling.
    op.drop_table("ai_events")
    op.drop_table("ai_logs")
    op.drop_table("ai_embeddings")
    op.drop_table("ai_ocr")
    op.drop_table("ai_classifications")
    op.drop_table("ai_detections")
    op.drop_table("ai_tracks")
    op.drop_table("ai_frames")
    op.drop_table("ai_sessions")
