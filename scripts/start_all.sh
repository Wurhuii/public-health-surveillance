#!/usr/bin/env bash
# 一键启动完整演示：LLM -> Web/API -> LangGraph 三级自治监测流程。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p var

LLM_PORT="${LLM_PORT:-8002}"
WEB_PORT="${WEB_PORT:-8080}"
AUTONOMY_STAGE="${AUTONOMY_STAGE:-3}"
INJECTION_SHAPE="${INJECTION_SHAPE:-gradual}"
INJECTION_MAGNITUDE="${INJECTION_MAGNITUDE:-10}"
START_LLM="${START_LLM:-1}"
START_WEB="${START_WEB:-1}"
RUN_PIPELINE="${RUN_PIPELINE:-1}"
RUN_GOVERNANCE="${RUN_GOVERNANCE:-1}"
GOVERNANCE_FAST="${GOVERNANCE_FAST:-0}"
CONFIG_PATH="${CONFIG_PATH:-config/governed_samples.json}"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
export SURVEILLANCE_CONFIG="$CONFIG_PATH"

command -v python >/dev/null 2>&1 || {
  echo "[start_all] 错误：当前环境找不到 python"
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  echo "[start_all] 错误：当前环境找不到 curl"
  exit 1
}
python -c "import surveillance_agent" >/dev/null 2>&1 || {
  echo "[start_all] 错误：项目无法导入，请先执行 python -m pip install -e . --no-deps"
  exit 1
}

web_ready() {
  curl -fsS -m 3 "http://127.0.0.1:${WEB_PORT}/api/health" >/dev/null 2>&1
}

start_web() {
  if web_ready; then
    echo "[start_all] Web/API 已经就绪，复用端口 ${WEB_PORT}"
    return
  fi
  if command -v fuser >/dev/null 2>&1 && fuser "${WEB_PORT}/tcp" >/dev/null 2>&1; then
    echo "[start_all] 错误：端口 ${WEB_PORT} 已被其他进程占用，且健康检查未通过"
    echo "[start_all] 请先确认占用进程，或使用 WEB_PORT=其他端口重新启动"
    exit 1
  fi

  nohup python -m surveillance_agent serve \
    --host 0.0.0.0 --port "$WEB_PORT" \
    > var/web_server.log 2>&1 &
  local web_pid=$!
  printf '%s\n' "$web_pid" > var/web_server.pid
  echo "[start_all] 已启动 Web/API PID=${web_pid}，等待健康检查..."

  for _ in $(seq 1 30); do
    if web_ready; then
      echo "[start_all] Web/API 已就绪: http://127.0.0.1:${WEB_PORT}/"
      return
    fi
    if ! kill -0 "$web_pid" 2>/dev/null; then
      echo "[start_all] Web/API 进程提前退出，最近日志："
      tail -40 var/web_server.log || true
      exit 1
    fi
    sleep 1
  done

  echo "[start_all] Web/API 启动超时，最近日志："
  tail -40 var/web_server.log || true
  exit 1
}

echo "============================================================"
echo "  省级公共卫生风险监测系统 - 一键启动"
echo "============================================================"
echo "  项目目录:      ${ROOT}"
echo "  LLM端口:       ${LLM_PORT}"
echo "  Web端口:       ${WEB_PORT}"
echo "  自治阶段:      ${AUTONOMY_STAGE}"
echo "  注入类型/强度: ${INJECTION_SHAPE} / ${INJECTION_MAGNITUDE}"
echo "  数据治理:      ${RUN_GOVERNANCE}（快速模式 ${GOVERNANCE_FAST}）"
echo "  监测配置:      ${CONFIG_PATH}"
echo "============================================================"

if [ "$RUN_GOVERNANCE" = "1" ]; then
  echo "[start_all] 1/4 运行场所数据治理包并生成标准输入"
  if [ "$GOVERNANCE_FAST" = "1" ]; then
    python scripts/run_data_governance.py --fast 2>&1 | tee var/governance_latest.log
  else
    python scripts/run_data_governance.py 2>&1 | tee var/governance_latest.log
  fi
else
  echo "[start_all] 1/4 跳过数据治理（RUN_GOVERNANCE=${RUN_GOVERNANCE}）"
fi

if [ "$START_LLM" = "1" ]; then
  echo "[start_all] 2/4 启动并检查 LLM 服务"
  bash scripts/start_llm.sh "$LLM_PORT"
else
  echo "[start_all] 2/4 跳过 LLM 启动（START_LLM=${START_LLM}）"
fi

if [ "$START_WEB" = "1" ]; then
  echo "[start_all] 3/4 启动并检查 Web/API 服务"
  start_web
  echo "[start_all] 请在 VS Code 的“端口/Ports”面板转发 ${WEB_PORT}，然后打开生成的地址"
else
  echo "[start_all] 3/4 跳过 Web/API 启动（START_WEB=${START_WEB}）"
fi

if [ "$RUN_PIPELINE" = "1" ]; then
  echo "[start_all] 4/4 执行完整监测流程"
  echo "[start_all] python -m surveillance_agent run --config ${CONFIG_PATH} --inject --shape ${INJECTION_SHAPE} --magnitude ${INJECTION_MAGNITUDE} --langgraph --autonomy-stage ${AUTONOMY_STAGE}"
  python -m surveillance_agent run \
    --config "$CONFIG_PATH" \
    --inject \
    --shape "$INJECTION_SHAPE" \
    --magnitude "$INJECTION_MAGNITUDE" \
    --langgraph \
    --autonomy-stage "$AUTONOMY_STAGE" \
    2>&1 | tee var/pipeline_latest.log
else
  echo "[start_all] 4/4 跳过监测流程（RUN_PIPELINE=${RUN_PIPELINE}）"
fi

echo "============================================================"
echo "[start_all] 一键启动完成"
if [ "$START_WEB" = "1" ]; then
  echo "[start_all] 本机检查: http://127.0.0.1:${WEB_PORT}/"
  echo "[start_all] API文档: http://127.0.0.1:${WEB_PORT}/docs"
  echo "[start_all] 服务器上请通过 VS Code Ports 转发 ${WEB_PORT} 后访问"
fi
echo "[start_all] 状态检查: bash scripts/status_all.sh"
echo "[start_all] 停止服务: bash scripts/stop_all.sh"
echo "============================================================"
