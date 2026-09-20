from __future__ import annotations

from typing import Dict, List, Tuple


def fuse_alarms(detector_results: Dict[str, Dict], watch_ratio: float = 0.7) -> str:
    alarm_count = 0
    near_threshold = False
    for name, res in detector_results.items():
        if res.get("alarm", False):
            alarm_count += 1
        else:
            score = res.get("score", 0.0)
            threshold = res.get("threshold", 1.0)
            if threshold > 0 and score / threshold >= watch_ratio:
                near_threshold = True

    if alarm_count >= 2:
        return "high"
    if alarm_count == 1:
        return "medium"
    if near_threshold:
        return "watch"
    return "normal"
