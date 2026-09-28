#!/usr/bin/env bash
# 查看一键启动的 LLM、Web/API 和最近一次流水线状态。
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

WEB_PORT="${WEB_PORT:-8080}"
LLM_BASE_URL="${SURVEILLANCE_LLM_BASE_URL:-}"
if [ -z "$LLM_BASE_URL" ] && [ -f var/llm_runtime.json ]; then
  LLM_BASE_URL="$(python -c 'import json; print(json.load(open("var/llm_runtime.json", encoding="utf-8")).get("base_url", ""))' 2>/dev/null || true)"
fi
LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:8002/v1}"

check_pid() {
  local label="$1"
  local pid_file="$2"
  if [ -f "$pid_file" ]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "[status_all] ${label}: 运行中 PID=${pid}"
    else
      echo "[status_all] ${label}: PID文件存在，但进程已退出（PID=${pid}）"
    fi
  else
    echo "[status_all] ${label}: 未找到PID文件"
  fi
}

echo "============================================================"
check_pid "LLM服务" "var/llm_server.pid"
if curl -kfsS -m 3 "${LLM_BASE_URL%/}/models" >/dev/null 2>&1; then
  echo "[status_all] LLM接口: 正常 ${LLM_BASE_URL}"
else
  echo "[status_all] LLM接口: 不可用 ${LLM_BASE_URL}"
fi

check_pid "Web/API服务" "var/web_server.pid"
if curl -fsS -m 3 "http://127.0.0.1:${WEB_PORT}/api/health" >/dev/null 2>&1; then
  echo "[status_all] Web/API接口: 正常 http://127.0.0.1:${WEB_PORT}/"
else
  echo "[status_all] Web/API接口: 不可用 http://127.0.0.1:${WEB_PORT}/"
fi

if [ -f var/pipeline_latest.log ]; then
  echo "[status_all] 最近一次流水线日志: var/pipeline_latest.log"
  tail -12 var/pipeline_latest.log
else
  echo "[status_all] 尚无流水线日志"
fi
echo "============================================================"
