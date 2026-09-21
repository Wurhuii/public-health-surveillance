#!/usr/bin/env python3
"""OpenAI 兼容的本地 LLM 推理服务。

用 transformers 加载本地模型目录（如 Qwen2.5-1.5B-Instruct），
对外提供与 /agent/llm.py 客户端兼容的 REST 接口：

    POST /v1/chat/completions   对话补全
    GET  /v1/models             模型列表
    GET  /health                健康检查

智算平台启动示例：
    python scripts/llm_server.py --model-dir /data/home/6120260064/model \
        --host 0.0.0.0 --port 8001

依赖：transformers、torch（按平台安装，昇腾额外安装 torch_npu）。
"""
from __future__ import annotations

import argparse
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

DEFAULT_MODEL_DIR = os.environ.get("QWEN_MODEL_DIR", "/data/home/6120260064/model/Qwen2.5-1.5B-Instruct")


def _pick_device() -> str:
    if os.environ.get("SURVEILLANCE_LLM_DEVICE"):
        return os.environ["SURVEILLANCE_LLM_DEVICE"]
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    try:
        import torch_npu  # noqa: F401
        import torch

        if torch.npu.is_available():
            return "npu"
    except Exception:
        pass
    return "cpu"


def _resolve_model_dir(path: str) -> str:
    """若给定目录不含 config.json，自动在其下一层寻找含 config.json 的子目录。

    兼容 ModelScope/HuggingFace 下载成嵌套目录的情况。
    """
    if os.path.isfile(os.path.join(path, "config.json")):
        return path
    try:
        entries = sorted(os.listdir(path))
    except OSError:
        return path
    for name in entries:
        sub = os.path.join(path, name)
        if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "config.json")):
            return sub
    return path


def _check_port_free(host: str, port: int) -> None:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
    except OSError as exc:
        raise SystemExit(
            f"端口 {port} 已被占用，请先释放（fuser -k {port}/tcp）或改用 --port：{exc}"
        )
    finally:
        s.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAI-compatible chat server for a local transformers model")
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR, help="本地模型目录")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--device", default="", help="cpu / cuda / npu / auto")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.2)
    args = parser.parse_args()

    if not os.path.isdir(args.model_dir):
        raise SystemExit(f"模型目录不存在: {args.model_dir}")

    model_dir = _resolve_model_dir(args.model_dir)
    if not os.path.isfile(os.path.join(model_dir, "config.json")):
        raise SystemExit(
            f"在 {args.model_dir} 下找不到 config.json。"
            "请检查模型是否下载完整，或把 --model-dir 指向真正包含 config.json 的目录。"
        )
    if model_dir != args.model_dir:
        print(f"[llm_server] 已自动定位模型子目录: {model_dir}", flush=True)

    _check_port_free(args.host, args.port)

    device = args.device or _pick_device()
    print(f"[llm_server] 正在加载模型 {model_dir} -> device={device}", flush=True)

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    tokenizer.padding_side = "left"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    if device in ("cuda", "npu"):
        try:
            model = AutoModelForCausalLM.from_pretrained(model_dir, trust_remote_code=True, torch_dtype=torch.bfloat16)
        except Exception:
            model = AutoModelForCausalLM.from_pretrained(model_dir, trust_remote_code=True)
        if device == "npu":
            model.to("npu:0")
        else:
            model.to("cuda:0")
    else:
        model = AutoModelForCausalLM.from_pretrained(model_dir, trust_remote_code=True)
    model.eval()
    print(f"[llm_server] 模型就绪: {os.path.basename(model_dir.rstrip('/'))}", flush=True)

    app = FastAPI(title="local-llm")
    model_name = os.path.basename(model_dir.rstrip("/"))

    @app.get("/health")
    def health():
        return {"status": "ok", "model": model_name, "backend": "transformers", "batch": True}

    @app.get("/v1/models")
    def list_models():
        return {"object": "list", "data": [{"id": model_name, "object": "model"}]}

    def generate_batch(message_batches, max_new: int, temperature: float):
        prompts = [
            tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            for messages in message_batches
        ]
        inputs = tokenizer(prompts, return_tensors="pt", padding=True).to(model.device)
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new,
                temperature=temperature,
                do_sample=(temperature > 0.0),
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            )
        input_width = int(inputs.input_ids.shape[1])
        texts = []
        usages = []
        for index, output in enumerate(outputs):
            new_tokens = output[input_width:]
            texts.append(tokenizer.decode(new_tokens, skip_special_tokens=True))
            prompt_len = int(inputs.attention_mask[index].sum().item())
            comp_len = int(new_tokens.shape[0])
            usages.append(
                {
                    "prompt_tokens": prompt_len,
                    "completion_tokens": comp_len,
                    "total_tokens": prompt_len + comp_len,
                }
            )
        return texts, usages

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        body = await request.json()
        messages = body.get("messages", [])
        if not messages:
            return JSONResponse({"error": "empty messages"}, status_code=400)
        max_new = int(body.get("max_tokens") or args.max_new_tokens)
        temperature = float(body.get("temperature", args.temperature))
        texts, usages = generate_batch([messages], max_new, temperature)
        return {
            "id": "chatcmpl-" + str(int(time.time() * 1000)),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": texts[0]},
                    "finish_reason": "stop",
                }
            ],
            "usage": usages[0],
        }

    @app.post("/v1/chat/completions/batch")
    async def batch_chat_completions(request: Request):
        body = await request.json()
        requests = body.get("requests", [])
        if not isinstance(requests, list) or not requests:
            return JSONResponse({"error": "empty requests"}, status_code=400)
        if len(requests) > 16:
            return JSONResponse({"error": "batch too large; maximum is 16"}, status_code=400)
        message_batches = [item.get("messages", []) for item in requests]
        if any(not messages for messages in message_batches):
            return JSONResponse({"error": "empty messages in batch"}, status_code=400)
        max_new = max(int(item.get("max_tokens") or args.max_new_tokens) for item in requests)
        temperatures = [float(item.get("temperature", args.temperature)) for item in requests]
        if len(set(temperatures)) != 1:
            return JSONResponse({"error": "all batch temperatures must match"}, status_code=400)
        texts, usages = generate_batch(message_batches, max_new, temperatures[0])
        return {"object": "chat.completion.batch", "outputs": texts, "usage": usages}

    import uvicorn

    print(f"[llm_server] 服务已启动: http://{args.host}:{args.port}/v1", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
