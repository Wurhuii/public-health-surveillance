from __future__ import annotations

from typing import Dict, List


ROLE_DEFS = [
    {
        "name": "supervisor",
        "label": "Supervisor Agent",
        "responsibility": "choose next whitelisted action by state, precondition and autonomy stage",
        "uses_llm": False,
        "capabilities": ["ingest", "aggregate", "inject", "detect", "fuse", "explain", "audit", "revise", "persist"],
    },
    {
        "name": "data_governance",
        "label": "数据治理 Agent",
        "responsibility": "source identification, privacy handling, quality checks",
        "uses_llm": "optional_field_mapping",
        "capabilities": ["ingest"],
    },
    {
        "name": "aggregation",
        "label": "聚合 Agent",
        "responsibility": "build scenario time series",
        "uses_llm": False,
        "capabilities": ["aggregate"],
    },
    {
        "name": "detection",
        "label": "统计检测 Agent",
        "responsibility": "EWMA, CUSUM, Shewhart detectors",
        "uses_llm": False,
        "capabilities": ["detect"],
    },
    {
        "name": "risk_assessment",
        "label": "风险评估 Agent",
        "responsibility": "fuse detection evidence into risk level",
        "uses_llm": False,
        "capabilities": ["fuse"],
    },
    {
        "name": "explanation",
        "label": "解释 Agent",
        "responsibility": "generate explanation drafts from RiskEvidence",
        "uses_llm": "optional",
        "capabilities": ["explain"],
    },
    {
        "name": "audit",
        "label": "证据审计 Agent",
        "responsibility": "verify numbers, fields and forbidden statements",
        "uses_llm": False,
        "capabilities": ["audit"],
    },
    {
        "name": "persistence",
        "label": "持久化 Agent",
        "responsibility": "save final signals and run summary",
        "uses_llm": False,
        "capabilities": ["persist"],
    },
]

ROLE_LOOKUP: Dict[str, Dict] = {r["name"]: r for r in ROLE_DEFS}

ACTION_TO_ROLE: Dict[str, str] = {
    "ingest": "data_governance",
    "aggregate": "aggregation",
    "inject": "data_governance",
    "detect": "detection",
    "fuse": "risk_assessment",
    "explain": "explanation",
    "audit": "audit",
    "revise": "explanation",
    "persist": "persistence",
}


def list_roles() -> List[Dict]:
    return [dict(r) for r in ROLE_DEFS]
