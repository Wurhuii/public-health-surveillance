from __future__ import annotations

from typing import Dict, List, Optional

from ..domain import SurveillanceEvent
from ..utils import hash_id, parse_date, to_iso
from .base import Adapter


class MarketAdapter(Adapter):
    """Adapter for person/event-level or daily aggregate market reports."""

    source = "market"

    @classmethod
    def recognizes(cls, header: List[str]) -> bool:
        has_place = any(k in header for k in ("市场编码", "市场名称", "场所编码", "场所名称"))
        has_date = any(k in header for k in ("统计日期", "上报日期", "日期"))
        has_signal = any(k in header for k in ("症状", "症状描述", "诊断名称", "病例数", "人数"))
        return has_place and has_date and has_signal

    def parse(self, row: Dict[str, str], salt: str) -> Optional[SurveillanceEvent]:
        org_code = row.get("市场编码") or row.get("场所编码") or row.get("机构编码") or ""
        org_name = row.get("市场名称") or row.get("场所名称") or row.get("机构名称") or ""
        raw_date = row.get("统计日期") or row.get("上报日期") or row.get("日期")
        event_date = parse_date(raw_date)
        if event_date is None or not (org_code or org_name):
            return None

        symptoms = row.get("症状") or row.get("症状描述") or ""
        diagnosis = row.get("诊断名称") or symptoms
        record_id = (
            row.get("记录ID") or row.get("人员ID") or row.get("从业人员ID")
            or f"aggregate:{row.get('_index', '')}"
        )
        try:
            event_count = max(1, int(float(row.get("病例数") or row.get("人数") or 1)))
        except (TypeError, ValueError):
            event_count = 1

        return SurveillanceEvent(
            event_id=hash_id(f"market:{org_code or org_name}:{record_id}:{to_iso(event_date)}", salt),
            source=self.source,
            org_id=hash_id(org_code or org_name, salt),
            province=row.get("省") or row.get("省份") or "",
            city=row.get("城市") or row.get("市") or "",
            district=row.get("区县") or row.get("行政区划") or "",
            event_date=to_iso(event_date),
            diagnosis=diagnosis,
            symptoms=symptoms,
            fields={
                "org_name": org_name,
                "org_code": org_code,
                "place_type": "market",
                "event_count": event_count,
                "update_time": row.get("数据更新时间") or row.get("上报时间") or "",
                "location": row.get("摊位区域") or row.get("区域") or "",
                "population_denominator": row.get("从业人员总数") or row.get("监测人数") or "",
                "person_key": row.get("从业人员脱敏键") or row.get("从业人员ID") or "",
                "severe": row.get("重症标记") or "",
                "pathogen": row.get("病原体名称") or "",
                "pathogen_result": row.get("病原检测结果") or "",
                "scheduled_update_time": row.get("固定上报时间") or "",
                "is_workday": row.get("是否工作日") or "",
            },
        )

    def quality_issues(self, row: Dict[str, str]) -> List[str]:
        issues: List[str] = []
        if not (row.get("市场编码") or row.get("场所编码") or row.get("机构编码")):
            issues.append("missing_market_code")
        if not (row.get("数据更新时间") or row.get("上报时间")):
            issues.append("missing_update_time")
        if not (row.get("从业人员总数") or row.get("监测人数")):
            issues.append("missing_market_denominator")
        return issues
