from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..domain import SurveillanceEvent
from ..utils import hash_id, parse_date, to_iso
from .base import read_rows


FILES = {
    "outpatient_record": "门诊病历.xlsx",
    "outpatient_diagnosis": "门诊诊断.xlsx",
    "outpatient_lab": "门诊检验报告.xlsx",
    "outpatient_registration": "门诊挂号.xlsx",
    "inpatient_diagnosis": "住院诊断.xlsx",
    "inpatient_lab": "住院检验报告.xlsx",
    "care_roster": "医养结合老人信息汇总.xlsx",
    "care_grid": "医养结合网格地址.xlsx",
}


def _rows(directory: Path, key: str) -> List[Dict[str, str]]:
    path = directory / FILES[key]
    return list(read_rows(str(path))) if path.is_file() else []


def _first(row: Dict[str, str], names: Iterable[str]) -> str:
    for name in names:
        value = (row.get(name) or "").strip()
        if value:
            return value
    return ""


def _clinical_person_id(row: Dict[str, str]) -> str:
    return _first(row, ("md5(`t`.`Local_ID`)", "local_id_hash", "Local_ID_hash"))


def _valid_person_keys(row: Dict[str, str], configured_fields: Iterable[str]) -> List[str]:
    return [value for field in configured_fields if (value := (row.get(field) or "").strip())]


def _parse_clinical_date(value: str):
    parsed = parse_date(value)
    if parsed is not None:
        return parsed
    text = str(value or "").strip()
    if len(text) == 14 and text.isdigit():
        return parse_date(text[:8])
    return None


def _roster_summary(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    orgs: Dict[str, Counter] = defaultdict(Counter)
    active = 0
    for row in rows:
        code = (row.get("org_code") or "").strip()
        name = (row.get("org_name") or "").strip()
        if not code and not name:
            continue
        key = code or name
        orgs[key]["residents"] += 1
        if not (row.get("leave_time") or "").strip():
            orgs[key]["active_residents"] += 1
            active += 1
    return {
        "institutions": len(orgs),
        "residents": sum(v["residents"] for v in orgs.values()),
        "active_residents": active,
        "institution_resident_counts": {
            key: {"residents": val["residents"], "active_residents": val["active_residents"]}
            for key, val in sorted(orgs.items())
        },
    }


def ingest_yichang_focus_bundle(
    directory: str,
    salt: str,
    person_key_fields: Optional[List[str]] = None,
) -> Tuple[List[SurveillanceEvent], Dict[str, Any]]:
    """Ingest the Yichang multi-table sample without guessing cross-table links.

    Medical diagnoses can produce medical-facility events when they have a real
    event date. Care-home attribution additionally requires an exact shared,
    already-deidentified person key supplied in the roster. Row position,
    demographics, and fuzzy name matching are deliberately not used.
    """

    root = Path(directory)
    person_key_fields = person_key_fields or ["local_id_hash"]
    table_rows = {key: _rows(root, key) for key in FILES}
    missing_files = [FILES[key] for key, rows in table_rows.items() if not rows]
    roster = table_rows["care_roster"]

    person_to_place: Dict[str, Dict[str, str]] = {}
    duplicate_person_keys = 0
    for row in roster:
        place = {
            "org_code": (row.get("org_code") or "").strip(),
            "org_name": (row.get("org_name") or "").strip(),
            "district": (row.get("org_district") or "").strip(),
            "place_type": "care_institution",
        }
        for key in _valid_person_keys(row, person_key_fields):
            if key in person_to_place and person_to_place[key] != place:
                duplicate_person_keys += 1
                continue
            person_to_place[key] = place

    records_by_visit: Dict[str, Dict[str, str]] = {}
    for row in table_rows["outpatient_record"]:
        visit = (row.get("menzhenliushuihao") or "").strip()
        if visit:
            records_by_visit[visit] = row

    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    quality = Counter()

    def add_diagnosis(row: Dict[str, str], setting: str) -> None:
        visit_field = "menzhenliushuihao" if setting == "outpatient" else "zhuyuanliushuihao"
        visit = (row.get(visit_field) or "").strip()
        if not visit:
            quality["missing_visit_id"] += 1
            return
        record = records_by_visit.get(visit, {}) if setting == "outpatient" else {}
        raw_date = (row.get("zhenduanriqi") or record.get("jiuzhenriqi") or "").strip()
        event_date = _parse_clinical_date(raw_date)
        if event_date is None:
            quality["invalid_or_masked_event_date"] += 1
            return
        person_id = _clinical_person_id(row) or _clinical_person_id(record)
        place = person_to_place.get(person_id)
        if place:
            quality["care_linked_visits"] += 1
        else:
            org_code = _first(row, ("yiliaojigoudaima", "baogaojigoudaima", "baogaojigoudaina"))
            if not org_code:
                quality["missing_medical_org"] += 1
                return
            place = {
                "org_code": org_code,
                "org_name": "",
                "district": "",
                "place_type": "medical_institution",
            }

        group_key = (setting, visit)
        item = grouped.setdefault(
            group_key,
            {
                "date": event_date,
                "person_id": person_id,
                "place": place,
                "diagnoses": [],
                "symptoms": " ".join(
                    x for x in (record.get("zhusu"), record.get("xianbingshi")) if x
                ),
            },
        )
        diagnosis = " ".join(x for x in (row.get("jbzdbm"), row.get("jbzdmc")) if x)
        if diagnosis and diagnosis not in item["diagnoses"]:
            item["diagnoses"].append(diagnosis)

    for row in table_rows["outpatient_diagnosis"]:
        add_diagnosis(row, "outpatient")
    for row in table_rows["inpatient_diagnosis"]:
        add_diagnosis(row, "inpatient")

    events: List[SurveillanceEvent] = []
    for (setting, visit), item in grouped.items():
        place = item["place"]
        org_ref = place["org_code"] or place["org_name"]
        events.append(
            SurveillanceEvent(
                event_id=hash_id(f"yichang_focus:{setting}:{visit}", salt),
                source="yichang_focus",
                org_id=hash_id(org_ref, salt),
                province="湖北省",
                city="宜昌市",
                district=place["district"],
                event_date=to_iso(item["date"]),
                diagnosis=" ".join(item["diagnoses"]),
                symptoms=item["symptoms"],
                fields={
                    "place_type": place["place_type"],
                    "org_name": place["org_name"],
                    "care_resident_linked": place["place_type"] == "care_institution",
                    "setting": setting,
                },
            )
        )

    clinical_ids = {
        _clinical_person_id(row)
        for key in (
            "outpatient_record",
            "outpatient_diagnosis",
            "outpatient_lab",
            "outpatient_registration",
            "inpatient_diagnosis",
            "inpatient_lab",
        )
        for row in table_rows[key]
        if _clinical_person_id(row)
    }
    grid_ids = {
        (row.get("`t`.`Local_ID`") or "").strip()
        for row in table_rows["care_grid"]
        if (row.get("`t`.`Local_ID`") or "").strip()
    }
    limitations = []
    if not person_to_place:
        limitations.append("care_roster_missing_shared_deidentified_person_key")
    if quality["invalid_or_masked_event_date"]:
        limitations.append("diagnosis_dates_invalid_or_masked")
    if not events:
        limitations.append("no_usable_time_series_events")

    report: Dict[str, Any] = {
        "status": "ok" if events else "not_ready_for_alerting",
        "directory": str(root),
        "files": {key: {"file": FILES[key], "rows": len(rows)} for key, rows in table_rows.items()},
        "missing_files": missing_files,
        "focus_place_roster": _roster_summary(roster),
        "linkage": {
            "configured_roster_person_key_fields": person_key_fields,
            "usable_roster_person_keys": len(person_to_place),
            "duplicate_roster_person_keys": duplicate_person_keys,
            "clinical_person_keys": len(clinical_ids),
            "clinical_to_roster_exact_matches": len(clinical_ids & set(person_to_place)),
            "clinical_to_grid_exact_matches": len(clinical_ids & grid_ids),
        },
        "quality_issues": dict(quality),
        "events": len(events),
        "limitations": limitations,
    }
    return events, report
