from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List

from .adapters.syndromes import map_syndromes
from .domain import AggregatePoint, SurveillanceEvent


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _display_date(d: date, freq: str) -> str:
    if freq == "week":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return d.isoformat()


def _iter_dates(start: date, end: date, freq: str):
    step = 7 if freq == "week" else 1
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=step)


def _excluded_school_date(d: date, scenario: Dict) -> bool:
    """Return true for dates that must not enter school baseline comparisons."""
    # Education authorities may designate weekend make-up school days.  An
    # explicit inclusion therefore has priority over the generic weekend rule.
    if d.isoformat() in set(scenario.get("included_dates", [])):
        return False
    if scenario.get("exclude_weekends", False) and d.weekday() >= 5:
        return True
    if d.isoformat() in set(scenario.get("excluded_dates", [])):
        return True
    for item in scenario.get("excluded_date_ranges", []):
        try:
            if date.fromisoformat(item["start"]) <= d <= date.fromisoformat(item["end"]):
                return True
        except (KeyError, TypeError, ValueError):
            continue
    return False


def _scope(ev: SurveillanceEvent, scope_type: str):
    org_name = str(ev.fields.get("org_name") or "")
    if scope_type == "province":
        return ev.province or "unknown", ev.province or "区域待补充", ""
    if scope_type == "ward":
        ward = str(ev.fields.get("ward") or ev.fields.get("department") or "病区待补充")
        return f"{ev.org_id}:{ward}", f"{org_name or '医疗机构名称待补充'} / {ward}", ward
    if scope_type == "class":
        class_name = str(ev.fields.get("class_name") or "班级待补充")
        return f"{ev.org_id}:{class_name}", f"{org_name or '学校名称待补充'} / {class_name}", class_name
    return ev.org_id or "unknown", org_name or "场所名称待补充", ""


def aggregate(events: List[SurveillanceEvent], scenarios: Dict, include_other: bool = False) -> List[AggregatePoint]:
    buckets = defaultdict(int)
    bucket_context = {}
    for ev in events:
        sc = scenarios.get(ev.source, {})
        scope_type = sc.get("scope_type", "province")
        if (
            ev.source == "yichang_focus"
            and ev.fields.get("setting") == "inpatient"
            and ev.fields.get("place_type") != "care_institution"
        ):
            scope_type = "ward"
        freq = sc.get("freq", "week")
        d = date.fromisoformat(ev.event_date)
        if ev.source == "school" and (
            _excluded_school_date(d, sc)
            or str(ev.fields.get("is_holiday", "")).lower() in {"1", "true", "yes", "是"}
        ):
            continue
        key_date = _week_start(d) if freq == "week" else d
        scope_key, scope_label, analysis_unit = _scope(ev, scope_type)
        for syn in map_syndromes(ev.diagnosis, ev.symptoms):
            if syn == "other" and not include_other:
                continue
            bucket_key = (ev.source, scope_type, scope_key, scope_label, syn, freq, key_date)
            try:
                event_count = max(1, int(float(ev.fields.get("event_count", 1))))
            except (TypeError, ValueError):
                event_count = 1
            buckets[bucket_key] += event_count
            context = bucket_context.setdefault(
                bucket_key,
                {
                    "province": ev.province,
                    "city": ev.city,
                    "district": ev.district,
                    "place_name": str(
                        (ev.fields.get("org_name") if scope_type != "province" else "")
                        or scope_label
                        or scope_key
                    ),
                    "location": str(analysis_unit or ev.fields.get("location") or ""),
                    "analysis_unit": analysis_unit,
                    "place_code": str(ev.fields.get("org_code") or "") if scope_type != "province" else "",
                    "place_type": str(ev.fields.get("place_type") or ""),
                    "setting": str(ev.fields.get("setting") or ""),
                    "care_resident_linked": bool(ev.fields.get("care_resident_linked", False)),
                    "latest_event_date": ev.event_date,
                    "latest_update_time": str(ev.fields.get("update_time") or ev.event_date),
                    "contributing_places": [],
                },
            )
            place_identity = {
                "name": str(ev.fields.get("org_name") or ""),
                "code": str(ev.fields.get("org_code") or ""),
            }
            if any(place_identity.values()) and place_identity not in context["contributing_places"]:
                context["contributing_places"].append(place_identity)
            if ev.event_date > context.get("latest_event_date", ""):
                context["latest_event_date"] = ev.event_date
            update_time = str(ev.fields.get("update_time") or ev.event_date)
            if update_time > context.get("latest_update_time", ""):
                context["latest_update_time"] = update_time

    series = defaultdict(list)
    for (source, scope_type, scope_key, scope_label, syn, freq, key_date), cnt in buckets.items():
        series[(source, scope_type, scope_key, scope_label, syn, freq)].append(
            (key_date, cnt, bucket_context[(source, scope_type, scope_key, scope_label, syn, freq, key_date)])
        )

    points: List[AggregatePoint] = []
    for (source, scope_type, scope_key, scope_label, syn, freq), pairs in series.items():
        pairs.sort()
        start = min(p[0] for p in pairs)
        end = max(p[0] for p in pairs)
        count_by_date = {p[0]: p[1] for p in pairs}
        context_by_date = {p[0]: p[2] for p in pairs}
        series_context = dict(pairs[-1][2])
        series_context["latest_event_date"] = max(p[2].get("latest_event_date", "") for p in pairs)
        series_context["latest_update_time"] = max(p[2].get("latest_update_time", "") for p in pairs)
        all_places = {
            (place.get("name", ""), place.get("code", ""))
            for _, _, item_context in pairs
            for place in item_context.get("contributing_places", [])
            if place.get("name") or place.get("code")
        }
        sorted_places = sorted(all_places, key=lambda item: (item[0], item[1]))
        series_context["contributing_place_count"] = len(sorted_places)
        series_context["contributing_places"] = [
            {"name": name, "code": code} for name, code in sorted_places[:20]
        ]
        for d in _iter_dates(start, end, freq):
            if source == "school" and _excluded_school_date(d, scenarios.get(source, {})):
                continue
            point_context = dict(context_by_date.get(d, series_context))
            point_context["latest_event_date"] = series_context["latest_event_date"]
            point_context["latest_update_time"] = series_context["latest_update_time"]
            point_context["contributing_places"] = sorted(
                point_context.get("contributing_places", []),
                key=lambda item: (item.get("name", ""), item.get("code", "")),
            )
            point_context["contributing_place_count"] = len(point_context.get("contributing_places", []))
            points.append(
                AggregatePoint(
                    source=source,
                    scope_type=scope_type,
                    scope_key=scope_key,
                    syndrome=syn,
                    date=_display_date(d, freq),
                    count=count_by_date.get(d, 0),
                    scope_label=scope_label,
                    context=point_context,
                )
            )

    points.sort(key=lambda p: (p.source, p.scope_key, p.syndrome, p.date))
    return points
