# 省级公共卫生风险监测多 Agent 系统 —— 功能与操作说明

> 本文档描述 `code/` 当前代码的实际能力、每一项功能做什么、如何操作，以及对应的代码位置与产物。
> 适用于原型验证、论文实验复现与二次开发参考。与 `README.md`（项目定位/架构）配合阅读。

---

## 1. 功能总览

系统把"原始异构数据 → 结构化风险信号"拆成八项流水线任务，由 Supervisor 统一编排：

| # | 任务 | 干什么 | 输出产物 |
|---|---|---|---|
| 1 | `ingest` 数据治理 | 读取 CSV/XLSX、自动识别场景、字段解析、隐私哈希、质量检查 | `events.jsonl`, `quality.json` |
| 2 | `aggregate` 聚合 | 事件按场景/症候群聚合为时间序列，自动补零 | `aggregates.csv` |
| 3 | `inject` 异常注入 | 实验模式注入 spike/gradual/cluster/multimodal 异常并记录真实标签 | `aggregates_for_detection.csv`, `injection_manifest.json` |
| 4 | `detect` 统计检测 | EWMA / CUSUM / Shewhart 三检测器，仅用当前点之前的历史做基线 | `detector_points.csv` |
| 5 | `fuse` 风险评估 | 融合检测器结果生成 high/medium/watch/normal，可合并连续报警段 | `risk_signals.json` |
| 6 | `explain` 解释 | 确定性模板或本地 LLM 生成解释草稿（仅证据内的陈述） | `explanation_drafts.json` |
| 7 | `audit` 证据审计 | 校验数字一致性、字段存在性、禁用表述；拒绝则退回或标记人审 | `explanations.json` |
| 8 | `persist` 持久化 | 保存运行摘要、风险信号到 SQLite，写出审计产物 | `summary.json`, `state.json`, SQLite |

此外还提供：**Supervisor 四阶段自主性编排**（含 LangGraph 回环，已在智算平台实测通过）、**本地 Web 页面与 HTTP API**、**三个论文实验入口（RQ1/RQ2/RQ4）**、**25 项自动化测试**，以及**本地 LLM 推理服务**（`scripts/llm_server.py`，OpenAI 兼容接口，可在昇腾 NPU/GPU/CPU 上加载 Qwen2.5 等本地模型）。

当前已在智算平台完成 demo 试运行：`run --inject --langgraph --autonomy-stage 1` 全链路通过，LLM 侧使用 Qwen2.5-1.5B-Instruct 成功参与解释生成。平台部署与 LLM 接入步骤见 `DEPLOY_GUIDE.md`。

核心设计约束：风险判定由确定性统计模型完成，LLM 不直接决定是否告警；事件级原始数据不进入风险结果，个人标识经盐值哈希。

---

## 2. 快速上手

前置：Python 3.9+，可选安装 `fastapi`/`uvicorn`/`langgraph`（未安装时自动回退到标准库服务器 / 顺序编排）。依赖见 `requirements.txt`。

```powershell
# 1) 配置 PYTHONPATH 后直接运行（在 code 目录下）
$env:PYTHONPATH = (Resolve-Path ".\src").Path

# 2) 完整流程：三份数据 + 注入 gradual 异常，幅度 10 倍
python -m surveillance_agent run --inject --shape gradual --magnitude 10

# 3) 不注入异常（观察基线行为）
python -m surveillance_agent run

# 4) 启用 Supervisor LangGraph（默认阶段 1）
python -m surveillance_agent run --inject --langgraph

# 5) 显式指定自主性阶段
python -m surveillance_agent run --inject --langgraph --autonomy-stage 2

# 6) 启动本地页面/API（浏览器访问 http://127.0.0.1:8080）
python -m surveillance_agent serve

# 7) 运行论文实验
python -m surveillance_agent experiment rq1 --output var\rq1_results.json
python -m surveillance_agent experiment rq2 --output var\rq2_results.json
python -m surveillance_agent experiment rq4 --output var\rq4_results.json

# 8) 运行测试
python -m unittest discover -s .\tests -t .

# 9) 启动本地 LLM 推理服务（可选，OpenAI 兼容；需已安装 transformers/torch）
python scripts/llm_server.py --model-dir <模型目录> --host 0.0.0.0 --port 8002
```

也可以直接用仓库脚本（自动探测 conda 环境的 `surveillance` 解释器）：

```powershell
.\scripts\run_demo.ps1    # 完整演示（注入 gradual 10）
.\scripts\run_server.ps1  # 启动本地页面
.\scripts\run_tests.ps1   # 运行 25 项测试
```

> 数据文件位于项目上级目录（`data_dir=".."`），当前启用医院与养老院两份 CSV；学校 xlsx 需放入上级目录并在 `config/default.json` 中把 `sources.school.enabled` 改为 `true`。
>
> 智算平台/Linux 部署、LLM（Qwen2.5-1.5B-Instruct）接入与常见报错排查见 `DEPLOY_GUIDE.md`。

---

## 3. 八项流水线功能详解

### 3.1 ingest —— 数据治理

**功能**：读取三份异构数据（养老院 CSV、医院 CSV、学校 XLSX），自动识别场景与字段，生成统一事件 `SurveillanceEvent`，并对事件 ID、机构 ID 做盐值哈希（防个人标识反查）。

**操作**：`run`/`serve` 流程的第一步自动执行；测试中可单独调用：

```python
from surveillance_agent.config import load_config
from surveillance_agent.agent import MultiAgentCoordinator
coord = MultiAgentCoordinator(cfg=load_config(), autonomy_stage=0)
coord._task_ingest()
```

**实现要点**：
- 适配器：`adapters/care_home.py`（CareHome/Hospital/School 三个 Adapter），按表头特征自动识别（`adapters/registry.py`）。
- 场景识别与字段归一化：`adapters/base.py` 的 `read_rows` / `Adapter`。
- 质量检查：缺省/省缺失、发病日期晚于就诊日期等记录进 `quality.json`。
- 隐私：`utils.hash_id(text, salt)`，盐值来自 `SURVEILLANCE_HASH_SALT` 环境变量，缺省用 `demo-only-change-me`（仅限本地演示，部署必须设置）。

**产物**：`events.jsonl`（去标识统一事件）、`quality.json`（逐源质量报告）。

### 3.2 aggregate —— 时间序列聚合

**功能**：把每个事件按"来源 + 范围 + 症候群 + 时间粒度"计数成时间序列。

**操作**：自动执行；也可单独 `coord._task_aggregate()`。

**实现要点**（`aggregation.py`）：
- 范围与粒度来自 `config` 的 `scenarios`：养老院/医院按**省份 + 周**，学校按**机构 + 天**。
- 症候群映射采用**互斥优先级**（`adapters/syndromes.py`）：`respiratory > digestive > fever > neuro > cardio`，同一病例只进入一条序列，避免重复计数。
- 匹配不上任何已知症候群的"杂项"事件默认**不生成 `other` 序列**（`aggregation.include_other=false`），消除稀疏噪声序列导致的假报警。
- 自动补齐无事件的时间点（补 0）。

**产物**：`aggregates.csv`（source, scope_type, scope_key, syndrome, date, count）。

### 3.3 inject —— 半合成异常注入

**功能**：把聚合序列注入已知异常，用于评估检测器。正常运行保持数据不变。

**操作**：`--inject` 参数开启；形状与幅度通过 `--shape`/`--magnitude` 指定；也可用 `research/injection.py::inject_anomalies`。

**支持四种形状**（`orchestrator._injection_positions` 与 `research/injection.py`）：
- `spike`：单个时间点突增；
- `cluster`：连续两个点突增；
- `gradual`：连续三个点持续偏高；
- `multimodal`：两个分离的抬高区间。

注入位置取各序列中段，幅度 = `count × (1+magnitude)`。每个注入点记录 `original/injected/shape/magnitude/true_label`。

**产物**：`aggregates_for_detection.csv`、`injection_manifest.json`（真实标签）。

### 3.4 detect —— 三检测器统计检测

**功能**：对每条序列逐时间点计算三个检测器的得分/预期值/阈值/是否报警。

**操作**：自动执行；单独调用 `coord._task_detect()`。

**实现要点**（`models/detectors.py`）：
- **EWMA**（`λ=0.3, threshold=3.0`）：平滑历史后对当前点做标准化，捕捉小幅持续偏移；
- **CUSUM**（`k=0.5, h=4.0`）：累计正向偏离，**超限即重置**（`s>h → s=0`），避免残留记忆导致持久误报；
- **Shewhart**（`threshold=3.0`）：当前点 vs 历史均值/标准差，捕捉单点突增；
- **不泄漏**：基线只用 `history=values[:i]`（当前点之前），当前异常不进入预期值；
- 预热：历史点数不足 `min_history`（默认 4）不检测。

**自适应子集选择**（可选）：`coordinator.model_selector` 可注入 `model_policy.select_models`，按序列长度与变异系数决定用哪些检测器（短序列只用 Shewhart，高噪声排除 CUSUM）。

**产物**：`detector_points.csv`。

### 3.5 fuse —— 融合与风险分级

**功能**：把同一来源/范围/症候群/时间点的检测器结果融合成风险等级。

**操作**：自动执行；单独调用 `coord._task_fuse()`。

**实现要点**（`models/fusion.py` + `orchestrator.py`）：
- 融合规则（`fuse_alarms`）：
  - ≥2 个检测器报警 → `high`；
  - 1 个报警 → `medium`；
  - 无报警但得分/阈值 ≥ `watch_ratio`(0.7) → `watch`；
  - 否则 → `normal`。
- **报警段合并**（`detection.merge_alarm_runs=true`，默认开）：同一序列连续非 normal 的时间窗合并为**一个**风险信号，代表一次"异常事件段"，信号上记录 `evidence.run_dates` 与峰值点。
- 每条信号保存观察值、预期值、每个模型的分数/阈值/报警标志、模型版本、质量限制。

**产物**：`risk_signals.json`。

### 3.6 explain —— 解释生成

**功能**：为每个风险信号生成解释草稿，只陈述 `RiskEvidence` 内的证据。

**操作**：自动执行；默认走确定性模板 `template_explain`。配置本地 LLM 后走 `llm_explain`。

**实现要点**（`agent/explanation.py` + `agent/llm.py`）：
- 模板解释：`"{范围} 的 {症候群} 在 {日期} 监测值 X，预期值 Y，检测器得分…，综合等级…"`，并输出结构化 `claims`（observed/expected/syndrome/date）。
- LLM 模式：`SURVEILLANCE_LLM_MODE=local_http` 时启用，客户端向 OpenAI 兼容服务（`scripts/llm_server.py` 或 vLLM）发请求；
  - 提示词要求"只输出一个 JSON 对象"，客户端用 `extract_json` 容错提取（容忍 ``` 代码围栏与前后缀文字）；
  - 支持超时（`SURVEILLANCE_LLM_TIMEOUT`，默认 120s）与重试（`SURVEILLANCE_LLM_RETRIES`，默认 2 次）；
  - 解析失败或调用异常一律回退确定性模板，主流程不中断；
  - 输出必须通过后续证据审计（`validate_draft`），LLM 不能自行把文本写进最终风险结果；
  - **解析成功率与延迟统计**：每条草稿带 `draft_source`（`llm`/`template`）与 `latency_ms`（该次调用耗时）。运行结束后在 `summary.json.explanation` 与 CLI 输出中给出 `llm_generated`、`template_fallback`、`llm_parse_success_rate`，以及 `latency`（avg/min/max/p95，毫秒），用于衡量 LLM 输出 JSON 的解析成功率与单次推理延迟。

**产物**：`explanation_drafts.json`。

### 3.7 audit —— 证据审计

**功能**：独立校验解释草稿与 `RiskEvidence` 的一致性，防止 LLM 胡编。

**操作**：自动执行；单独调用 `coord._task_audit()`。

**拒绝条件**（`validate_draft`）：
- 与证据不一致的数字（`number_mismatch`）；
- 不存在的证据字段（`nonexistent_field`）；
- 出现禁用表述："已经暴发/确诊为/证实暴发…"（`forbidden`）；
- 没有任何证据声明（`no_evidence_claims`）。

**处理策略**：
- 草稿被拒时，先用确定性模板回退；回退也失败则标记 `requires_human_review` 并清空解释；
- 阶段 2+ 且 `max_revision_rounds` 内：退回解释 Agent 重做并**重新审计**（`_task_revise` 同步更新草稿产物）。

**产物**：`explanations.json`（含 `passed/errors/used_fallback`），仅通过的文本进入最终 `RiskSignal`。

### 3.8 persist —— 持久化

**功能**：把运行摘要与风险信号写入 SQLite，并把全部中间产物落盘到运行目录。

**操作**：自动执行；单独调用 `coord._task_persist()`。

**实现要点**（`storage.py`）：
- 库表 `runs`（运行摘要）与 `risk_signals`（每条信号含 evidence JSON）；
- 输出 `summary.json`（事件/聚合/检测/信号统计、风险等级分布、阶段、是否 LangGraph）、`state.json`（角色注册表、质量、注入清单）。

---

## 4. Supervisor 自主性编排（四阶段）

Supervisor 从白名单动作中选步执行，并在执行前校验前置产物。自主性按阶段逐步开放：

| 阶段 | 名称 | 实际行为 |
|---|---|---|
| 0 | baseline | 固定八步顺序，无任何自主动作 |
| 1 | shadow（默认） | 记录自主建议，仍执行固定顺序 |
| 2 | bounded | 无风险信号时跳过 explain/audit；审计被拒时在 `max_revision_rounds` 内自动修订并重审 |
| 3 | adaptive | 阶段 2 + 对 `retryable_steps`（explain/audit）白名单内的步骤在异常时按 `max_step_retries` 有限重试 |

无论哪一阶段，Supervisor 都不能修改统计风险等级、绕过证据审计、越权访问或发送原始数据。

**两种执行器（行为一致）**：
- 顺序编排：`MultiAgentCoordinator.run()`；
- LangGraph 回环：`run_with_langgraph()`（`langgraph_workflow.py`），图状态携带 `idx` 与 `revision_rounds`，每个动作节点调用与顺序编排**同一个** `_supervise_action()`，保证两路径行为一致。

关键配置（`config/default.json` 的 `supervisor` 段）：`default_autonomy_stage=1`、`max_revision_rounds=1`、`max_step_retries=1`、`max_iterations=32`、`retryable_steps=["explain","audit"]`。

> 未安装 LangGraph 且传入 `--langgraph` 时，系统记录回退原因并走顺序编排，主流程不中断。
>
> **验证状态**：已在本机 23 项测试（顺序编排路径）与智算平台 demo（`run --inject --langgraph --autonomy-stage 1`，LangGraph 0.3.34 / Python 3.9）上实际跑通，两条执行器路径行为一致。

---

## 5. 命令行操作参考

```text
python -m surveillance_agent {run | serve | experiment} [选项]
python scripts/llm_server.py [选项]     # 本地 LLM 推理服务
```

### run
| 参数 | 说明 | 默认 |
|---|---|---|
| `--inject` | 注入半合成异常 | 关 |
| `--shape` | `spike`/`gradual`/`cluster`/`multimodal` | `gradual` |
| `--magnitude` | 注入幅度（倍数） | `10.0` |
| `--langgraph` | 使用 Supervisor LangGraph 回环 | 关 |
| `--autonomy-stage` | `0`~`3`，覆盖配置默认阶段 | 配置值 |
| `--config` | 指定配置 JSON 路径 | `config/default.json` |

### serve
| 参数 | 说明 | 默认 |
|---|---|---|
| `--host` | 监听地址 | `127.0.0.1` |
| `--port` | 监听端口 | `8080` |

### llm_server（本地 LLM 推理服务）
| 参数 | 说明 | 默认 |
|---|---|---|
| `--model-dir` | 本地模型目录（缺省自动定位一层子目录） | `Qwen2.5-1.5B-Instruct` 默认路径 |
| `--host` / `--port` | 监听地址/端口 | `0.0.0.0` / `8002` |
| `--device` | `cpu`/`cuda`/`npu`/`auto` | `auto` |
| `--max-new-tokens` | 单次生成上限 | `256` |
| `--temperature` | 采样温度 | `0.2` |

### experiment
`python -m surveillance_agent experiment {rq1|rq2|rq4} [--output 路径]`，详见第 7 节。

---

## 6. HTTP API 与本地页面

启动 `serve` 后浏览器访问 `http://127.0.0.1:8080`。页面支持：查看风险信号表、点击"证据"展开检测器分数/阈值/模型版本/质量限制、一键触发运行（注入或不注入）。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/` | 风险展示页面 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 查询演示配置 |
| GET | `/api/agents` | 查询 Agent 角色与能力 |
| POST | `/api/runs` | 启动一次处理 |
| GET | `/api/runs` | 查询运行记录 |
| GET | `/api/risks` | 查询结构化风险结果 |
| GET | `/docs` `/openapi.json` | 接口文档（FastAPI 模式；回退服务器提供精简版） |

`POST /api/runs` 请求体示例：

```json
{
  "inject_outbreak": true,
  "injection_shape": "gradual",
  "injection_magnitude": 10,
  "use_langgraph": true,
  "autonomy_stage": 1
}
```

实现位置：`api/app.py`（FastAPI）+ `api/fallback_server.py`（标准库回退，已修复路径穿越：静态文件解析后会校验真实路径必须位于 static 根目录内）。

---

## 7. 论文实验入口

### RQ1 —— 模式漂移与异构字段适配
`experiment rq1`。生成原始字段/别名/空格/下划线/字段缺失等扰动，比较 `static_primary`（只认首选字段）与 `constrained`（别名+规范化+必填校验）的 precision/recall/F1/正确拒绝/静默错误。输出 `results`（每源每方法）与 `summary`。

### RQ2 —— 检测器选择与融合
`experiment rq2`。交叉 4 形状 × 3 强度 × 2 策略（`fixed_fusion`/`adaptive`）× 2 阈值集（`default`/`calibrated`），按"注入序列级"评估检出率与误报数。
- 自适应策略：`model_policy.select_models`（按序列长度/CV 选子集）；
- 阈值校准：`research/experiments.py::calibrate_detection_cfg` 在无注入基线上估计经验控制限（校准集与测试集分离）。
- 报警段合并后，命中判定基于 `evidence.run_dates` 与注入日期是否重叠。

### RQ4 —— 解释忠实性
`experiment rq4`。验证模板解释通过率、伪造数字被拒率；`grounded_llm`/`ungrounded_llm` 在接入 LLM 后状态由 `skipped_no_llm` 变为 `ready`（注：RQ4 目前仅做模板与伪造验证，真实的 LLM 解释调用发生在正常 `run` 的 explain 阶段，已在智算平台用 Qwen2.5-1.5B-Instruct 验证通过）。

> 当前数字是代码正确性验证，不是模型性能结论；论文阶段需扩大扰动集、随机种子与未见数据源。

---

## 8. 配置项说明（`config/default.json`）

| 字段 | 说明 | 当前值 |
|---|---|---|
| `data_dir` | 数据文件所在目录（相对 code/） | `..` |
| `sources.*` | 各数据源文件与启用开关 | 医院/养老院启用，学校停用 |
| `scenarios.*` | 各场景聚合范围与粒度 | 医院/养老院=province+week，学校=org+day |
| `aggregation.include_other` | 是否生成 `other` 症候群序列 | `false` |
| `supervisor.default_autonomy_stage` | 默认自主性阶段 | `1` |
| `supervisor.max_revision_rounds` | 审计被拒后的最大修订轮数 | `1` |
| `supervisor.max_step_retries` | 阶段 3 白名单步骤重试上限 | `1` |
| `supervisor.max_iterations` | LangGraph 最大迭代上限 | `32` |
| `supervisor.retryable_steps` | 阶段 3 允许重试的步骤 | `["explain","audit"]` |
| `detection.ewma` | EWMA 平滑系数与阈值 | `lambda=0.3, threshold=3.0` |
| `detection.cusum` | CUSUM k/h | `k=0.5, h=4.0` |
| `detection.shewhart` | Shewhart 阈值 | `3.0` |
| `detection.watch_ratio` | watch 判定比例 | `0.7` |
| `detection.min_history` | 检测预热点数 | `4` |
| `detection.merge_alarm_runs` | 是否合并连续报警段为单个信号 | `true` |
| `privacy.hash_salt_env` | 盐值环境变量名 | `SURVEILLANCE_HASH_SALT` |
| `privacy.default_salt` | 缺省盐（仅演示） | `demo-only-change-me` |
| `llm.*` | 本地 LLM 配置（mode/base_url/model/api_key） | mode=`off` |
| `model_version` | 模型版本号（写入每条证据） | `1.0.0` |

LLM 接入环境变量（优先级高于 `config.llm.*`；`MODE` 未设置/为 `off` 时默认走模板）：

| 环境变量 | 说明 | 默认 |
|---|---|---|
| `SURVEILLANCE_LLM_MODE` | `off` / `local_http` | `off` |
| `SURVEILLANCE_LLM_BASE_URL` | 模型服务地址（客户端连它，不含模型路径） | `http://127.0.0.1:8002/v1` |
| `SURVEILLANCE_LLM_MODEL` | 发给服务端的模型名字符串 | `local-model` |
| `SURVEILLANCE_LLM_API_KEY` | 鉴权密钥（无鉴权留空） | 空 |
| `SURVEILLANCE_LLM_TEMPERATURE` | 采样温度（越低越稳定） | `0.2` |
| `SURVEILLANCE_LLM_TIMEOUT` | 单次请求超时（秒） | `120` |
| `SURVEILLANCE_LLM_RETRIES` | 失败重试次数 | `2` |

示例（PowerShell / bash）：
```powershell
$env:SURVEILLANCE_LLM_MODE = "local_http"
$env:SURVEILLANCE_LLM_BASE_URL = "http://127.0.0.1:8002/v1"
$env:SURVEILLANCE_LLM_MODEL = "Qwen2.5-1.5B-Instruct"
$env:SURVEILLANCE_LLM_API_KEY = ""
```

---

## 9. 每次运行的审计产物

`var/runs/<run_id>/` 下：

| 文件 | 内容 |
|---|---|
| `state.json` | 多 Agent 注册表、状态、注入清单、质量 |
| `agent_messages.jsonl` | Agent 间请求/响应与关联 ID |
| `supervisor_decisions.jsonl` | 每次路由建议、实际动作、原因与安全上限 |
| `events.jsonl` | 去标识统一事件 |
| `quality.json` | 字段映射与数据质量报告 |
| `aggregates.csv` | 原始聚合时间序列 |
| `aggregates_for_detection.csv` | 注入后（或原样）检测数据 |
| `injection_manifest.json` | 半合成异常真实标签 |
| `detector_points.csv` | 各检测器逐时间点输出 |
| `risk_signals.json` | 最终风险信号（含证据与 run_dates） |
| `explanation_drafts.json` | 解释草稿 |
| `explanations.json` | 解释、证据声明与验证结果（含 passed/errors/used_fallback/draft_source） |
| `summary.json` | 本次运行摘要（含 `explanation` 解析成功率统计） |

同一次实验可检查、重放、定位失败节点。

---

## 10. 自动化测试（25 项）

运行：`python -m unittest discover -s .\tests -t .` 或 `.\scripts\run_tests.ps1`。

- **TestAdapters（7）**：医院/养老院场景识别；症候群互斥映射；2,644 事件生成且 ID 唯一；必填字段缺失拒绝；`other` 序列排除。
- **TestModels（3）**：三检测器对异常报警；融合分级；注入清单可审计。
- **TestExplanation（5）**：模板解释通过验证；伪造数字被拒；审计拒绝后可重做；解释草稿来源标记；LLM 单次调用延迟记录。
- **TestEndToEnd（4）**：完整流水线；消息关联可审计；阶段 1 只执行基线；阶段 2 端到端。
- **TestImprovements（6）**：CUSUM 报警后重置；报警段合并；审计回退写回；自适应模型选择；静态路径穿越被拒；LLM 输出 JSON 容错提取。

---

## 11. 隐私与安全

- 事件 ID / 机构 ID 使用盐值哈希，**正式部署必须设置** `SURVEILLANCE_HASH_SALT` 为安全随机值。
- 个人标识（身份证号、门诊流水号、老人信息 ID、记录 ID）不原样进入统一事件；但 `fields.org_name` 等机构名称与诊断/症状全文仍会进入 `events.jsonl`（为症候群映射所需），需在部署时明确权限边界。
- 静态文件服务已做路径穿越防护；API 与本地 LLM 服务（8002 端口）当前无鉴权/限流，**仅限本机或受信内网**运行。智算平台部署时若需对外暴露，应在平台侧加端口映射/鉴权控制。
- LLM 请求通过 HTTP 明文发送到本地服务（`127.0.0.1:8002`），同机内网使用；跨节点需自行保证网络隔离。

---

## 12. 近期修复与增强记录

- **本地 LLM 推理服务**（`scripts/llm_server.py` **新增**）：transformers 加载本地模型，暴露 OpenAI 兼容 `/v1/chat/completions`；自动识别 CPU/CUDA/昇腾 NPU 并按平台用 bf16；兼容模型目录嵌套（自动定位含 `config.json` 的子目录）。
- **LLM 客户端加固**（`agent/llm.py`）：LLM 设置支持 config+环境变量、超时/重试参数化、新增 `extract_json` 容错提取模型输出；`llm_explain`/`propose_with_llm` 均改为容错解析，失败回退模板/规则映射。
- **部署指南**（`DEPLOY_GUIDE.md` **新增**）：智算平台部署、Qwen2.5-1.5B-Instruct 接入、code-server 打开页面、常见报错（`Unrecognized model` 等）排查。
- **可选 LLM 依赖**（`requirements-llm.txt` **新增**）：transformers / safetensors / accelerate，不污染核心安装。
- **核心依赖锁版**（`requirements.txt`）：按 `surveillance` conda 环境（Python 3.9.23）逐版本锁定 43 个包，离线 wheelhouse 可复现。
- **CUSUM 报警后重置**（`models/detectors.py`）：消除残留记忆导致的持久误报。
- **报警段合并**（`detection.merge_alarm_runs`）：连续报警时间窗合并为单个风险信号，`RiskEvidence` 新增 `run_dates`。
- **症候群互斥映射 + 剔除 `other` 序列**（`adapters/syndromes.py`、`aggregation.py`）：杜绝重复计数与 `other` 稀疏噪声信号。
- **自适应模型选择 + 阈值校准**（`agent/model_policy.py`、`research/experiments.py`）：RQ2 增加 `adaptive` 策略与 `calibrated` 阈值集对比。
- **审计健壮性**（`agent/orchestrator.py`）：按 `signal_id` 关联草稿、fallback 后清空 errors 并标记 `used_fallback`、revise 同步更新草稿产物。
- **执行路径统一**（`agent/langgraph_workflow.py`）：LangGraph 与顺序编排共用 `_supervise_action`，行为一致（已在智算平台实测）。
- **路径穿越修复**（`api/fallback_server.py`）：静态文件真实路径校验。

> 注意：以上改动后 `README.md` 中的部分描述（如事件总数 4,743、检测器行为、风险信号粒度）与当前实现存在出入，文档同步工作见项目后续任务清单。

---

## 13. 当前已知问题（待办清单）

> 按影响优先级排列。已修复项见第 12 节；本节是**尚未解决**的部分。

### A. 文档与实现不一致（论文评审风险最高，建议最先处理）

- **`README.md` 与实际行为脱节**：
  - §2/§12 声称"完整导入 4,743 条事件"，但学校文件缺失且 `sources.school.enabled=false`，实际为 2,644 条；
  - §12 的 15 项测试描述与实际 23 项测试不符（无 LangGraph、无阶段 3、无"无风险跳过"等用例）；
  - §11.2 的 RQ2 数字与本次改动后的 4 组对比（2 策略 × 2 阈值集）未同步；
  - §6.2 "展开为一个或多个症候群" 与实际"互斥单映射"不符；
  - §6.5 风险信号按"时间窗口"粒度的描述与 `merge_alarm_runs` 合并段语义不符。
- **死代码**：`agent/supervisor.py` 的 `ACTION_WHITELIST / PREQUISITES / missing_preconditions` 定义了但从未被编排器或 LangGraph 引用；`agent/messages.py` 的 `AgentMessage` 协议字段与审计追溯能力未完全发挥。
- **阶段计时已补齐**：`state.json` 和 `summary.json` 的 `node_times` 记录各阶段调用次数、累计耗时和最近一次耗时，CLI 同步展示。

### B. 统计方法问题（影响实验结果可信度）

- **EWMA 不是标准 EWMA 控制图**（`models/detectors.py`）：把 EWMA 平滑值当基线、用普通 `pstdev` 做 z-score，未使用教科书控制限 `σ·√(λ/(2−λ)·(1−(1−λ)^2t))`。README 中"EWMA 灵敏度偏低"是此实现导致，不是方法本身。
- **计数数据正态性假设不成立**：三检测器均为 `(x−mean)/σ`，对稀疏/小均值序列（学校日级、罕见症候群）会系统性误报。建议稀疏序列引入 Poisson/负二项基线（Farrington/Noufaily 类算法），见 L3 方案。
- **`expected` 语义混用**（`orchestrator.py`）：`_build_signal` 取第一个检测器（EWMA 平滑值）作为证据的"预期值"，而 CUSUM/Shewhart 的 `expected` 是均值，口径不一致。
- **零填充聚合**（`aggregation.py`）：无事件时间点补 0 造成零膨胀，扭曲均值与方差；学校日级数据周末全 0。
- **`gradual` 注入并非渐进**：连续 3 个点乘同一幅度，不是爬升；注入位置固定在中段、无随机种子，无法支撑"检出延迟"的统计推断。
- **阈值校准仍粗糙**：`calibrate_detection_cfg` 用 `max×(1+margin)`（保证基线零误报的极端做法），且校准集与测试集同源，存在数据窥探风险；建议改用分位数 + 留一序列交叉验证。
- **自适应策略区分度不足**：`select_models`（按长度/CV）在当前数据上与固定融合结果几乎相同，说明启发式尚未体现优势；应结合按序列校准阈值与加权融合（`score/threshold` 裕度）落地。
- **季节/周内效应未建模**：周粒度序列未用历史同期基线，日粒度序列未处理周末效应；`min_history=4` 偏短。
- **症候群优先级为手工启发式**：`SYNDROME_PRIORITY` 把发热置于神经/心血管之上，但 `neuro/cardio` 关键词混合急症（脑炎、心梗）与慢病（高血压、阿尔茨海默），边界情况依赖主观排序。

### C. 工程与打包问题

- **`pyproject.toml` 打包不完整**：`packages` 缺少 `surveillance_agent.research`，且 `static/` 与 `config/` 未声明为包数据 → 按 README §8.3 离线 `pip install -e .` 后，`experiment rq*` 会失败、`serve` 页面 404（平台 demo 用 `PYTHONPATH=src` 直接跑，暂未受影响）。
- **`run_id` 秒级粒度**（`orchestrator.py`）：同一秒内并发运行会撞 ID，SQLite `INSERT OR REPLACE` 互相覆盖；API `POST /api/runs` 无并发保护。
- **API 无鉴权/限流/输入校验**：`shape`、`magnitude`、`autonomy_stage` 接受任意值，`POST /api/runs` 同步阻塞线程。
- **LLM 支持并发与批量推理**：vLLM/MindIE 通过并发请求进行连续批处理；项目自带的 Transformers 服务提供 `/v1/chat/completions/batch`，默认每批 4 条，减少逐条生成带来的线性等待。
- **LLM 输出依赖模型能力**：提示词要求"只输出 JSON"，`extract_json` 已容错，但 1.5B 模型偶发输出不合规仍会回退模板；RQ4 的 `grounded_llm`/`ungrounded_llm` 目前仍只是状态占位，未真正执行 LLM 对照实验。
- **LLM 运行依赖平台环境**：`llm_server.py` 需要平台已装 transformers/torch/torch_npu；本机（Windows 开发环境）未装则无法本地跑通模型服务。
- **无日志框架**：全用 `print`/`write_json`，缺少统一结构化日志。
- **测试覆盖缺口**：FastAPI 路径、LangGraph 路径仍无自动化测试（平台为手工验证）；LLM 仅有 `extract_json` 单测与 mock 集成自检，无真实模型端到端自动化测试；`agent_messages.jsonl` 的 payload 只含 summary，无输入快照，追溯性偏弱。
- **阶段 3 重试不完整**：`_supervise_action` 中 `_run_with_retry` 只包裹主动作，审计被拒后的 `revise`/`re-audit` 子流程未纳入重试保护。
- **`read_rows` xlsx 边界**（`adapters/base.py`）：行比表头短时 `IndexError`；表头含 `None`/重复项未处理。
- **`_injection_positions` 重复实现**：`orchestrator.py` 与 `research/injection.py` 各一份，应合并。
- **`config.py` 全局缓存**：模块级 `_loaded` 可变，多实例/测试场景存在状态泄漏风险（已有 `reset_config` 兜底）。

### D. 数据与隐私边界

- **`events.jsonl` 保留机构名称明文**：`fields.org_name`（养老院/学校）未哈希，与 README"机构标识哈希"的声明不完全一致。
- **诊断/症状全文保留**：`diagnosis`/`symptoms` 为症候群映射所必需，属个人健康信息，README 未明确该边界与权限要求。
- **`include_other=false` 的漏报风险**：未匹配任何已知症候群的事件被静默排除在检测之外，可能漏掉关键词表未覆盖的新发异常；当前依赖手工维护的 `SYNDROME_KEYWORDS`，覆盖不全。
- **学校数据缺失**：`school_symptom_processed.xlsx` 不在上级目录且默认停用，三场景验证链路实际上只跑了两个场景。
