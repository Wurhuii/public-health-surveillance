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
    for ev in events:
        sc = scenarios.get(ev.source, {})
        scope_type = sc.get("scope_type", "province")
        freq = sc.get("freq", "week")
        d = date.fromisoformat(ev.event_date)
        key_date = _week_start(d) if freq == "week" else d
        scope_key = ev.province if scope_type == "province" else ev.org_id
        if not scope_key:
            scope_key = "unknown"
        for syn in map_syndromes(ev.diagnosis, ev.symptoms):
            if syn == "other" and not include_other:
                continue
            buckets[(ev.source, scope_type, scope_key, syn, freq, key_date)] += 1

    series = defaultdict(list)
    for (source, scope_type, scope_key, syn, freq, key_date), cnt in buckets.items():
        series[(source, scope_type, scope_key, syn, freq)].append((key_date, cnt))

    points: List[AggregatePoint] = []
    for (source, scope_type, scope_key, syn, freq), pairs in series.items():
        pairs.sort()
        start = min(p[0] for p in pairs)
        end = max(p[0] for p in pairs)
        count_by_date = dict(pairs)
        for d in _iter_dates(start, end, freq):
            points.append(
                AggregatePoint(
                    source=source,
                    scope_type=scope_type,
                    scope_key=scope_key,
                    syndrome=syn,
                    date=_display_date(d, freq),
                    count=count_by_date.get(d, 0),
                )
            )

    points.sort(key=lambda p: (p.source, p.scope_key, p.syndrome, p.date))
    return points
