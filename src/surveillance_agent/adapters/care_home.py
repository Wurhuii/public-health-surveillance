from __future__ import annotations

from typing import Dict, List, Optional

from ..domain import SurveillanceEvent
from ..utils import hash_id, normalize_text, parse_date, to_iso
from .base import Adapter


class CareHomeAdapter(Adapter):
    source = "care_home"

    @classmethod
    def recognizes(cls, header: List[str]) -> bool:
        return "老人信息Id" in header or "老人信息ID" in header or ("机构名称" in header and "入院诊断" in header)

    def parse(self, row: Dict[str, str], salt: str) -> Optional[SurveillanceEvent]:
        person_id = row.get("老人信息Id") or row.get("老人信息ID") or ""
        hospital_no = row.get("住院号") or ""
        org_id = row.get("机构id") or row.get("机构编码id") or row.get("机构编码") or ""
        org_name = row.get("机构名称") or ""

        if not person_id and not hospital_no:
            return None

        event_date = parse_date(row.get("入院时间"))
        if event_date is None:
            return None

        diagnosis = " ".join(x for x in [row.get("入院诊断"), row.get("诊断名称")] if x)
        symptoms = row.get("入院诊断") or ""

        return SurveillanceEvent(
            event_id=hash_id(f"care_home:{person_id}:{hospital_no}:{to_iso(event_date)}:{row.get('_index')}", salt),
            source=self.source,
            org_id=hash_id(org_id or org_name, salt),
            province=row.get("省") or "",
            city=row.get("城市") or "",
            district=row.get("行政区划") or "",
            event_date=to_iso(event_date),
            diagnosis=diagnosis,
            symptoms=symptoms,
            fields={
                "org_name": org_name,
                "status": row.get("状态") or "",
                "longitude": row.get("经度") or "",
                "latitude": row.get("维度") or "",
            },
        )

    def quality_issues(self, row: Dict[str, str]) -> List[str]:
        issues = []
        if not (row.get("省") or "").strip():
            issues.append("missing_province")
        return issues


class HospitalAdapter(Adapter):
    source = "hospital"

    @classmethod
    def recognizes(cls, header: List[str]) -> bool:
        return "门诊流水号" in header and "西医诊断名称" in header

    def parse(self, row: Dict[str, str], salt: str) -> Optional[SurveillanceEvent]:
        visit_no = row.get("门诊流水号") or ""
        org_code = row.get("医疗机构组织代码") or row.get("机构") or ""

        event_date = parse_date(row.get("就诊日期"))
        if event_date is None:
            return None

        onset_date = parse_date(row.get("发病日期"))

        return SurveillanceEvent(
            event_id=hash_id(f"hospital:{visit_no}:{row.get('_index')}", salt),
            source=self.source,
            org_id=hash_id(org_code, salt),
            province=row.get("省") or "",
            city=row.get("城市") or "",
            district=row.get("县") or row.get("行政区划名称") or "",
            event_date=to_iso(event_date),
            diagnosis=row.get("西医诊断名称") or "",
            symptoms=row.get("现病史") or "",
            fields={
                "onset_date": to_iso(onset_date) if onset_date else "",
                "department": row.get("科室名称") or "",
                "gender": row.get("性别") or "",
                "age": row.get("年龄") or "",
            },
        )

    def quality_issues(self, row: Dict[str, str]) -> List[str]:
        issues = []
        if not (row.get("省") or "").strip():
            issues.append("missing_province")
        event_date = parse_date(row.get("就诊日期"))
        onset_date = parse_date(row.get("发病日期"))
        if event_date and onset_date and onset_date > event_date:
            issues.append("onset_after_visit")
        return issues


class SchoolAdapter(Adapter):
    source = "school"

    @classmethod
    def recognizes(cls, header: List[str]) -> bool:
        return any(k in header for k in ("缺勤", "缺课", "班级", "学校名称", "学校"))

    def parse(self, row: Dict[str, str], salt: str) -> Optional[SurveillanceEvent]:
        record_id = row.get("记录ID") or row.get("记录id") or row.get("序号") or ""
        org_name = row.get("学校名称") or row.get("学校") or row.get("机构名称") or ""

        date_col = next((k for k in ("日期", "记录日期", "症状日期") if k in row), None)
        event_date = parse_date(row.get(date_col)) if date_col else None
        if event_date is None:
            return None

        symptoms = " ".join(x for x in (row.get("症状"), row.get("症状描述")) if x)
        diagnosis = symptoms

        return SurveillanceEvent(
            event_id=hash_id(f"school:{org_name}:{record_id}:{to_iso(event_date)}:{row.get('_index')}", salt),
            source=self.source,
            org_id=hash_id(org_name, salt),
            province=row.get("省") or "",
            city=row.get("城市") or "",
            district=row.get("区县") or row.get("行政区划") or "",
            event_date=to_iso(event_date),
            diagnosis=diagnosis,
            symptoms=symptoms,
            fields={"org_name": org_name},
        )

    def quality_issues(self, row: Dict[str, str]) -> List[str]:
        return []
