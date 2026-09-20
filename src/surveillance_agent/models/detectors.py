from __future__ import annotations

import statistics
from typing import Dict, List, Tuple

from .base import Detector


def _std(values: List[float]) -> float:
    if len(values) < 2:
        return 1.0
    s = statistics.pstdev(values)
    return s if s > 0 else 1.0


class EWMA(Detector):
    name = "ewma"

    def compute(self, history: List[float], current: float) -> Tuple[float, float, float, bool]:
        lam = self.params.get("lambda", 0.3)
        threshold = self.params.get("threshold", 3.0)
        if not history:
            return 0.0, current, threshold, False
        expected = history[0]
        for x in history[1:]:
            expected = lam * x + (1 - lam) * expected
        std = _std(history)
        score = (current - expected) / std
        return round(score, 4), round(expected, 4), threshold, score > threshold


class CUSUM(Detector):
    name = "cusum"

    def compute(self, history: List[float], current: float) -> Tuple[float, float, float, bool]:
        k = self.params.get("k", 0.5)
        h = self.params.get("h", 4.0)
        if not history:
            return 0.0, current, h, False
        mean = statistics.mean(history)
        std = _std(history)
        s = 0.0
        for x in history:
            z = (x - mean) / std
            s = max(0.0, s + z - k)
            if s > h:
                s = 0.0
        z = (current - mean) / std
        s = max(0.0, s + z - k)
        alarm = s > h
        return round(s, 4), round(mean, 4), h, alarm


class Shewhart(Detector):
    name = "shewhart"

    def compute(self, history: List[float], current: float) -> Tuple[float, float, float, bool]:
        threshold = self.params.get("threshold", 3.0)
        if not history:
            return 0.0, current, threshold, False
        mean = statistics.mean(history)
        std = _std(history)
        score = (current - mean) / std
        return round(score, 4), round(mean, 4), threshold, score > threshold


DETECTORS = {
    "ewma": EWMA,
    "cusum": CUSUM,
    "shewhart": Shewhart,
}


def build_detectors(detection_cfg: Dict) -> Dict[str, Detector]:
    out = {}
    for name, cls in DETECTORS.items():
        params = detection_cfg.get(name, {})
        out[name] = cls(params)
    return out
