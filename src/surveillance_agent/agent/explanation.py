from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

from ..domain import RiskEvidence
from .llm import extract_json, get_llm, get_llm_batch, get_llm_settings

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


def _explanation_prompt(evidence: RiskEvidence) -> str:
    example_text = (
        f"{evidence.scope_key}的{evidence.syndrome}症候群在{evidence.date}的监测值为"
        f"{evidence.observed}，预期值为{evidence.expected}，建议结合持续监测结果评估风险。"
    )
    return (
        "你是一个公共卫生风险预警解释器。请严格基于给定证据生成解释，"
        "只能陈述证据内的事实，不得使用'已经暴发''确诊为'等确定性结论。\n"
        f"证据: {json.dumps(evidence.to_dict(), ensure_ascii=False)}\n"
        "只输出一个 JSON 对象，不要输出任何其他文字、解释或代码围栏，"
        "不要以'好的''以下是'等开头。只返回 text 字段，保持一句话，"
        "不要添加证据中不存在的数字。结构化 claims 将由程序从证据生成，无需模型重复输出。输出示例：\n"
        f"{json.dumps({'text': example_text}, ensure_ascii=False)}"
    )


def _draft_from_output(
    evidence: RiskEvidence,
    level: str,
    result: str,
    latency_ms: float,
) -> Dict[str, Any]:
    obj = extract_json(result)
    if not isinstance(obj, dict) or not isinstance(obj.get("text"), str) or not obj["text"].strip():
        return _fallback_with_latency(evidence, level, latency_ms, raw=result)
    obj["text"] = obj["text"].strip()
    obj["claims"] = _evidence_claims(evidence)
    obj["signal_id"] = evidence.signal_id
    obj["draft_source"] = "llm"
    obj["latency_ms"] = latency_ms
    return obj


def llm_explain(evidence: RiskEvidence, level: str = "", llm=None) -> Dict[str, Any]:
    llm = llm or get_llm()
    if llm is None:
        return template_explain(evidence, level)
    t0 = time.monotonic()
    latency_ms = None
    raw = None
    try:
        result = llm(_explanation_prompt(evidence))
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        raw = result
        return _draft_from_output(evidence, level, result, latency_ms)
    except Exception:
        if latency_ms is None:
            latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return _fallback_with_latency(evidence, level, latency_ms, raw=raw)


def llm_explain_many(items: List[Tuple[RiskEvidence, str]]) -> List[Dict[str, Any]]:
    """Generate explanations concurrently while preserving signal order.

    vLLM and MindIE can continuously batch these independent requests. The
    bundled Transformers server uses its native batched generation endpoint.
    """
    if not items:
        return []
    llm = get_llm()
    if llm is None:
        return [template_explain(evidence, level) for evidence, level in items]
    settings = get_llm_settings() or {}
    workers = min(max(1, int(settings.get("concurrency", 1))), len(items))
    batch_llm = get_llm_batch()
    if batch_llm is not None and workers > 1:
        drafts = []
        for offset in range(0, len(items), workers):
            chunk = items[offset : offset + workers]
            started = time.monotonic()
            try:
                outputs = batch_llm([_explanation_prompt(evidence) for evidence, _ in chunk])
                latency_ms = round((time.monotonic() - started) * 1000, 1)
                drafts.extend(
                    _draft_from_output(evidence, level, output, latency_ms)
                    for (evidence, level), output in zip(chunk, outputs)
                )
            except Exception:
                latency_ms = round((time.monotonic() - started) * 1000, 1)
                drafts.extend(
                    _fallback_with_latency(evidence, level, latency_ms)
                    for evidence, level in chunk
                )
        return drafts
    if workers == 1:
        return [llm_explain(evidence, level, llm=llm) for evidence, level in items]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="llm-explain") as pool:
        return list(pool.map(lambda item: llm_explain(item[0], item[1], llm=llm), items))


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
