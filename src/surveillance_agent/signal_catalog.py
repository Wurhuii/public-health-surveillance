from __future__ import annotations

import copy
import json
from functools import lru_cache
from typing import Any, Dict, List

from .config import PROJECT_ROOT


@lru_cache(maxsize=1)
def _load() -> Dict[str, Any]:
    path = PROJECT_ROOT / "config" / "signal_catalog.json"
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def catalog_document() -> Dict[str, Any]:
    return copy.deepcopy(_load())


def signal_catalog() -> Dict[str, Dict[str, Any]]:
    return {str(item["code"]): copy.deepcopy(item) for item in _load()["signals"]}


def signal_catalog_list() -> List[Dict[str, Any]]:
    return [copy.deepcopy(item) for item in _load()["signals"]]


def classify_signal_code(
    setting_type: str,
    scope_type: str,
    syndrome: str = "respiratory",
    *,
    regional_risk: bool = False,
) -> str:
    """Map a monitoring series to the reference catalog 21-28."""
    if setting_type == "学校" and scope_type in {"province", "region"}:
        return "28"
    if setting_type == "医疗机构":
        return "21"
    if setting_type == "农贸市场":
        return "22" if syndrome == "respiratory" else "23"
    if setting_type == "养老机构":
        return "25" if regional_risk or scope_type in {"province", "region"} else "24"
    if setting_type == "学校":
        return "26" if scope_type == "class" else "27"
    raise ValueError(
        f"unsupported signal catalog binding: setting_type={setting_type}, "
        f"scope_type={scope_type}, syndrome={syndrome}"
    )
