#!/usr/bin/env bash
# 昇腾一键启动：加载 CANN/ATB 环境、检查项目和模型、选择推理后端、启动并自检。
#
# 常用方式：
#   bash scripts/start_llm.sh                         # auto: vLLM 优先，随后 transformers
#   LLM_BACKEND=vllm bash scripts/start_llm.sh 8002
#   LLM_BACKEND=mindie bash scripts/start_llm.sh      # MindIE 配置决定实际地址/端口
#   LLM_BACKEND=transformers bash scripts/start_llm.sh 8002
#
# 可配置：LLM_MODEL_DIR、LLM_MODEL_NAME、LLM_CONCURRENCY、LLM_FORCE_PORT、
# CANN_ENV、ATB_ENV、MINDIE_HOME、MINDIE_BASE_URL、VLLM_EXTRA_ARGS。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p var

PORT="${1:-${LLM_PORT:-8002}}"
REQUESTED_BACKEND="${LLM_BACKEND:-auto}"
MODEL_DIR="${LLM_MODEL_DIR:-${QWEN_MODEL_DIR:-/data/home/6120260064/model/Qwen2.5-1.5B-Instruct}}"
MODEL_NAME="${LLM_MODEL_NAME:-Qwen2.5-1.5B-Instruct}"
CANN_ENV="${CANN_ENV:-/usr/local/Ascend/ascend-toolkit/set_env.sh}"
ATB_ENV="${ATB_ENV:-/usr/local/Ascend/nnal/atb/set_env.sh}"

load_env() {
  local env_file="$1"
  local label="$2"
  if [ -f "$env_file" ]; then
    echo "[start_llm] 加载 ${label}: ${env_file}"
    set +u
    # shellcheck disable=SC1090
    source "$env_file"
    set -u
  else
    echo "[start_llm] 提示：未找到 ${label}: ${env_file}"
  fi
}

load_env "$CANN_ENV" "CANN 环境"
load_env "$ATB_ENV" "ATB 环境"
export PYTORCH_NPU_ALLOC_CONF="${PYTORCH_NPU_ALLOC_CONF:-expandable_segments:True}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

command -v python >/dev/null 2>&1 || { echo "[start_llm] 错误：当前环境找不到 python"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "[start_llm] 错误：找不到 curl"; exit 1; }
python -c "import surveillance_agent" >/dev/null 2>&1 || {
  echo "[start_llm] 错误：项目无法导入。请先在当前环境执行 pip install -e ."
  exit 1
}

if [ ! -d "$MODEL_DIR" ]; then
  echo "[start_llm] 错误：模型目录不存在: ${MODEL_DIR}"
  exit 1
fi
if [ ! -f "$MODEL_DIR/config.json" ]; then
  CONFIG_FILE="$(find "$MODEL_DIR" -maxdepth 2 -type f -name config.json -print -quit 2>/dev/null || true)"
  if [ -z "$CONFIG_FILE" ]; then
    echo "[start_llm] 错误：${MODEL_DIR} 下找不到 config.json，模型可能未下载完整"
    exit 1
  fi
  MODEL_DIR="$(dirname "$CONFIG_FILE")"
  echo "[start_llm] 自动定位模型目录: ${MODEL_DIR}"
fi

MINDIE_HOME="${MINDIE_HOME:-/usr/local/Ascend/mindie/latest/mindie-service}"
if [ "$REQUESTED_BACKEND" = "auto" ]; then
  if command -v vllm >/dev/null 2>&1; then
    BACKEND="vllm"
  else
    BACKEND="transformers"
  fi
elif [ "$REQUESTED_BACKEND" = "atb" ]; then
  BACKEND="mindie"
else
  BACKEND="$REQUESTED_BACKEND"
fi
if [ -n "${LLM_CONCURRENCY:-}" ]; then
  CONCURRENCY="$LLM_CONCURRENCY"
elif [ "$BACKEND" = "transformers" ]; then
  CONCURRENCY=1
else
  CONCURRENCY=4
fi

case "$BACKEND" in
  vllm)
    command -v vllm >/dev/null 2>&1 || {
      echo "[start_llm] 错误：找不到 vllm。请安装与当前 CANN/torch_npu 匹配的 vllm-ascend"
      exit 1
    }
    BASE_URL="http://127.0.0.1:${PORT}/v1"
    ;;
  mindie)
    [ -x "$MINDIE_HOME/bin/mindieservice_daemon" ] || {
      echo "[start_llm] 错误：找不到 MindIE daemon: ${MINDIE_HOME}/bin/mindieservice_daemon"
      exit 1
    }
    [ -f "$MINDIE_HOME/conf/config.json" ] || {
      echo "[start_llm] 错误：找不到 MindIE 配置: ${MINDIE_HOME}/conf/config.json"
      exit 1
    }
    load_env "$MINDIE_HOME/set_env.sh" "MindIE 环境"
    BASE_URL="${MINDIE_BASE_URL:-http://127.0.0.1:1025/v1}"
    echo "[start_llm] MindIE 的模型、端口和 backendType=atb 由 conf/config.json 管理"
    ;;
  transformers)
    python -c "import fastapi, torch, transformers, uvicorn" >/dev/null 2>&1 || {
      echo "[start_llm] 错误：Transformers 后端依赖不完整，请执行 pip install -r requirements-llm.txt"
      exit 1
    }
    python -c "import torch_npu" >/dev/null 2>&1 || {
      echo "[start_llm] 错误：当前昇腾环境无法导入 torch_npu，请检查 CANN 与 PyTorch 版本"
      exit 1
    }
    BASE_URL="http://127.0.0.1:${PORT}/v1"
    ;;
  *)
    echo "[start_llm] 错误：LLM_BACKEND 只支持 auto/vllm/mindie/atb/transformers"
    exit 1
    ;;
esac

api_ready() {
  local base="${BASE_URL%/}"
  curl -kfsS -m 3 "${base}/models" >/dev/null 2>&1
}

write_runtime() {
  python - "$BACKEND" "$BASE_URL" "$MODEL_NAME" "$CONCURRENCY" <<'PY'
import json
import sys
from pathlib import Path

backend, base_url, model, concurrency = sys.argv[1:]
Path("var").mkdir(exist_ok=True)
with open("var/llm_runtime.json", "w", encoding="utf-8") as fh:
    json.dump(
        {
            "mode": "local_http",
            "backend": backend,
            "base_url": base_url,
            "model": model,
            "concurrency": int(concurrency),
        },
        fh,
        ensure_ascii=False,
        indent=2,
    )
PY
  printf '%s\n' "$PORT" > var/llm_port.txt
}

if api_ready; then
  write_runtime
  echo "[start_llm] 服务已就绪: ${BASE_URL}（backend=${BACKEND}）"
  exit 0
fi

if [ "$BACKEND" != "mindie" ] && command -v fuser >/dev/null 2>&1 && fuser "${PORT}/tcp" >/dev/null 2>&1; then
  if [ "${LLM_FORCE_PORT:-0}" = "1" ]; then
    echo "[start_llm] 释放端口 ${PORT}"
    fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
    sleep 1
  else
    echo "[start_llm] 错误：端口 ${PORT} 已被占用。请换端口，或确认后使用 LLM_FORCE_PORT=1"
    exit 1
  fi
fi

LOG_FILE="var/llm_${BACKEND}.log"
case "$BACKEND" in
  vllm)
    read -r -a EXTRA_ARGS <<< "${VLLM_EXTRA_ARGS:-}"
    nohup vllm serve "$MODEL_DIR" \
      --host 0.0.0.0 --port "$PORT" \
      --served-model-name "$MODEL_NAME" \
      --trust-remote-code --dtype bfloat16 \
      --max-model-len "${VLLM_MAX_MODEL_LEN:-4096}" \
      --max-num-seqs "${VLLM_MAX_NUM_SEQS:-16}" \
      --max-num-batched-tokens "${VLLM_MAX_BATCHED_TOKENS:-4096}" \
      "${EXTRA_ARGS[@]}" > "$LOG_FILE" 2>&1 &
    PID=$!
    ;;
  mindie)
    pushd "$MINDIE_HOME" >/dev/null
    nohup ./bin/mindieservice_daemon > "$ROOT/$LOG_FILE" 2>&1 &
    PID=$!
    popd >/dev/null
    ;;
  transformers)
    nohup python scripts/llm_server.py \
      --model-dir "$MODEL_DIR" --host 0.0.0.0 --port "$PORT" \
      --max-new-tokens "${TRANSFORMERS_MAX_NEW_TOKENS:-256}" \
      --temperature "${TRANSFORMERS_TEMPERATURE:-0}" > "$LOG_FILE" 2>&1 &
    PID=$!
    ;;
esac

printf '%s\n' "$PID" > var/llm_server.pid
echo "[start_llm] 已启动 backend=${BACKEND} PID=${PID}，等待模型加载..."

WAIT_SECONDS="${LLM_START_TIMEOUT:-600}"
for ((elapsed=0; elapsed<WAIT_SECONDS; elapsed+=2)); do
  if api_ready; then
    write_runtime
    echo "[start_llm] 模型服务就绪: ${BASE_URL}"
    echo "[start_llm] 客户端配置已写入 var/llm_runtime.json，无需再手工 export"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "[start_llm] 进程已退出，最近日志："
    tail -40 "$LOG_FILE"
    exit 1
  fi
  sleep 2
done

echo "[start_llm] 等待 ${WAIT_SECONDS}s 超时，最近日志："
tail -40 "$LOG_FILE"
exit 1
