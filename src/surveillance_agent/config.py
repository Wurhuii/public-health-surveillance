from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.json"

_loaded: Dict[str, Any] = {}


def load_config(path: str = "") -> Dict[str, Any]:
    global _loaded
    if _loaded:
        return copy.deepcopy(_loaded)

    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        cfg_path = PROJECT_ROOT / "config" / "default.json"

    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    _loaded = cfg
    return copy.deepcopy(cfg)


def reset_config() -> None:
    global _loaded
    _loaded = {}


def data_dir(cfg: Dict[str, Any]) -> Path:
    env = os.environ.get("SURVEILLANCE_DATA_DIR", "")
    if env:
        return Path(env)
    rel = cfg.get("data_dir", "..")
    p = Path(rel)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def resolve_source_file(cfg: Dict[str, Any], source: str) -> Path:
    source_cfg = cfg["sources"].get(source, {})
    fname = source_cfg.get("file", "")
    return data_dir(cfg) / fname
