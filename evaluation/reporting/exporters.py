"""CSV / Excel (.xlsx) / JSON exporters for a `RunResult`.

Every export is derived directly from the `RunResult` produced by actually
running the collectors in `evaluation/metrics/*` — nothing here invents or
interpolates values. Fields that a given run didn't measure (e.g. no
`detection` because no ground truth was supplied) are simply absent from
the corresponding table/sheet rather than filled with 0 or an estimate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluation.reporting.types import RunResult, to_plain


def _flatten(d: dict, prefix: str = "") -> dict:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, prefix=f"{key}."))
        else:
            out[key] = v
    return out


def _pipeline_rows(run: RunResult) -> list[dict]:
    rows = []
    for c in run.configs:
        row = {"config_id": c.config_id, "config_name": c.config_name}
        row.update(_flatten(c.pipeline))
        rows.append(row)
    return rows


def _camera_quality_rows(run: RunResult) -> list[dict]:
    rows = []
    for c in run.configs:
        if not c.camera_quality:
            continue
        row = {"config_id": c.config_id, "config_name": c.config_name}
        row.update(_flatten(c.camera_quality))
        rows.append(row)
    return rows


def _detection_rows(run: RunResult) -> list[dict]:
    rows = []
    for c in run.configs:
        if not c.detection:
            continue
        d = dict(c.detection)
        per_class = d.pop("per_class", None)
        confusion = d.pop("confusion_matrix", None)
        row = {"config_id": c.config_id, "config_name": c.config_name}
        row.update(_flatten(d))
        row["per_class_json"] = json.dumps(per_class) if per_class else None
        row["confusion_matrix_json"] = json.dumps(confusion) if confusion else None
        rows.append(row)
    return rows


def _tracking_rows(run: RunResult) -> list[dict]:
    rows = []
    for c in run.configs:
        if not c.tracking:
            continue
        row = {"config_id": c.config_id, "config_name": c.config_name}
        row.update(_flatten(c.tracking))
        rows.append(row)
    return rows


def _opencv_module_rows(run: RunResult) -> list[dict]:
    if not run.opencv_modules:
        return []
    return [dict(_flatten(m)) for m in run.opencv_modules]


def _cart_metrics_rows(run: RunResult) -> list[dict]:
    if not run.cart_metrics:
        return []
    return [_flatten(run.cart_metrics)]


def export_json(run: RunResult, output_dir: str | Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"evaluation_{run.run_id}.json"
    path.write_text(json.dumps(run.to_dict(), indent=2, default=str), encoding="utf-8")
    return path


def export_csv(run: RunResult, output_dir: str | Path) -> list[Path]:
    import pandas as pd

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    tables = {
        "pipeline_metrics": _pipeline_rows(run),
        "camera_quality_metrics": _camera_quality_rows(run),
        "detection_metrics": _detection_rows(run),
        "tracking_metrics": _tracking_rows(run),
        "opencv_module_evaluation": _opencv_module_rows(run),
        "cart_metrics": _cart_metrics_rows(run),
    }
    for name, rows in tables.items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        path = output_dir / f"{name}_{run.run_id}.csv"
        df.to_csv(path, index=False)
        paths.append(path)
    return paths


def export_xlsx(run: RunResult, output_dir: str | Path) -> Path:
    import pandas as pd

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"evaluation_{run.run_id}.xlsx"

    tables = {
        "Pipeline": _pipeline_rows(run),
        "CameraQuality": _camera_quality_rows(run),
        "Detection": _detection_rows(run),
        "Tracking": _tracking_rows(run),
        "OpenCVModules": _opencv_module_rows(run),
        "CartMetrics": _cart_metrics_rows(run),
    }
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        wrote_any = False
        for sheet_name, rows in tables.items():
            if not rows:
                continue
            pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)
            wrote_any = True
        if not wrote_any:
            # openpyxl refuses to save a workbook with zero visible sheets —
            # write a placeholder explaining why the run produced no tables.
            pd.DataFrame([{"note": "No metrics were measured in this run."}]).to_excel(
                writer, sheet_name="Empty", index=False
            )
    return path
