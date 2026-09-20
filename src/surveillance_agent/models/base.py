from __future__ import annotations

from typing import Dict, List, Tuple


class Detector:
    name = "base"

    def __init__(self, params: Dict[str, float] = None):
        self.params = params or {}

    def compute(self, history: List[float], current: float) -> Tuple[float, float, float, bool]:
        raise NotImplementedError
