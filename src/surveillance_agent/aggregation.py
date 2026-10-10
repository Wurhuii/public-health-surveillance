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


def aggregate(events: List[SurveillanceEvent], scenarios: Dict, include_other: bool = False) -> List[AggregatePoint]:
    buckets = defaultdict(int)
    bucket_context = {}
    for ev in events:
        sc = scenarios.get(ev.source, {})
        scope_type = sc.get("scope_type", "province")
        freq = sc.get("freq", "week")
        d = date.fromisoformat(ev.event_date)
        key_date = _week_start(d) if freq == "week" else d
        scope_key = ev.province if scope_type == "province" else ev.org_id
        scope_label = ev.province if scope_type == "province" else str(ev.fields.get("org_name") or "")
        if not scope_key:
            scope_key = "unknown"
        for syn in map_syndromes(ev.diagnosis, ev.symptoms):
            if syn == "other" and not include_other:
                continue
            bucket_key = (ev.source, scope_type, scope_key, scope_label, syn, freq, key_date)
            buckets[bucket_key] += 1
            context = bucket_context.setdefault(
                bucket_key,
                {
                    "province": ev.province,
                    "city": ev.city,
                    "district": ev.district,
                    "place_name": str(
                        (ev.fields.get("org_name") if scope_type == "org" else "")
                        or scope_label
                        or scope_key
                    ),
                    "location": str(ev.fields.get("location") or ev.fields.get("department") or ""),
                    "setting": str(ev.fields.get("setting") or ""),
                    "latest_event_date": ev.event_date,
                },
            )
            if ev.event_date > context.get("latest_event_date", ""):
                context["latest_event_date"] = ev.event_date

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
        for d in _iter_dates(start, end, freq):
            point_context = dict(context_by_date.get(d, series_context))
            point_context["latest_event_date"] = series_context["latest_event_date"]
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
