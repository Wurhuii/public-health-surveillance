#!/usr/bin/env bash
# 停止由一键启动脚本记录的 Web/API 和 LLM 后台进程。
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

stop_pid() {
  local label="$1"
  local pid_file="$2"
  local expected="$3"
  if [ ! -f "$pid_file" ]; then
    echo "[stop_all] ${label}: 未找到PID文件，跳过"
    return
  fi

  local pid
  pid="$(cat "$pid_file")"
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "[stop_all] ${label}: 进程已经退出（PID=${pid}）"
    rm -f "$pid_file"
    return
  fi

  if [ -r "/proc/${pid}/cmdline" ]; then
    local cmdline
    cmdline="$(tr '\0' ' ' < "/proc/${pid}/cmdline")"
    if ! printf '%s' "$cmdline" | grep -Eq "$expected"; then
      echo "[stop_all] ${label}: PID=${pid} 的命令与记录不符，拒绝停止"
      echo "[stop_all] 实际命令: ${cmdline}"
      return
    fi
  fi

  echo "[stop_all] 正在停止 ${label} PID=${pid}"
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 15); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pid_file"
      echo "[stop_all] ${label}: 已停止"
      return
    fi
    sleep 1
  done
  echo "[stop_all] ${label}: 15秒内未退出，请检查 PID=${pid}"
}

stop_pid "Web/API服务" "var/web_server.pid" "surveillance_agent[[:space:]]+serve"
stop_pid "LLM服务" "var/llm_server.pid" "llm_server.py|vllm|mindieservice"
