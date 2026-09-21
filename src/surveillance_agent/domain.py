from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class SurveillanceEvent:
    event_id: str
    source: str
    org_id: str
    province: str
    city: str
    district: str
    event_date: str
    diagnosis: str
    symptoms: str
    fields: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AggregatePoint:
    source: str
    scope_type: str
    scope_key: str
    syndrome: str
    date: str
    count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DetectorPoint:
    source: str
    scope_type: str
    scope_key: str
    syndrome: str
    date: str
    observed: float
    expected: float
    score: float
    threshold: float
    detector: str
    alarm: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RiskEvidence:
    signal_id: str
    source: str
    scope_type: str
    scope_key: str
    syndrome: str
    date: str
    observed: float
    expected: float
    scores: Dict[str, float]
    thresholds: Dict[str, float]
    alarms: Dict[str, bool]
    model_version: str
    quality_limits: List[str] = field(default_factory=list)
    run_dates: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RiskSignal:
    signal_id: str
    level: str
    evidence: RiskEvidence
    explanation: str = ""
    explanation_source: str = ""
    requires_human_review: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "level": self.level,
            "evidence": self.evidence.to_dict(),
            "explanation": self.explanation,
            "explanation_source": self.explanation_source,
            "requires_human_review": self.requires_human_review,
        }
