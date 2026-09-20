from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from ..domain import AggregatePoint


def _injection_positions(shape: str, mid: int, n: int) -> List[int]:
    if shape == "spike":
        return [mid]
    if shape == "cluster":
        return [i for i in (mid, mid + 1) if i < n]
    if shape == "gradual":
        return [i for i in (mid, mid + 1, mid + 2) if i < n]
    if shape == "multimodal":
        return [i for i in (max(0, mid - 3), min(n - 1, mid + 2))]
    return [mid]


def inject_anomalies(
    points: List[AggregatePoint],
    shape: str = "gradual",
    magnitude: float = 10.0,
    num_series: int = 5,
) -> Tuple[List[AggregatePoint], Dict[str, Any]]:
    series_map = defaultdict(list)
    for p in points:
        series_map[(p.source, p.scope_type, p.scope_key, p.syndrome)].append(p)

    injections: List[Dict[str, Any]] = []
    modified = dict((id(p), p) for p in points)
    targets = [k for k, v in series_map.items() if len(v) >= 6][:num_series]

    for key in targets:
        series = sorted(series_map[key], key=lambda x: x.date)
        n = len(series)
        mid = n // 2
        for pos in _injection_positions(shape, mid, n):
            p = series[pos]
            injected = AggregatePoint(
                source=p.source,
                scope_type=p.scope_type,
                scope_key=p.scope_key,
                syndrome=p.syndrome,
                date=p.date,
                count=max(p.count, 1) + int(p.count * magnitude),
            )
            modified[id(p)] = injected
            injections.append(
                {
                    "source": p.source,
                    "scope_key": p.scope_key,
                    "syndrome": p.syndrome,
                    "date": p.date,
                    "original": p.count,
                    "injected": injected.count,
                    "shape": shape,
                    "magnitude": magnitude,
                    "true_label": 1,
                }
            )

    injected_points = sorted(
        modified.values(), key=lambda p: (p.source, p.scope_key, p.syndrome, p.date)
    )
    manifest = {"enabled": True, "shape": shape, "magnitude": magnitude, "injections": injections}
    return injected_points, manifest
