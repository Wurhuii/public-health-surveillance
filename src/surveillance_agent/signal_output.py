from __future__ import annotations

from typing import Any, Dict, List

from .signal_catalog import signal_catalog


REPORT_FIELDS = (
    "signal_id",
    "report_time",
    "area_code",
    "setting_type",
    "setting_id_name",
    "warning_type",
    "warning_level",
    "monitored_target",
    "signal_source_type",
    "monitoring_window",
    "key_indicator_value",
    "signal_description_verification_hint",
)


def business_warning_level(model_level: str, cfg: Dict[str, Any]) -> str:
    output = cfg.get("signal_output", {})
    if output.get("level_mapping_status") not in {"approved", "demo", "provisional"}:
        return ""
    mapping = {
        "high": "Red", "medium": "Orange", "watch": "Yellow",
        "near": "Blue", "normal": "",
        **output.get("level_mapping", {}),
    }
    return str(mapping.get(model_level, ""))


def build_report_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    evidence = row.get("evidence") or {}
    p = evidence.get("presentation") or {}
    place_code = str(p.get("place_code") or "").strip()
    place_name = str(p.get("place_name") or "").strip()
    setting_id_name = "｜".join(item for item in (place_code, place_name) if item)
    targets = p.get("monitored_targets") or []
    if isinstance(targets, str):
        targets = [targets]
    explanation = str(row.get("explanation") or p.get("catalog_explanation") or "").strip()
    hints = p.get("verification_hints") or []
    if isinstance(hints, str):
        hints = [hints]
    description = "；".join(
        item for item in (
            f"〔目录{p.get('signal_code', '')}〕{p.get('signal_name', '')}".strip(),
            explanation,
            "建议核查：" + "、".join(str(item) for item in hints) if hints else "",
            "本信号用于提示核查，不代表已确认聚集或暴发。",
        ) if item
    )
    return {
        "signal_id": row.get("signal_id", ""),
        "report_time": p.get("report_time", ""),
        "area_code": p.get("area_code", ""),
        "setting_type": p.get("catalog_setting_code", ""),
        "setting_id_name": setting_id_name,
        "warning_type": p.get("catalog_type_code", ""),
        "warning_level": p.get("warning_level", ""),
        "monitored_target": ";".join(str(item) for item in targets),
        "signal_source_type": p.get("catalog_source_type", ""),
        "monitoring_window": p.get("monitoring_window", ""),
        "key_indicator_value": p.get("key_indicator", ""),
        "signal_description_verification_hint": description,
    }


def validate_report_payload(row: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    evidence = row.get("evidence") or {}
    p = evidence.get("presentation") or {}
    catalog = signal_catalog()
    missing = [field for field in REPORT_FIELDS if not payload.get(field)]
    checks: List[Dict[str, str]] = []

    def add(check_id: str, ok: bool, message: str) -> None:
        checks.append({"check_id": check_id, "status": "pass" if ok else "blocked", "message": message})

    add("C01", not missing, "12个字段完整" if not missing else "缺少：" + "、".join(missing))
    item = catalog.get(str(p.get("signal_code") or ""))
    binding_ok = bool(
        item
        and item.get("setting_code") == payload.get("setting_type")
        and item.get("warning_type") == payload.get("warning_type")
    )
    add("C02", binding_ok, "目录、场所类型和预警类型匹配" if binding_ok else "目录绑定不一致")
    add(
        "C03",
        bool(p.get("window_start") and p.get("window_end") and p.get("window_basis")),
        "时间窗口边界完整" if p.get("window_start") and p.get("window_end") and p.get("window_basis") else "时间窗口边界不完整",
    )
    add(
        "C04",
        bool(payload.get("area_code") and p.get("place_code")),
        "行政区划码和场所编码已提供" if payload.get("area_code") and p.get("place_code") else "行政区划码或场所编码待补充",
    )
    invalid_ratio = any(
        item.get("role") == "ratio" and not item.get("denominator")
        for item in p.get("evidence_items", [])
    )
    add("C05", not invalid_ratio, "比例指标包含分母" if not invalid_ratio else "比例指标缺少分母")
    add("C08", bool(p.get("update_seq")), "信号版本存在" if p.get("update_seq") else "缺少信号版本")
    add(
        "C10",
        p.get("data_status") not in {"无有效数据"},
        f"数据状态：{p.get('data_status') or '未知'}",
    )
    add(
        "C12",
        bool(payload.get("warning_level")),
        "业务等级已配置" if payload.get("warning_level") else "等级映射尚未核定，保持待研判",
    )
    blockers = [item for item in checks if item["status"] == "blocked"]
    return {
        "ready": not blockers,
        "missing_fields": missing,
        "checks": checks,
        "blockers": blockers,
        "schema_version": "1.0",
    }


def attach_report_preview(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = build_report_payload(row)
    row["report_payload"] = payload
    row["report_validation"] = validate_report_payload(row, payload)
    row["report_metadata"] = {
        "signal_code": (row.get("evidence") or {}).get("presentation", {}).get("signal_code", ""),
        "update_seq": (row.get("evidence") or {}).get("presentation", {}).get("update_seq", 1),
        "record_status": (row.get("evidence") or {}).get("presentation", {}).get("record_status", "ACTIVE"),
        "schema_version": "1.0",
    }
    return row