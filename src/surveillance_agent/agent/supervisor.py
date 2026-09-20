from __future__ import annotations

from typing import Dict, List, Set


ACTION_WHITELIST = ["ingest", "aggregate", "inject", "detect", "fuse", "explain", "audit", "revise", "persist"]

STAGE_LABELS = {
    0: "baseline",
    1: "shadow",
    2: "bounded",
    3: "adaptive",
}

PREQUISITES = {
    "aggregate": ["ingest"],
    "inject": ["aggregate"],
    "detect": ["aggregate"],
    "fuse": ["detect"],
    "explain": ["fuse"],
    "audit": ["explain"],
    "revise": ["audit"],
    "persist": ["fuse"],
}


def missing_preconditions(action: str, completed: Set[str]) -> List[str]:
    return [p for p in PREQUISITES.get(action, []) if p not in completed]
