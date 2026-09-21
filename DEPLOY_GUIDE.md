# 智算平台部署与 LLM 接入指南

> 场景：项目部署到智算平台 `/data/home/6120260064/wrh/code`，
> 本地已有 Qwen2.5-1.5B-Instruct 模型目录 `/data/home/6120260064/model`。
> 本指南说明如何启动本地 LLM 服务，并让项目真正调用它。

---

## 1. 整体架构

```
┌────────────── 同一台机器（智算节点）───────────────┐
│                                                    │
│  [LLM 服务] scripts/llm_server.py                  │
│   transformers 加载 Qwen2.5-1.5B-Instruct           │
│   ├─ POST /v1/chat/completions                     │
│   ├─ GET  /v1/models                               │
│   └─ GET  /health          端口 8001               │
│                          ▲                         │
│                          │ OpenAI 兼容协议           │
│                          │                         │
│  [监测系统] python -m surveillance_agent ...        │
│   agent/llm.py 客户端 → 解释 Agent / 字段映射 Agent  │
│   LLM 失败自动回退确定性模板，主流程不中断            │
└────────────────────────────────────────────────────┘
```

## 2. 一次性环境准备

```bash
cd /data/home/6120260064/wrh/code

# 若平台已内置 transformers/torch 可跳过；否则：
pip install -r requirements-llm.txt
# 昇腾 NPU 节点需额外安装 torch_npu（按平台文档）；GPU 节点 torch 自带

# 安装项目核心依赖（如尚未安装）
pip install -r requirements.txt
```

## 3. 一键加载环境并启动 LLM 服务

脚本依次加载 CANN 和 ATB 环境，检查 Python、项目依赖与模型目录，选择后端，
后台启动服务并等待 `/v1/models` 可用。成功后会写入 `var/llm_runtime.json`，
监测程序会自动读取，不需要再手工执行多条 `export`。

```bash
cd /data/home/6120260064/wrh/code

# 推荐：检测到 vllm-ascend 时优先使用，否则回退 Transformers
bash scripts/start_llm.sh 8002

# 明确选择 vLLM（连续批处理，并发解释时吞吐量更高）
LLM_BACKEND=vllm bash scripts/start_llm.sh 8002

# 8002 已运行旧服务，需要切换后端时强制重启
LLM_FORCE_PORT=1 LLM_BACKEND=vllm bash scripts/start_llm.sh 8002

# 明确使用项目自带 Transformers 服务
LLM_BACKEND=transformers bash scripts/start_llm.sh 8002

# MindIE/ATB：先在 MindIE conf/config.json 中设置模型、端口和 backendType=atb
LLM_BACKEND=mindie \
MINDIE_BASE_URL=http://127.0.0.1:1025/v1 \
bash scripts/start_llm.sh
```

默认模型目录是 `/data/home/6120260064/model/Qwen2.5-1.5B-Instruct`。更换模型时设置
`LLM_MODEL_DIR` 和 `LLM_MODEL_NAME`。并发数默认是 4，可通过 `LLM_CONCURRENCY` 调整；
推荐先测试 4，再根据 NPU 内存和吞吐量测试 8。

vLLM 后端需要预先安装与服务器 CANN、PyTorch 和 Python 版本匹配的
`vllm`/`vllm-ascend`。这些组件版本必须配套，因此脚本只检查，不自动在线安装。

> **注意：智算平台每次新建/切换 worker 节点都是全新环境，`nohup` 起的服务不会保留到下一个节点。** 换节点后必须重新执行启动命令。推荐用一键脚本：

```bash
bash scripts/start_llm.sh                    # 默认 8002 端口，自动等待就绪并自检
# 若默认端口被平台存根占用（历史节点 8001 曾有此情况，返回 422），强制释放后重试：
LLM_FORCE_PORT=1 bash scripts/start_llm.sh   # 慎用：会杀掉占用该端口的进程
bash scripts/start_llm.sh 8002               # 或换端口
```

**验证服务可用：**

```bash
curl http://127.0.0.1:8002/health
# {"status":"ok","model":"model"}

curl -s http://127.0.0.1:8002/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"Qwen2.5-1.5B-Instruct","messages":[{"role":"user","content":"你好"}]}'
```

## 4. 配置项目接入 LLM

> 重要：**模型文件路径不需要写进这里的任何配置**。模型路径只用于第 3 节启动 `llm_server.py`（其默认值已指向
> `/data/home/6120260064/model/Qwen2.5-1.5B-Instruct`）。本节配置的是**客户端**连到模型服务的地址，
> `SURVEILLANCE_LLM_MODEL` 只是发给服务端的模型名字符串，服务端会按自己加载的模型响应。

两种方式任选其一（环境变量优先）：

**方式 A：环境变量（推荐，无需改配置文件）**

```bash
export SURVEILLANCE_LLM_MODE=local_http
export SURVEILLANCE_LLM_BASE_URL=http://127.0.0.1:8002/v1
export SURVEILLANCE_LLM_MODEL=Qwen2.5-1.5B-Instruct
export SURVEILLANCE_LLM_API_KEY=""          # 无鉴权可留空
# 可选调参：
export SURVEILLANCE_LLM_TEMPERATURE=0        # 解释任务使用确定性输出
export SURVEILLANCE_LLM_TIMEOUT=120          # 单次请求超时秒
export SURVEILLANCE_LLM_RETRIES=2            # 失败重试次数
export SURVEILLANCE_LLM_CONCURRENCY=4        # vLLM/MindIE 可将并发请求连续批处理
```

对应到你的环境，完整操作（在同一终端会话里依次执行）：

```bash
cd /data/home/6120260064/wrh/code

# 1) 启动模型服务（默认已指向 /data/home/6120260064/model/Qwen2.5-1.5B-Instruct，可省略 --model-dir）
nohup python scripts/llm_server.py --host 0.0.0.0 --port 8002 > var/llm_server.log 2>&1 &

# 2) 配置客户端环境变量
export SURVEILLANCE_LLM_MODE=local_http
export SURVEILLANCE_LLM_BASE_URL=http://127.0.0.1:8002/v1
export SURVEILLANCE_LLM_MODEL=Qwen2.5-1.5B-Instruct
export SURVEILLANCE_LLM_API_KEY=""

# 3) 校验 LLM 客户端可用（应打印出模型生成的一行中文）
curl -s http://127.0.0.1:8002/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"Qwen2.5-1.5B-Instruct","messages":[{"role":"user","content":"你好"}]}'

# 4) 跑 demo（环境变量仅在当前终端有效，同一终端内执行）
export PYTHONPATH=src
python -m surveillance_agent run --inject --shape gradual --magnitude 10 --autonomy-stage 1
```

注意：这些 `export` 只对**当前终端会话**有效，重开终端或换会话需重新设置；想长期生效可写入
`~/.bashrc`。若改了服务端口，`BASE_URL` 要同步改。

**方式 B：修改 `config/default.json` 的 `llm` 段**

```json
"llm": {
  "mode": "local_http",
  "base_url": "http://127.0.0.1:8002/v1",
  "model": "Qwen2.5-1.5B-Instruct",
  "api_key": ""
}
```

## 5. 运行 Demo

```bash
cd /data/home/6120260064/wrh/code
export PYTHONPATH=src
# 数据文件放在 code 的上级目录：/data/home/6120260064/wrh/*.csv

# 完整流水线（注入 gradual 异常，LLM 参与解释生成）
python -m surveillance_agent run --inject --shape gradual --magnitude 10 --autonomy-stage 1

# 启用 Supervisor LangGraph
python -m surveillance_agent run --inject --langgraph --autonomy-stage 1

# 本地页面/API（可选）
python -m surveillance_agent serve --host 0.0.0.0 --port 8080
# 浏览器访问 http://<节点IP>:8080
```

### 5.1 在 code-server（浏览器版 VS Code）里打开服务页

服务启动后，用 code-server 内置功能即可查看页面，无需安装额外浏览器插件：

- **方法 A（推荐）：内置 Simple Browser**
  1. `Ctrl+Shift+P` 打开命令面板；
  2. 输入并选择 `Simple Browser: Show`；
  3. 在 URL 输入框填 `http://127.0.0.1:8080`，回车。
  - 页面 JS 用相对路径 `/api/*` 请求，此方式页面来源正确，页面上"运行/证据"按钮和接口都能正常工作。

- **方法 B：code-server 内置代理路径**
  在 code-server 地址后追加 `/proxy/8080/`：
  `https://<你的code-server地址>/proxy/8080/`
  - 注意：经代理访问时页面里相对 `/api/*` 会指向 code-server 根路径，接口可能 404，适合只查看页面效果；接口要通请用方法 A。

- **方法 C：Ports 面板（若该版本支持）**
  `Ctrl+Shift+P` → `View: Open Ports` → 点 "+" Forward a Port → 填 `8080` → 点击生成的转发 URL。

- **方法 D：平台控制台端口映射（最稳）**
  智算平台 Web 控制台一般有工作负载/服务的端口暴露或端口转发入口，把 `8080` 映射成可访问地址，浏览器直接打开。

- LLM 服务同理可查看健康页：`http://127.0.0.1:8002/health`（Simple Browser 中输入该地址）。

**确认 LLM 真的被调用：**

- **首选**：查看本次运行目录 `var/runs/<run_id>/explanation_drafts.json`——若文本不是固定的模板句式（"监测值为…检测器得分…"），而是由模型生成的多样化中文，即 LLM 生效。
- 辅助：运行 RQ4，`grounded_llm`/`ungrounded_llm` 状态会从 `skipped_no_llm` 变为 `ready`（仅表示环境变量配置生效；RQ4 本身只做模板与伪造验证，不实际调用 LLM）：
  ```bash
  python -m surveillance_agent experiment rq4 --output var/rq4_results.json
  ```

**查看 LLM 解析成功率与单次推理延迟：**

每次 `run` 结束后，CLI 会打印一行，且结果写入 `var/runs/<run_id>/summary.json`：

```json
"explanation": {
  "llm_enabled": true,
  "drafts": 47,
  "llm_generated": 41,
  "template_fallback": 6,
  "llm_parse_success_rate": 0.8723,
  "latency": { "calls": 47, "avg_ms": 3200.5, "min_ms": 1800.2, "max_ms": 5400.8, "p95_ms": 4900.3 }
}
```

- `llm_parse_success_rate = llm_generated / drafts`：LLM 输出被 `extract_json` 成功解析成解释的占比；未成功解析（非 JSON、网络/超时异常）自动回退模板，记为 `template_fallback`；
- `latency`：每次 LLM 调用的耗时统计（毫秒）。测量点为 `llm_explain` 内 `llm(prompt)` 前后（含 HTTP 往返 + JSON 解析），即"单次推理延迟"的**端到端口径**；
- `wall_seconds` 是整个解释阶段的墙钟时间；并发开启后它会小于各请求延迟之和；
- `llm_enabled=false` 表示未配置 LLM（全部为模板，成功率/延迟无意义）。

终端还会输出数据接入、聚合、异常注入、异常检测、风险融合、LLM 解释、证据审计和
结果持久化各阶段耗时；相同数据也保存在 `summary.json.node_times` 与
`state.json.node_times`。

只想快速测一次单次延迟，不必跑全流程：

```bash
cd /data/home/6120260064/wrh/code && export PYTHONPATH=src
export SURVEILLANCE_LLM_MODE=local_http SURVEILLANCE_LLM_BASE_URL=http://127.0.0.1:8002/v1
python - <<'PY'
import json, time
from surveillance_agent.agent.llm import get_llm
llm = get_llm()
t0 = time.monotonic()
out = llm("用一句话介绍你自己，只输出JSON {\"text\":\"...\"}")
print("latency_ms =", round((time.monotonic()-t0)*1000, 1))
print("output:", out)
PY
```

数据导入（ingest）解析率在 `var/runs/<run_id>/quality.json` 的 `per_source` 中：`events / total_rows` 即各数据源的事件生成率。

## 6. 容错与注意事项

- **LLM 不可用时主流程照跑**：LLM 调用失败自动回退确定性模板解释；`SURVEILLANCE_LLM_MODE` 未设置时直接走模板，与之前行为一致。
- **JSON 解析容错**：客户端已增强，模型输出即使带 ``` 代码围栏或前后缀文字，也能提取出 JSON；提取失败才回退模板。
- **1.5B 模型能力有限**：解释生成是低风险场景（有证据审计把关），字段映射有必填校验兜底；若觉得输出不稳定，把 `SURVEILLANCE_LLM_TEMPERATURE` 降到 `0.1`。
- **端口占用**：`8002` 被占用时用 `--port` 换端口，并同步修改 `SURVEILLANCE_LLM_BASE_URL`。
- **多节点**：若监测流程与模型服务分在不同节点，把 `BASE_URL` 指向模型节点 IP 并确保端口开放；本指南假设同机，用 `127.0.0.1`。
- **备选服务**：若平台已装 vLLM，也可用它替代本服务（接口完全兼容）：
  ```bash
  vllm serve /data/home/6120260064/model --port 8002 --served-model-name Qwen2.5-1.5B-Instruct
  ```

## 7. 常见报错排查

### 7.1 `Unrecognized model ... Should have a model_type key in its config.json`

原因：transformers 在 `--model-dir` 指定的目录里找不到可识别的 `config.json`。通常是**下载目录结构与预期不符**（模型在嵌套子目录里）或**下载不完整**。

服务器已支持自动往下找一层子目录，先直接重试：
```bash
python scripts/llm_server.py --model-dir /data/home/6120260064/model --host 0.0.0.0 --port 8002
# 若看到 "已自动定位模型子目录: ..." 即修复
```

若仍报错，在平台上手动排查：
```bash
# 1) 看顶层目录里有什么
ls -la /data/home/6120260064/model

# 2) 找 config.json 到底在哪（最多下探两层）
find /data/home/6120260064/model -maxdepth 2 -name config.json

# 3) 确认 config.json 里有没有 model_type
python -c "import json;c=json.load(open('/data/home/6120260064/model/config.json'));print(c.get('model_type'))"
# Qwen2.5 应为 qwen2

# 4) 直接把 --model-dir 指到真正含 config.json 的那层目录
python scripts/llm_server.py --model-dir /data/home/6120260064/model/<实际子目录> \
    --host 0.0.0.0 --port 8002
```

若 `find` 找不到任何 `config.json` → 模型下载不完整，需重新下载（应含 `config.json`、`tokenizer.json`、`*.safetensors` 等文件）。

### 7.2 日志末尾出现 `ERR99999 UNKNOWN application exception`

这是昇腾 CANN 运行时在进程崩溃后打印的附带日志，**不是独立故障**；真正的错误在上面 Python 的 Traceback 里，先按上一条排查。

## 8. 本次代码改动清单

| 文件 | 改动 |
|---|---|
| `scripts/llm_server.py` | **新增**：transformers 加载本地模型的 OpenAI 兼容推理服务（CPU/CUDA/NPU） |
| `src/surveillance_agent/agent/llm.py` | 重写：LLM 设置支持 config+环境变量、超时/重试、新增 `extract_json` 容错提取 |
| `src/surveillance_agent/agent/explanation.py` | `llm_explain` 改用 `extract_json`，提示词改为仅 JSON 输出 |
| `src/surveillance_agent/agent/schema_mapping.py` | `propose_with_llm` 改用 `extract_json` |
| `requirements-llm.txt` | **新增**：transformers / safetensors / accelerate 可选依赖 |
| `tests/test_core.py` | 新增 `extract_json` 单元测试（23 项测试全过） |
