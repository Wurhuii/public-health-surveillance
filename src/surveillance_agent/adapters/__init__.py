from __future__ import annotations

from .base import Adapter, read_rows
from .care_home import CareHomeAdapter, HospitalAdapter, SchoolAdapter
from .market import MarketAdapter
from .registry import ADAPTERS, detect_adapter, detect_adapter_from_file
from .syndromes import map_syndromes, syndrome_label

__all__ = [
    "Adapter",
    "read_rows",
    "CareHomeAdapter",
    "HospitalAdapter",
    "SchoolAdapter",
    "MarketAdapter",
    "ADAPTERS",
    "detect_adapter",
    "detect_adapter_from_file",
    "map_syndromes",
    "syndrome_label",
]
