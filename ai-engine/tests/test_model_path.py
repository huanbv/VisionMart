from __future__ import annotations

import os

from app.services.model_path import (
    STOCK_WEIGHT,
    ensure_try_weight,
    is_custom_weight_path,
    sanitize_try_weight_key,
)


def test_sanitize_try_weight_key_accepts_job_object():
    assert sanitize_try_weight_key("models/abc-123.pt") == "models/abc-123.pt"
    assert sanitize_try_weight_key("  models/abc.pt  ") == "models/abc.pt"


def test_sanitize_try_weight_key_rejects_traversal_and_other_prefixes():
    assert sanitize_try_weight_key(None) is None
    assert sanitize_try_weight_key("") is None
    assert sanitize_try_weight_key("../models/x.pt") is None
    assert sanitize_try_weight_key("models/../etc/passwd.pt") is None
    assert sanitize_try_weight_key("/models/x.pt") is None
    assert sanitize_try_weight_key("models\\x.pt") is None
    assert sanitize_try_weight_key("weights/x.pt") is None
    assert sanitize_try_weight_key("models/x.pth") is None
    assert sanitize_try_weight_key("models/nested/x.pt") is None
    assert sanitize_try_weight_key("models/.hidden.pt") is None


def test_is_custom_weight_path():
    assert is_custom_weight_path(None) is False
    assert is_custom_weight_path(STOCK_WEIGHT) is False
    assert is_custom_weight_path("/models/yolov8n.pt") is False
    assert is_custom_weight_path("/models/try/job-uuid.pt") is True


def test_ensure_try_weight_reuses_existing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELS_DIR", str(tmp_path))
    dest = tmp_path / "job-1.pt"
    dest.write_bytes(b"fake-weight")
    path = ensure_try_weight("models/job-1.pt")
    assert os.path.isfile(path)
    assert os.path.basename(path) == "job-1.pt"
