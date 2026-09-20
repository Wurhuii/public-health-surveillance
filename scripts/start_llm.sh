#!/usr/bin/env bash
# 启动本地 LLM 服务并自检（智算平台每个新 worker 节点需重新执行一次）
#
# 用法：
#   bash scripts/start_llm.sh                # 默认端口 8002
#   bash scripts/start_llm.sh 8001           # 换端口
#   LLM_FORCE_PORT=1 bash scripts/start_llm.sh   # 强制释放被占端口后再起（慎用）
set -u

PORT="${1:-8002}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 已在跑且是我们的服务 -> 直接退出
HEALTH="$(curl -s -m 3 "http://127.0.0.1:${PORT}/health" 2>/dev/null)"
if echo "$HEALTH" | grep -q '"status":"ok"'; then
  echo "[start_llm] 服务已在 ${PORT} 端口运行: $HEALTH"
  exit 0
fi

# 端口被别的服务占着（比如平台存根返回 422/detail）-> 明确提示
if [ -n "$HEALTH" ]; then
  echo "[start_llm] 警告：端口 ${PORT} 已被其他服务占用，其 /health 返回："
  echo "           $HEALTH"
  echo "[start_llm] 这不是我们的服务（我们的标志是 {\"status\":\"ok\",\"model\":...}）。"
  if [ "${LLM_FORCE_PORT:-0}" != "1" ]; then
    echo "[start_llm] 请二选一："
    echo "[start_llm]   (a) 换端口：      bash scripts/start_llm.sh 8003"
    echo "[start_llm]   (b) 强制释放再起：LLM_FORCE_PORT=1 bash scripts/start_llm.sh $PORT"
    exit 1
  fi
fi

# 可选：强制释放被占端口
if [ "${LLM_FORCE_PORT:-0}" = "1" ]; then
  echo "[start_llm] LLM_FORCE_PORT=1，释放 ${PORT} 端口..."
  fuser -k "${PORT}/tcp" 2>/dev/null || true
  sleep 1
fi

mkdir -p var
nohup python scripts/llm_server.py --host 0.0.0.0 --port "$PORT" > var/llm_server.log 2>&1 &
PID=$!
echo "[start_llm] 已启动 PID=$PID (端口 $PORT)，等待模型加载..."

for _ in $(seq 1 90); do
  sleep 2
  H="$(curl -s -m 3 "http://127.0.0.1:${PORT}/health" 2>/dev/null)"
  if echo "$H" | grep -q '"status":"ok"'; then
    echo "[start_llm] 就绪: $H"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "[start_llm] 进程已退出，最近日志："
    tail -20 var/llm_server.log
    exit 1
  fi
done
echo "[start_llm] 等待超时，最近日志："
tail -20 var/llm_server.log
exit 1
