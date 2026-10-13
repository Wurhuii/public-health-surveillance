from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT


_CACHE_SIGNATURE: tuple[tuple[str, int, int], ...] | None = None
_CACHE_VALUE: dict[str, Any] | None = None


def _json_value(value: Any) -> Any:
    """Convert pandas/numpy values into strict JSON-compatible values."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    try:
        import pandas as pd

        if pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def _records(frame, limit: int = 100) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in frame.head(limit).to_dict(orient="records")
    ]


def _read_excel(path: Path, sheet: str):
    import pandas as pd

    if not path.is_file():
        return None
    try:
        return pd.read_excel(path, sheet_name=sheet)
    except (ValueError, OSError):
        return None


def _number(frame, column: str, default: float = 0.0):
    import pandas as pd

    if frame is None or column not in frame:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def _date_text(value: Any) -> str:
    converted = _json_value(value)
    return str(converted or "")[:10]


def _latest_nonzero(frame, value_columns: list[str], limit: int = 40):
    if frame is None or frame.empty:
        return frame
    result = frame.copy()
    mask = None
    for column in value_columns:
        values = _number(result, column)
        current = values.gt(0)
        mask = current if mask is None else (mask | current)
    if mask is not None:
        result = result.loc[mask]
    sort_columns = [column for column in ("date", "school_code", "grade", "class_id") if column in result]
    if sort_columns:
        result = result.sort_values(sort_columns, ascending=[False] + [True] * (len(sort_columns) - 1))
    return result.head(limit)


def _artifact_signature(model_dir: Path, manifest_path: Path) -> tuple[tuple[str, int, int], ...]:
    paths = sorted(path for path in model_dir.iterdir() if path.is_file()) if model_dir.is_dir() else []
    if manifest_path.is_file():
        paths.append(manifest_path)
    return tuple((path.name, path.stat().st_mtime_ns, path.stat().st_size) for path in paths)


def _build_payload(model_dir: Path, manifest_path: Path) -> dict[str, Any]:
    import pandas as pd

    if not model_dir.is_dir():
        return {
            "available": False,
            "message": "尚未生成学校数据治理成果，请先运行 scripts/run_data_governance.py。",
            "artifacts": [],
        }
    artifacts = sorted(path for path in model_dir.iterdir() if path.is_file())
    files = [path for path in artifacts if path.suffix.lower() == ".xlsx"]
    if not artifacts:
        return {
            "available": False,
            "message": "尚未生成学校数据治理成果，请先运行 scripts/run_data_governance.py。",
            "artifacts": [],
        }

    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            manifest = {}

    audit_summary = _read_excel(model_dir / "01_import_audit.xlsx", "00_file_summary")
    audit_issues = _read_excel(model_dir / "01_import_audit.xlsx", "01_issues")
    audit_missing = _read_excel(model_dir / "01_import_audit.xlsx", "03_missing")
    cleaned = _read_excel(model_dir / "02_clean_records.xlsx", "cleaned_records")
    rejected = _read_excel(model_dir / "02_clean_records.xlsx", "rejected_records")
    duplicates = _read_excel(model_dir / "02_clean_records.xlsx", "duplicate_records")
    episodes = _read_excel(model_dir / "04_syndromic_episodes.xlsx", "episodes")
    realtime = _read_excel(model_dir / "05-1_realtime_summary.xlsx", "data")
    grade_daily = _read_excel(model_dir / "05-3_grade_daily.xlsx", "data")
    school_daily = _read_excel(model_dir / "05-4_school_daily.xlsx", "data")

    if realtime is not None and "date" in realtime:
        realtime = realtime.sort_values("date").tail(35)

    date_values = []
    if episodes is not None:
        for column in ("onset_date", "first_report_date"):
            if column in episodes:
                parsed = pd.to_datetime(episodes[column], errors="coerce").dropna()
                if not parsed.empty:
                    date_values.extend([parsed.min(), parsed.max()])

    def flag_count(column: str) -> int:
        if episodes is None or column not in episodes:
            return 0
        return int(_number(episodes, column).gt(0).sum())

    class_activity = None
    if episodes is not None and not episodes.empty:
        required = ["onset_date", "school_code", "grade", "class_id"]
        if all(column in episodes for column in required):
            active = episodes.loc[_number(episodes, "broad_ari").gt(0)].copy()
            active["absence_count"] = _number(active, "respiratory_absence").gt(0).astype(int)
            active["visit_count"] = _number(active, "respiratory_visit").gt(0).astype(int)
            class_activity = (
                active.groupby(required, dropna=False, as_index=False)
                .agg(event_count=("episode_id", "size"), absence_count=("absence_count", "sum"), visit_count=("visit_count", "sum"))
                .sort_values(["onset_date", "school_code", "grade", "class_id"], ascending=[False, True, True, True])
                .rename(columns={"onset_date": "date"})
            )

    overview = {
        "source_rows": int(_number(audit_summary, "rows").sum()) if audit_summary is not None else 0,
        "cleaned_rows": int(len(cleaned)) if cleaned is not None else 0,
        "rejected_rows": int(len(rejected)) if rejected is not None else 0,
        "duplicate_rows": int(len(duplicates)) if duplicates is not None else 0,
        "student_episodes": int(len(episodes)) if episodes is not None else 0,
        "broad_ari_episodes": flag_count("broad_ari"),
        "fever_ari_episodes": flag_count("fever_ari"),
        "ili_like_episodes": flag_count("ili_like"),
        "schools": int(episodes["school_code"].nunique()) if episodes is not None and "school_code" in episodes else 0,
        "classes": int(episodes["class_id"].nunique()) if episodes is not None and "class_id" in episodes else 0,
        "date_start": _date_text(min(date_values)) if date_values else "",
        "date_end": _date_text(max(date_values)) if date_values else "",
    }

    missing_top = []
    if audit_missing is not None and "missing_pct" in audit_missing:
        missing_top = _records(audit_missing.sort_values("missing_pct", ascending=False), 12)

    model: dict[str, Any] = {}
    baseline_path = model_dir / "06_baseline_predictions.xlsx"
    diagnostics = _read_excel(model_dir / "06_baseline_predictions.xlsx", "diagnostics")
    model["baseline"] = {
        "available": baseline_path.is_file(),
        "diagnostics": _records(diagnostics, 5),
    }

    cluster_path = model_dir / "07_cluster_concentration.xlsx"
    model["concentration"] = {
        "available": cluster_path.is_file(),
    }

    sequential_path = model_dir / "08_sequential_detection.xlsx"
    thresholds = _read_excel(model_dir / "08_sequential_detection.xlsx", "thresholds")
    model["sequential"] = {
        "available": sequential_path.is_file(),
        "thresholds": _records(thresholds, 12),
    }

    events_path = model_dir / "09_candidate_events.xlsx"
    model["events"] = {
        "available": events_path.is_file(),
    }

    progression_path = model_dir / "10_progression_risk.xlsx"
    progression_status = _read_excel(model_dir / "10_progression_risk.xlsx", "model_status")
    model["progression"] = {
        "available": progression_path.is_file(),
        "model_status": _records(progression_status, 5),
    }

    latest_grades = _read_excel(model_dir / "11_dynamic_grading.xlsx", "latest_event_status")
    grade_counts: dict[str, int] = {}
    if latest_grades is not None and "final_level" in latest_grades:
        grade_counts = {str(key): int(value) for key, value in latest_grades["final_level"].fillna("unknown").value_counts().items()}
    model["grading"] = {
        "available": latest_grades is not None,
        "event_count": int(len(latest_grades)) if latest_grades is not None else 0,
        "level_counts": grade_counts,
        "latest_events": _records(latest_grades.sort_values("date", ascending=False) if latest_grades is not None and "date" in latest_grades else latest_grades, 30),
    }

    school_info = manifest.get("school", {}) if isinstance(manifest.get("school"), dict) else {}
    completed = int(school_info.get("modules_completed", 0) or 0)
    if not completed:
        prefixes = [int(path.name[:2]) for path in artifacts if path.name[:2].isdigit()]
        completed = max(prefixes, default=0)
    artifacts_match_manifest = bool(school_info) or not manifest

    return {
        "available": True,
        "generated_at": manifest.get("completed_at") or datetime.fromtimestamp(max(path.stat().st_mtime for path in files)).isoformat(timespec="seconds"),
        "pipeline": {
            "input_mode": manifest.get("input_mode") or manifest.get("mode") or "unknown",
            "modules_completed": completed,
            "prototype_only": bool(school_info.get("prototype_only", True)),
            "full_model_available": bool(model["grading"]["available"] and artifacts_match_manifest),
            "artifacts_match_manifest": artifacts_match_manifest,
        },
        "overview": overview,
        "quality": {
            "datasets": _records(audit_summary, 10),
            "issues": _records(audit_issues, 30),
            "missing_top": missing_top,
        },
        "trend": _records(realtime, 35),
        "class_activity": _records(class_activity, 40),
        "grade_activity": _records(_latest_nonzero(grade_daily, ["grade_cases", "affected_classes"]), 40),
        "school_activity": _records(_latest_nonzero(school_daily, ["school_cases", "affected_classes"]), 40),
        "model": model,
        "artifacts": [
            {"name": path.name, "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"), "size_bytes": path.stat().st_size}
            for path in artifacts
        ],
        "privacy": "仅返回学校、年级、班级及事件级聚合，不返回学生身份字段和逐条原始记录。",
    }


def school_governance_summary() -> dict[str, Any]:
    """Return a cached, privacy-preserving summary of school model artifacts."""
    global _CACHE_SIGNATURE, _CACHE_VALUE
    model_dir = PROJECT_ROOT / "data_governance" / "output" / "school_model"
    manifest_path = PROJECT_ROOT / "data_governance" / "output" / "governance_manifest.json"
    signature = _artifact_signature(model_dir, manifest_path)
    if signature != _CACHE_SIGNATURE or _CACHE_VALUE is None:
        _CACHE_VALUE = _build_payload(model_dir, manifest_path)
        _CACHE_SIGNATURE = signature
    return _CACHE_VALUE
