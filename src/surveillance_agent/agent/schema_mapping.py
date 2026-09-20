from __future__ import annotations

import json
from typing import List

from ..config import load_config
from .llm import extract_json, get_llm


PRIMARY_FIELDS = {
    "hospital": {
        "required": ["门诊流水号", "西医诊断名称", "就诊日期"],
        "optional": ["省", "城市", "县", "医疗机构组织代码", "现病史", "发病日期"],
    },
    "care_home": {
        "required": ["老人信息Id", "入院时间"],
        "optional": ["住院号", "机构id", "机构名称", "省", "城市", "行政区划", "入院诊断", "诊断名称"],
    },
    "school": {
        "required": ["学校名称", "日期"],
        "optional": ["症状", "症状描述", "省", "城市"],
    },
}

ALIASES = {
    "老人信息Id": ["老人信息ID", "老人编号", "老人id"],
    "门诊流水号": ["流水号", "门诊号"],
    "西医诊断名称": ["诊断名称", "西医诊断"],
    "就诊日期": ["就诊时间", "看诊日期"],
    "入院时间": ["入院日期"],
    "机构名称": ["机构", "单位名称"],
}


def suggest_mapping(source: str, header: List[str]) -> dict:
    spec = PRIMARY_FIELDS.get(source, {})
    mapping = {}
    for field in list(spec.get("required", [])) + list(spec.get("optional", [])):
        if field in header:
            mapping[field] = field
            continue
        for alias in ALIASES.get(field, []):
            if alias in header:
                mapping[field] = alias
                break
    return mapping


def validate_mapping(source: str, mapping: dict) -> tuple:
    spec = PRIMARY_FIELDS.get(source, {})
    errors = []
    for field in spec.get("required", []):
        if field not in mapping or not mapping[field]:
            errors.append(f"missing_required:{field}")
    return (len(errors) == 0), errors


def propose_with_llm(source: str, header: List[str]) -> dict:
    llm = get_llm()
    if llm is None:
        return suggest_mapping(source, header)
    prompt = (
        f"数据源 {source} 的表头为 {header}。"
        f"请将表头映射到标准字段 {list(PRIMARY_FIELDS[source].get('required', [])) + list(PRIMARY_FIELDS[source].get('optional', []))}。"
        '只输出一个 JSON 对象，例如 {"标准字段": "表头名"}，不要输出任何其他文字。'
    )
    try:
        result = llm(prompt)
        mapping = extract_json(result)
        if not isinstance(mapping, dict):
            mapping = {}
        ok, _ = validate_mapping(source, mapping)
        if ok:
            return mapping
    except Exception:
        pass
    return suggest_mapping(source, header)
