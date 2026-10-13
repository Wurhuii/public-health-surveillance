from __future__ import annotations

from typing import Dict, List, Tuple


WARNING_DETECTORS = ("ewma", "cusum", "shewhart")


def fuse_alarms(detector_results: Dict[str, Dict], watch_ratio: float = 0.7) -> str:
    """Map the three warning models to the provisional colour levels."""
    results = {
        name: detector_results[name]
        for name in WARNING_DETECTORS
        if name in detector_results
    }
    alarm_count = sum(bool(res.get("alarm", False)) for res in results.values())

    if alarm_count == 3:
        return "high"
    if alarm_count == 2:
        return "medium"
    if alarm_count == 1:
        return "watch"

    near_threshold = any(
        not res.get("alarm", False)
        and float(res.get("threshold", 0.0)) > 0
        and float(res.get("score", 0.0)) / float(res["threshold"]) >= watch_ratio
        for res in results.values()
    )
    if near_threshold:
        return "near"
    return "normal"