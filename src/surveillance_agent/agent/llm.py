from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from ..config import load_config


def get_llm_settings():
    cfg = load_config().get("llm", {})
    mode = os.environ.get("SURVEILLANCE_LLM_MODE") or cfg.get("mode", "off")
    if mode != "local_http":
        return None
    return {
        "base_url": os.environ.get("SURVEILLANCE_LLM_BASE_URL") or cfg.get("base_url", "http://127.0.0.1:8002/v1"),
        "model": os.environ.get("SURVEILLANCE_LLM_MODEL") or cfg.get("model", "local-model"),
        "api_key": os.environ.get("SURVEILLANCE_LLM_API_KEY") or cfg.get("api_key", ""),
        "timeout": float(os.environ.get("SURVEILLANCE_LLM_TIMEOUT", "120")),
        "retries": int(os.environ.get("SURVEILLANCE_LLM_RETRIES", "2")),
        "temperature": float(os.environ.get("SURVEILLANCE_LLM_TEMPERATURE", "0.2")),
        "max_tokens": int(os.environ.get("SURVEILLANCE_LLM_MAX_TOKENS", "0")) or None,
    }


def get_llm() -> Optional[Callable[[str], str]]:
    settings = get_llm_settings()
    if settings is None:
        return None
    base_url = settings["base_url"]
    model = settings["model"]
    api_key = settings["api_key"]

    def _call(prompt: str) -> str:
        url = base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": settings["temperature"],
        }
        if settings["max_tokens"]:
            body["max_tokens"] = settings["max_tokens"]
        last_err = None
        for attempt in range(settings["retries"]):
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            try:
                with urllib.request.urlopen(req, timeout=settings["timeout"]) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "replace")[:500]
                except Exception:
                    pass
                last_err = f"HTTP {exc.code}: {detail}"
                time.sleep(1 + attempt)
            except Exception as exc:
                last_err = exc
                time.sleep(1 + attempt)
        raise RuntimeError(f"LLM call failed after {settings['retries']} attempts -> {last_err}")

    return _call


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _repair_json(frag: str) -> str:
    import re

    frag = re.sub(r",\s*([}\]])", r"\1", frag)
    frag = frag.replace("None", "null").replace("True", "true").replace("False", "false")
    return frag


def _parse_json_obj(frag: str):
    if not frag:
        return None
    try:
        return json.loads(frag)
    except Exception:
        pass
    try:
        return json.loads(_repair_json(frag))
    except Exception:
        pass
    try:
        import ast

        return ast.literal_eval(frag)
    except Exception:
        return None


def extract_json(text):
    """从 LLM 输出中提取第一个 JSON 对象。

    容忍：代码围栏、前后缀文字、单引号（Python 字面量风格）、尾随逗号、
    None/True/False 等不严格 JSON。
    """
    if not text:
        return None
    text = str(text).strip()
    m = _JSON_BLOCK_RE.search(text)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                obj = _parse_json_obj(text[start : i + 1])
                if obj is not None:
                    return obj
    return _parse_json_obj(text[start:])
