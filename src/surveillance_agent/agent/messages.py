from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict


@dataclass
class AgentMessage:
    correlation_id: str
    sender: str
    receiver: str
    task: str
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:12]
