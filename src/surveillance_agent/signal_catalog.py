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
