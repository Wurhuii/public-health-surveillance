from __future__ import annotations

from typing import Any, Dict, List

from ..agent.schema_mapping import ALIASES, PRIMARY_FIELDS


def _space_noise(field: str) -> str:
    if len(field) <= 2:
        return field + " "
    mid = len(field) // 2
    return field[:mid] + " " + field[mid:]


def _underscore_noise(field: str) -> str:
    if len(field) <= 2:
        return field + "_"
    mid = len(field) // 2
    return field[:mid] + "_" + field[mid:]


def generate_drift_cases(source: str) -> List[Dict[str, Any]]:
    spec = PRIMARY_FIELDS.get(source, {})
    required = list(spec.get("required", []))
    optional = list(spec.get("optional", []))
    all_fields = required + optional

    cases: List[Dict[str, Any]] = []
    for f in all_fields:
        cases.append({"noisy": f, "target": f, "expected": "map", "case": "original", "source": source})
        cases.append({"noisy": _space_noise(f), "target": f, "expected": "map", "case": "space_noise", "source": source})
        cases.append({"noisy": _underscore_noise(f), "target": f, "expected": "map", "case": "underscore_noise", "source": source})
        for alias in ALIASES.get(f, []):
            cases.append({"noisy": alias, "target": f, "expected": "map", "case": "alias", "source": source})

    cases.append({"noisy": "完全不存在的字段XYZ", "target": None, "expected": "reject", "case": "unknown_field", "source": source})
    cases.append({"noisy": "random_unknown_col", "target": None, "expected": "reject", "case": "unknown_field", "source": source})
    return cases


def static_primary_map(noisy: str, source: str) -> str:
    if noisy is None:
        return None
    spec = PRIMARY_FIELDS.get(source, {})
    known = list(spec.get("required", [])) + list(spec.get("optional", []))
    if noisy in known:
        return noisy
    return None


def _normalize(s: str) -> str:
    return s.replace(" ", "").replace("_", "").strip()


def constrained_map(noisy: str, source: str) -> str:
    if noisy is None:
        return None
    spec = PRIMARY_FIELDS.get(source, {})
    known = list(spec.get("required", [])) + list(spec.get("optional", []))
    if noisy in known:
        return noisy
    norm_noisy = _normalize(noisy)
    for f in known:
        if _normalize(f) == norm_noisy:
            return f
    for target, aliases in ALIASES.items():
        for a in aliases:
            if _normalize(a) == norm_noisy:
                return target
    return None


def evaluate_method(cases: List[Dict[str, Any]], method) -> Dict[str, Any]:
    tp = fp = fn = tn = 0
    for c in cases:
        pred = method(c["noisy"], c["source"])
        if c["expected"] == "map":
            if pred == c["target"]:
                tp += 1
            else:
                fn += 1
        else:
            if pred is None:
                tn += 1
            else:
                fp += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "correct_reject": tn,
        "silent_error": fp,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }
