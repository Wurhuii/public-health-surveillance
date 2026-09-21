from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional

from ..config import PROJECT_ROOT, load_config


def _runtime_settings() -> dict:
    """Read settings written by scripts/start_llm.sh, if present."""
    path = Path(PROJECT_ROOT) / "var" / "llm_runtime.json"
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def get_llm_settings():
    cfg = load_config().get("llm", {})
    runtime = _runtime_settings()
    mode = os.environ.get("SURVEILLANCE_LLM_MODE") or runtime.get("mode") or cfg.get("mode", "off")
    if mode not in ("local_http", "openai", "vllm", "mindie"):
        return None
    return {
        "mode": mode,
        "backend": os.environ.get("SURVEILLANCE_LLM_BACKEND") or runtime.get("backend", "openai"),
        "base_url": os.environ.get("SURVEILLANCE_LLM_BASE_URL") or runtime.get("base_url") or cfg.get("base_url", "http://127.0.0.1:8002/v1"),
        "model": os.environ.get("SURVEILLANCE_LLM_MODEL") or runtime.get("model") or cfg.get("model", "local-model"),
        "api_key": os.environ.get("SURVEILLANCE_LLM_API_KEY") or cfg.get("api_key", ""),
        "timeout": float(os.environ.get("SURVEILLANCE_LLM_TIMEOUT", cfg.get("timeout", 120))),
        "retries": int(os.environ.get("SURVEILLANCE_LLM_RETRIES", cfg.get("retries", 2))),
        "temperature": float(os.environ.get("SURVEILLANCE_LLM_TEMPERATURE", cfg.get("temperature", 0.0))),
        "max_tokens": int(os.environ.get("SURVEILLANCE_LLM_MAX_TOKENS", cfg.get("max_tokens", 256))) or None,
        "concurrency": max(1, int(os.environ.get("SURVEILLANCE_LLM_CONCURRENCY", runtime.get("concurrency", cfg.get("concurrency", 4))))),
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


def get_llm_batch() -> Optional[Callable[[List[str]], List[str]]]:
    """Return the bundled server's native batch client when available."""
    settings = get_llm_settings()
    if settings is None or settings.get("backend") != "transformers":
        return None
    base_url = settings["base_url"]
    api_key = settings["api_key"]

    def _call(prompts: List[str]) -> List[str]:
        if not prompts:
            return []
        url = base_url.rstrip("/") + "/chat/completions/batch"
        request_body = {
            "requests": [
                {
                    "model": settings["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": settings["temperature"],
                    "max_tokens": settings["max_tokens"],
                }
                for prompt in prompts
            ]
        }
        last_err = None
        for attempt in range(settings["retries"]):
            req = urllib.request.Request(
                url,
                data=json.dumps(request_body).encode("utf-8"),
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            try:
                with urllib.request.urlopen(req, timeout=settings["timeout"]) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                outputs = result.get("outputs")
                if not isinstance(outputs, list) or len(outputs) != len(prompts):
                    raise ValueError("invalid batch response")
                return [str(output) for output in outputs]
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:500]
                last_err = f"HTTP {exc.code}: {detail}"
            except Exception as exc:
                last_err = exc
            time.sleep(1 + attempt)
        raise RuntimeError(f"LLM batch call failed after {settings['retries']} attempts -> {last_err}")

    return _call


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _repair_json(frag: str) -> str:
    import re

    frag = re.sub(r",\s*([}\]])", r"\1", frag)
    # Small instruction-tuned models occasionally emit a closing quote after
    # an otherwise unquoted JSON number, for example: ``"value": 5.0"``.
    # Remove only that unmatched trailing quote; correctly quoted numbers are
    # unaffected because they have an opening quote before the number.
    frag = re.sub(
        r'(:\s*-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"\s*([,}\]])',
        r"\1\2",
        frag,
    )
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
