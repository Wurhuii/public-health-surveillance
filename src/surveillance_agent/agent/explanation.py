from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Tuple

from ..domain import RiskEvidence
from .llm import extract_json, get_llm

FORBIDDEN_PHRASES = ["已经暴发", "确诊为", "证实暴发", "确定为暴发", "疫情暴发", "已暴发"]

LEVEL_LABELS = {"high": "高", "medium": "中", "watch": "观察", "normal": "正常"}


def _evidence_claims(evidence: RiskEvidence) -> List[Dict[str, Any]]:
    """Build the auditable claims from evidence instead of trusting model formatting."""
    return [
        {"field": "observed", "value": evidence.observed, "text": f"观察值 {evidence.observed}"},
        {"field": "expected", "value": evidence.expected, "text": f"预期值 {evidence.expected}"},
        {"field": "syndrome", "value": evidence.syndrome, "text": f"症候群 {evidence.syndrome}"},
        {"field": "date", "value": evidence.date, "text": f"时间 {evidence.date}"},
    ]


def template_explain(evidence: RiskEvidence, level: str = "") -> Dict[str, Any]:
    scores = evidence.scores
    scope = evidence.scope_key
    syn_label = evidence.syndrome
    level_label = LEVEL_LABELS.get(level, level or "风险")
    text = (
        f"{scope} 的 {syn_label} 症候群在 {evidence.date} 监测值为 {evidence.observed}，"
        f"预期值为 {evidence.expected}。检测器得分：EWMA {scores.get('ewma', 0)}，"
        f"CUSUM {scores.get('cusum', 0)}，Shewhart {scores.get('shewhart', 0)}。"
        f"综合风险等级为 {level_label}。"
    )
    claims = _evidence_claims(evidence)
    return {"signal_id": evidence.signal_id, "text": text, "claims": claims, "draft_source": "template"}


def llm_explain(evidence: RiskEvidence, level: str = "") -> Dict[str, Any]:
    llm = get_llm()
    if llm is None:
        return template_explain(evidence, level)
    t0 = time.monotonic()
    required_output = {
        "text": (
            f"{evidence.scope_key}的{evidence.syndrome}症候群在{evidence.date}的监测值为"
            f"{evidence.observed}，预期值为{evidence.expected}，建议结合持续监测结果评估风险。"
        ),
        "claims": _evidence_claims(evidence),
    }
    prompt = (
        "你是一个公共卫生风险预警解释器。请严格基于给定证据生成解释，"
        "只能陈述证据内的事实，不得使用'已经暴发''确诊为'等确定性结论。\n"
        f"证据: {json.dumps(evidence.to_dict(), ensure_ascii=False)}\n"
        "只输出一个 JSON 对象，不要输出任何其他文字、解释或代码围栏，"
        "不要以'好的''以下是'等开头。必须保留示例中的 claims 字段和值，"
        "只改写 text，且不要添加证据中不存在的数字。输出示例：\n"
        f"{json.dumps(required_output, ensure_ascii=False)}"
    )
    latency_ms = None
    raw = None
    try:
        result = llm(prompt)
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        raw = result
        obj = extract_json(result)
        if not isinstance(obj, dict) or not isinstance(obj.get("text"), str) or not obj["text"].strip():
            return _fallback_with_latency(evidence, level, latency_ms, raw=raw)
        # Claims are a machine-readable projection of RiskEvidence. Rebuilding
        # them prevents copied placeholders or formatting mistakes from turning
        # an otherwise useful explanation into a parse failure.
        obj["text"] = obj["text"].strip()
        obj["claims"] = _evidence_claims(evidence)
        obj["signal_id"] = evidence.signal_id
        obj["draft_source"] = "llm"
        obj["latency_ms"] = latency_ms
        return obj
    except Exception:
        if latency_ms is None:
            latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return _fallback_with_latency(evidence, level, latency_ms, raw=raw)


def _fallback_with_latency(evidence: RiskEvidence, level: str, latency_ms: float, raw: str = None) -> Dict[str, Any]:
    draft = template_explain(evidence, level)
    if latency_ms is not None:
        draft["latency_ms"] = latency_ms
    if raw is not None:
        draft["raw_output"] = str(raw)[:800]
    return draft


def validate_draft(draft: Dict[str, Any], evidence: RiskEvidence) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    claims = draft.get("claims", [])
    if not claims:
        errors.append("no_evidence_claims")

    ev_dict = evidence.to_dict()
    numeric_fields = {"observed", "expected"}
    for claim in claims:
        field = claim.get("field")
        if field is None or field not in ev_dict:
            errors.append(f"nonexistent_field:{field}")
            continue
        value = claim.get("value")
        if field in numeric_fields:
            try:
                if abs(float(value) - float(ev_dict[field])) > 1e-9:
                    errors.append(f"number_mismatch:{field}")
            except (TypeError, ValueError):
                errors.append(f"number_mismatch:{field}")

    text = draft.get("text", "")
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text:
            errors.append(f"forbidden:{phrase}")

    return (len(errors) == 0), errors
