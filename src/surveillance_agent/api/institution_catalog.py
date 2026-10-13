from __future__ import annotations

import os
from typing import Any, Dict, List

from ..adapters.base import read_rows
from ..config import load_config, resolve_source_file


_FIELD_MAP = {
    "care_home": {
        "names": ("机构名称",),
        "codes": ("机构编码", "机构编码id", "机构id"),
        "type": "养老院",
    },
    "hospital": {
        "names": ("医疗机构名称", "机构名称"),
        "codes": ("医疗机构组织代码", "机构"),
        "type": "医院",
    },
    "school": {
        "names": ("学校名称", "学校", "机构名称"),
        "codes": ("学校编码", "机构编码"),
        "type": "学校",
    },
    "market": {
        "names": ("市场名称", "场所名称", "机构名称"),
        "codes": ("市场编码", "场所编码", "机构编码"),
        "type": "农贸市场",
    },
}


def _first(row: Dict[str, str], fields) -> str:
    return next((str(row.get(field) or "").strip() for field in fields if row.get(field)), "")


def load_institution_catalog() -> Dict[str, List[Dict[str, Any]]]:
    """Return non-personal institution names/codes exactly as supplied by source files."""
    cfg = load_config()
    result: Dict[str, List[Dict[str, Any]]] = {}
    for source, fields in _FIELD_MAP.items():
        source_cfg = cfg.get("sources", {}).get(source, {})
        if not source_cfg.get("enabled", True):
            result[source] = []
            continue
        path = resolve_source_file(cfg, source)
        if not os.path.isfile(path):
            result[source] = []
            continue
        unique = set()
        for row in read_rows(str(path)):
            name = _first(row, fields["names"])
            code = _first(row, fields["codes"])
            if name or code:
                unique.add((name, code))
        result[source] = [
            {"name": name, "code": code, "setting_type": fields["type"]}
            for name, code in sorted(unique, key=lambda item: (item[0], item[1]))
        ]
    return result
