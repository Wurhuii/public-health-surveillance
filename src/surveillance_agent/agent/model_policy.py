from __future__ import annotations

import statistics
from typing import Dict, List


DEFAULT_MODELS = ["ewma", "cusum", "shewhart"]

# 序列过短时累计型方法没有足够基线，只保留对单点突增最敏感的 Shewhart。
# 变异系数(CV)很高的序列噪声大，CUSUM 的累积会把噪声放大并造成持久误报，
# 因此排除 CUSUM。序列越长、越平稳，可用越多的模型互补。
_MIN_LENGTH = 8
_HIGH_CV = 1.2
_MID_CV = 0.5


def select_models(context: Dict = None) -> List[str]:
    if not context:
        return list(DEFAULT_MODELS)
    values = context.get("values") or []
    n = len(values)
    if n < _MIN_LENGTH:
        return ["shewhart"]
    mean = statistics.mean(values)
    std = statistics.pstdev(values)
    cv = (std / mean) if mean else float("inf")
    if cv > _HIGH_CV:
        return ["ewma", "shewhart"]
    if cv > _MID_CV:
        return ["cusum", "ewma"]
    return list(DEFAULT_MODELS)


def describe_policy() -> str:
    return "adaptive_constrained"
