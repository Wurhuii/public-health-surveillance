#!/usr/bin/env python3
"""独立 LLM 诊断探针：仅用标准库，不依赖项目代码。

在智算平台上直接运行：
    python probe_llm.py
它先检查 /health，再对模型发起两次调用，打印模型返回的【原始内容】，
用于定位解析失败 / 服务连通性问题。
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

BASE = os.environ.get("SURVEILLANCE_LLM_BASE_URL", "http://127.0.0.1:8002/v1")
MODEL = os.environ.get("SURVEILLANCE_LLM_MODEL", "Qwen2.5-1.5B-Instruct")


def chat(prompt: str, temperature: float = 0.2, max_tokens: int = 512):
    url = BASE.rstrip("/") + "/chat/completions"
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}")
    latency_ms = (time.monotonic() - t0) * 1000
    return data["choices"][0]["message"]["content"], latency_ms


def simple_extract(text):
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    s = text.find("{")
    if s < 0:
        return None
    depth = 0
    for i in range(s, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[s : i + 1])
                except Exception:
                    return None
    try:
        return json.loads(text[s:])
    except Exception:
        return None


evidence = {
    "source": "hospital",
    "scope_key": "湖北省",
    "syndrome": "respiratory",
    "date": "2026-W01",
    "observed": 12.0,
    "expected": 5.0,
    "scores": {"ewma": 4.0, "cusum": 5.0, "shewhart": 3.5},
    "thresholds": {"ewma": 3.0, "cusum": 4.0, "shewhart": 3.0},
    "alarms": {"ewma": True, "cusum": True, "shewhart": True},
}

explain_prompt = (
    "你是一个公共卫生风险预警解释器。请严格基于给定证据生成解释，"
    "只能陈述证据内的事实，不得使用'已经暴发''确诊为'等确定性结论。\n"
    f"证据: {json.dumps(evidence, ensure_ascii=False)}\n"
    "只输出一个 JSON 对象，不要输出任何其他文字、解释或代码围栏，"
    "不要以'好的''以下是'等开头。格式：\n"
    '{"text": "中文解释", "claims": [{"field": "observed", "value": 数字}, '
    '{"field": "expected", "value": 数字}, {"field": "syndrome", "value": "症候群名"}, '
    '{"field": "date", "value": "时间"}]}'
)

print("BASE_URL =", BASE)
print("MODEL    =", MODEL)
print()
print("---- 1) /health 检查 ----")
try:
    with urllib.request.urlopen(BASE.rstrip("/") + "/health", timeout=5) as r:
        print("health:", r.status, r.read().decode("utf-8", "replace")[:200])
except Exception as exc:
    print("health 失败:", exc)

for i, (name, p) in enumerate([("simple", '请只输出JSON对象 {"a": 1}'), ("explain", explain_prompt)], 1):
    print()
    print(f"---- 2.{i}) 调用 [{name}] ----")
    try:
        out, ms = chat(p)
        print(f"latency={ms:.0f}ms len={len(out)}")
        print("RAW>>>", repr(out[:600]))
        print("JSON-LOADS>>>", simple_extract(out))
    except Exception as exc:
        print("调用失败:", exc)
