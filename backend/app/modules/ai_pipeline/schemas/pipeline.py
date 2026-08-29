"""Pydantic schemas for the AI pipeline dashboard and telemetry ingest."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------- read side
class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    camera_id: uuid.UUID | None = None
    camera_key: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str
    frame_count: int
    detection_count: int
    detector_version: str | None = None
    classifier_version: str | None = None
    config_snapshot: dict | None = None


class SessionList(BaseModel):
    items: list[SessionRead]
    total: int


class FrameRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    seq: int
    captured_at: datetime
    width: int | None = None
    height: int | None = None
    storage_prefix: str | None = None
    brightness: float | None = None
    contrast: float | None = None
    blur_score: float | None = None
    quality_score: float | None = None
    gate_passed: bool
    reject_reason: str | None = None
    preprocess_ms: float | None = None
    detect_ms: float | None = None
    classify_ms: float | None = None
    ocr_ms: float | None = None
    total_ms: float | None = None
    steps_applied: dict | None = None


class FrameList(BaseModel):
    items: list[FrameRead]
    total: int


class ClassificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku: str
    confidence: float
    runner_up_sku: str | None = None
    runner_up_confidence: float | None = None
    margin: float | None = None
    model_version: str | None = None
    inference_ms: float | None = None


class DetectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    track_id: int | None = None
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    crop_key: str | None = None
    combined_confidence: float | None = None


class DetectionWithClassification(BaseModel):
    detection: DetectionRead
    classification: ClassificationRead | None = None


class LogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: str
    level: str
    message: str
    elapsed_ms: float | None = None
    payload: dict | None = None
    created_at: datetime


class FrameDetail(BaseModel):
    frame: FrameRead
    detections: list[DetectionWithClassification]
    logs: list[LogRead]
    previous_frame_id: uuid.UUID | None = None
    next_frame_id: uuid.UUID | None = None


class TrackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    track_id: int
    class_name: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    frame_count: int
    resolved_sku: str | None = None
    resolved_confidence: float | None = None
    resolved_source: str | None = None


class SessionStats(BaseModel):
    frame_count: int
    rejected_count: int
    reject_rate: float
    avg_total_ms: float | None = None
    max_total_ms: float | None = None
    avg_quality_score: float | None = None
    detection_count: int
    avg_confidence: float | None = None
    event_count: int


# -------------------------------------------------------------- write side
class ClassificationIn(BaseModel):
    sku: str
    confidence: float = 0.0
    label_index: int | None = None
    runner_up_sku: str | None = None
    runner_up_confidence: float | None = None
    margin: float | None = None
    model_version: str | None = None
    inference_ms: float | None = None


class DetectionIn(BaseModel):
    track_id: int | None = None
    class_name: str = "unknown"
    confidence: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    crop_key: str | None = None
    combined_confidence: float | None = None
    # Resolved identity for the track, so the ingest side can fill
    # ai_tracks without a second round-trip.
    sku: str | None = None
    source: str | None = None
    classification: ClassificationIn | None = None


class LogIn(BaseModel):
    stage: str = "unknown"
    level: str = "INFO"
    message: str = ""
    elapsed_ms: float | None = None
    payload: dict | None = None


class EventIn(BaseModel):
    event_type: str
    confidence: float | None = None
    payload: dict | None = None


class FrameIn(BaseModel):
    seq: int = 0
    captured_at: datetime | None = None
    width: int | None = None
    height: int | None = None
    storage_prefix: str | None = None
    brightness: float | None = None
    contrast: float | None = None
    blur_score: float | None = None
    quality_score: float | None = None
    gate_passed: bool = True
    reject_reason: str | None = None
    preprocess_ms: float | None = None
    detect_ms: float | None = None
    classify_ms: float | None = None
    ocr_ms: float | None = None
    total_ms: float | None = None
    steps_applied: dict | None = None
    detections: list[DetectionIn] = Field(default_factory=list)
    logs: list[LogIn] = Field(default_factory=list)
    events: list[EventIn] = Field(default_factory=list)


class OpenSessionIn(BaseModel):
    organization_id: uuid.UUID
    branch_id: uuid.UUID | None = None
    camera_id: uuid.UUID | None = None
    camera_key: str
    detector_version: str | None = None
    classifier_version: str | None = None
    config_snapshot: dict | None = None


class IngestIn(BaseModel):
    organization_id: uuid.UUID
    session_id: uuid.UUID
    frames: list[FrameIn] = Field(default_factory=list)


class IngestResult(BaseModel):
    written: int
    failed: int
