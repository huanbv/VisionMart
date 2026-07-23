"""ORM models for the AI pipeline telemetry context.

What this context is for
------------------------
Every stage of a camera frame's journey through the vision pipeline gets a
row here: session -> frame -> detection -> classification / OCR / embedding,
plus a log stream and a business-event stream. The admin dashboard is built
entirely on these tables, and the training pipeline mines them for the cases
the model got wrong.

Three schema decisions worth stating up front, because they are the reason
this looks different from the rest of the codebase's models:

1. ``ImmutableEntity``, not ``Entity``.
   These are append-only observations of something that already happened —
   a frame cannot be "edited", and soft-deleting a detection would make the
   dashboard lie about what the model actually did. Dropping the audit and
   soft-delete mixins also removes 6 columns from tables that will hold
   millions of rows: at ~30 fps across a handful of cameras, ``ai_frames``
   grows by roughly 2.5M rows/camera/day. Bytes per row are a real cost
   here in a way they never are on ``products``.

2. Partition-ready by ``created_at``.
   Nothing here is partitioned *yet* — that would be premature. But every
   high-volume table keeps ``created_at`` in its primary lookup index, so
   converting to native Postgres range partitioning later is a migration
   rather than a redesign, and the retention job can stay a cheap
   ``DROP PARTITION`` instead of a table-locking ``DELETE``.

3. Denormalised ``organization_id`` on the child tables.
   Strictly it is derivable via ``session -> camera -> org``. It is repeated
   because every dashboard query and every tenant-isolation filter starts
   with it, and making them all traverse three joins to reach the tenant key
   would be both slower and easier to forget (a forgotten tenant filter is a
   data leak, not just a slow query).

Retention
---------
This data is diagnostic, not financial: it should expire. See
``ai_logs``/``ai_frames`` — the intended policy is to keep frames ~7 days,
detections ~30 days, and events indefinitely (they are business facts).
TODO(retention): add a scheduled purge task once volumes are observed in
production; the indexes below are shaped so it can run as a ranged delete.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.entity import ImmutableEntity
from app.database.types import JSONBType, UUIDType


class AiSession(ImmutableEntity):
    """One continuous run of the pipeline for one camera.

    A session groups frames so the dashboard has something to page through:
    without it, "show me what the AI did" would mean scanning a global frame
    table by timestamp. A session opens on the first frame from a camera and
    closes when the stream stops or the process restarts.
    """

    __tablename__ = "ai_sessions"
    __table_args__ = (
        # The dashboard's landing query: newest sessions for this tenant.
        Index("ix_ai_sessions_org_started", "organization_id", "started_at"),
        Index("ix_ai_sessions_camera_started", "camera_id", "started_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    # Free-text camera key as the engine knows it. Kept alongside camera_id
    # because the ai-engine addresses cameras by string and may report one
    # that has no row yet; losing the frame would be worse than a soft link.
    camera_key: Mapped[str] = mapped_column(String(128), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="active"
    )

    # Running counters. Denormalised so the session list does not need a
    # COUNT(*) over millions of frames per row rendered.
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    detection_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    # Which model versions produced this session's results. Pinned per
    # session rather than read from current config, so a result stays
    # explainable after the models are upgraded.
    detector_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    classifier_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Snapshot of the VisionConfig flags in force. Without this, a frame from
    # last week cannot be reproduced — you would not know whether CLAHE was
    # on when it was captured.
    config_snapshot: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)


class AiFrame(ImmutableEntity):
    """A single processed frame: quality, timings, and where its images live."""

    __tablename__ = "ai_frames"
    __table_args__ = (
        # Paging within a session, and the Previous/Next controls.
        Index("ix_ai_frames_session_seq", "session_id", "seq"),
        Index("ix_ai_frames_org_captured", "organization_id", "captured_at"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Monotonic index within the session — stable ordering that does not
    # depend on clock resolution when several frames land in the same ms.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Object-storage prefix holding this frame's per-step debug images
    # (01_original.jpg ... 08_result.jpg + pipeline.json). Null when
    # DEBUG_AI was off — the common production case.
    storage_prefix: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Quality gate. `gate_passed=false` means the frame was measured and
    # rejected before detection; `reject_reason` says which check failed.
    # Storing rejects is the point: a camera that silently drops 40% of its
    # frames to blur is invisible otherwise.
    brightness: Mapped[float | None] = mapped_column(Float, nullable=True)
    contrast: Mapped[float | None] = mapped_column(Float, nullable=True)
    blur_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    gate_passed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    reject_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Per-stage latency. Separate columns rather than a JSON blob because
    # these are the numbers the performance dashboard aggregates, and
    # AVG() over a JSONB field cannot use an index.
    preprocess_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    detect_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    classify_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Which enhancement steps actually ran, in order. Cheap to store, and it
    # is the first thing you want when a frame looks wrong.
    steps_applied: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)


class AiTrack(ImmutableEntity):
    """One tracked object across its lifetime within a session.

    The resolved SKU lives here rather than on each detection because a
    track *is* the unit of identity: the same bottle seen in 40 frames is
    one object, and re-deciding its SKU per frame is both wasteful and a
    source of flicker in the UI.
    """

    __tablename__ = "ai_tracks"
    __table_args__ = (
        # A ByteTrack id is only unique within a camera+session, so the
        # natural key is the pair. Unique so the writer can upsert.
        Index("uq_ai_tracks_session_track", "session_id", "track_id", unique=True),
        Index("ix_ai_tracks_org_last_seen", "organization_id", "last_seen_at"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    track_id: Mapped[int] = mapped_column(Integer, nullable=False)
    class_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    # Final answer for this track, plus how it was reached.
    resolved_sku: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    resolved_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    resolved_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # "classifier" | "ocr" | "class_map" | "none" — which stage decided.
    resolved_source: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AiDetection(ImmutableEntity):
    """One YOLO box in one frame."""

    __tablename__ = "ai_detections"
    __table_args__ = (
        Index("ix_ai_detections_frame", "frame_id"),
        Index("ix_ai_detections_track", "track_pk"),
        # Powers "show me low-confidence detections to review".
        Index("ix_ai_detections_org_conf", "organization_id", "confidence"),
    )

    frame_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("ai_frames.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable: a detection exists even when tracking failed to assign an id.
    track_pk: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("ai_tracks.id", ondelete="SET NULL"), nullable=True
    )
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    class_name: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # Pixel coordinates in the *preprocessed* frame's space — the same space
    # the crop was taken from, so a box can be re-drawn on the stored image
    # without knowing the ROI transform.
    x1: Mapped[float] = mapped_column(Float, nullable=False)
    y1: Mapped[float] = mapped_column(Float, nullable=False)
    x2: Mapped[float] = mapped_column(Float, nullable=False)
    y2: Mapped[float] = mapped_column(Float, nullable=False)

    crop_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Final confidence after the multi-stage chain (see matcher.py). Kept
    # next to the raw YOLO score so the dashboard can show both and make the
    # effect of each stage visible.
    combined_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class AiClassification(ImmutableEntity):
    """Fine-grained SKU prediction for one detection's crop."""

    __tablename__ = "ai_classifications"
    __table_args__ = (
        Index("ix_ai_classifications_detection", "detection_id"),
        Index("ix_ai_classifications_org_sku", "organization_id", "sku"),
    )

    detection_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("ai_detections.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    label_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The runner-up is stored because the *margin* between top-1 and top-2 is
    # a better uncertainty signal than top-1 confidence alone: 0.51 vs 0.49
    # is a coin flip, 0.51 vs 0.05 is a confident answer on a hard class.
    # The review queue ranks by this.
    runner_up_sku: Mapped[str | None] = mapped_column(String(80), nullable=True)
    runner_up_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin: Mapped[float | None] = mapped_column(Float, nullable=True)

    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    inference_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class AiOcr(ImmutableEntity):
    """Text read off a detection's crop, used to break lookalike ties."""

    __tablename__ = "ai_ocr"
    __table_args__ = (Index("ix_ai_ocr_detection", "detection_id"),)

    detection_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("ai_detections.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    engine: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Parsed fields — the only parts the matcher actually consumes. Raw text
    # is kept anyway so a parser bug can be diagnosed and re-run offline
    # without re-reading the images.
    parsed_brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parsed_volume_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsed_weight_g: Mapped[int | None] = mapped_column(Integer, nullable=True)

    inference_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class AiEmbedding(ImmutableEntity):
    """Feature vector from the classifier backbone's penultimate layer.

    Why store these at all: a classifier can only name classes it was
    trained on, so a new product is silently mapped to the nearest old one.
    An embedding supports nearest-neighbour lookup instead, which handles a
    new SKU from a handful of reference images and no retraining — and it
    makes near-duplicate detection in the training set possible.

    The vector is JSONB for now, deliberately.
    TODO(pgvector): once the extension is available, migrate `vector` to
    `vector(dim)` and add an HNSW index. JSONB cannot do indexed ANN search,
    so today's lookups are brute force — fine at thousands of rows, not at
    millions. `dim` is stored so that migration can validate before casting.
    """

    __tablename__ = "ai_embeddings"
    __table_args__ = (
        Index("ix_ai_embeddings_detection", "detection_id"),
        Index("ix_ai_embeddings_org_model", "organization_id", "model_version"),
    )

    detection_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("ai_detections.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    vector: Mapped[list] = mapped_column(JSONBType, nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Set when this embedding was matched against a known product, so the
    # gallery can be rebuilt without re-running inference.
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )


class AiLog(ImmutableEntity):
    """Structured per-stage log line.

    Separate from the application logger because these need to be *queryable
    per frame* in the admin UI ("why did this frame produce nothing?"), which
    grepping a container's stdout cannot do. Volume is controlled by only
    writing WARN/ERROR unless DEBUG_AI is on.
    """

    __tablename__ = "ai_logs"
    __table_args__ = (
        Index("ix_ai_logs_frame", "frame_id"),
        Index("ix_ai_logs_session_created", "session_id", "created_at"),
        # Error triage across a tenant, newest first.
        Index("ix_ai_logs_org_level_created", "organization_id", "level", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Both nullable: a log line can predate the frame row (e.g. decode
    # failure) or belong to the session as a whole.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=True
    )
    frame_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("ai_frames.id", ondelete="CASCADE"), nullable=True
    )

    # "capture" | "preprocess" | "detect" | "track" | "crop" | "classify" |
    # "ocr" | "match" | "store"
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, server_default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    elapsed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)


class AiEvent(ImmutableEntity):
    """A business-level conclusion the pipeline reached.

    Distinct from ``ai_logs``: a log says what the code did, an event says
    what happened in the shop ("track 12 was taken from shelf A"). Events
    are the only table here intended to be kept indefinitely, because
    downstream cart/checkout logic depends on them.
    """

    __tablename__ = "ai_events"
    __table_args__ = (
        Index("ix_ai_events_session_created", "session_id", "created_at"),
        Index("ix_ai_events_org_type_created", "organization_id", "event_type", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=True
    )
    frame_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("ai_frames.id", ondelete="SET NULL"), nullable=True
    )
    track_pk: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("ai_tracks.id", ondelete="SET NULL"), nullable=True
    )

    # "pick_up" | "put_back" | "enter_zone" | "exit_zone" | "checkout" | ...
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
