from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional


def get_salt(default: str = "demo-only-change-me") -> str:
    env = os.environ.get("SURVEILLANCE_HASH_SALT", "")
    return env if env else default


def hash_id(text: str, salt: Optional[str] = None) -> str:
    if text is None:
        text = ""
    s = salt if salt is not None else get_salt()
    raw = f"{s}:{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text or text in ("-", "None", "nan", ""):
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y%m%d", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def to_iso(d: date) -> str:
    return d.isoformat()


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def append_jsonl(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(path: str) -> List[Any]:
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
