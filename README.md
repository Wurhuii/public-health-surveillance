# 省级公共卫生风险监测多 Agent 系统

## 1. 项目定位

本项目是一个可运行的省级公共卫生风险监测多 Agent 原型。Supervisor Agent 通过结构化消息组织数据治理、聚合、统计检测、风险评估、解释、证据审计和持久化 Agent，用三份模拟数据验证以下完整链路：

1. 接收养老院、医院和学校三类异构数据；
2. 将不同字段体系转换为统一的监测事件；
3. 在省内完成数据质量检查、症候群映射和时间序列聚合；
4. 调用 EWMA、CUSUM、Shewhart 三种统计检测器；
5. 融合模型结果，生成结构化风险信号；
6. 在本地页面展示风险、证据和解释；
7. 仅输出聚合后的风险结果，不输出个人级原始数据；
8. 为 RQ1、RQ2、RQ4 提供可重复的论文实验入口。

当前版本是验证流程和研究设计的原型，不是可以直接用于疾病诊断或公共卫生处置的生产系统。统计阈值尚未经过真实数据标定。

## 2. 已使用的模拟数据

默认配置读取项目上级目录的三份文件：

- `care_home_data_hubei_yichang-模拟.csv`：省份 A 养老院场景；
- `medical_data_hubei_yichang-模拟.csv`：省份 A 医院场景；
- `school_symptom_processed.xlsx`：省份 B 学校场景。

一次完整导入会生成：

- 养老院标准事件 1,000 条；
- 医院标准事件 1,644 条；
- 学校标准事件 2,099 条；
- 合计标准事件 4,743 条。

原始文件不会被修改。身份证号、门诊流水号、老人信息 ID、学校记录 ID 等不会原样进入统一事件；事件 ID 使用本地盐值进行不可逆哈希。模拟数据存在重复流水号、缺少省份字段和症状日期晚于上报日期等问题，系统会在 `quality.json` 中记录。

正式部署前必须设置：

```powershell
$env:SURVEILLANCE_HASH_SALT = "由本地安全管理员配置的随机密钥"
```

默认的 `demo-only-change-me` 仅用于本地演示。

## 3. 总体逻辑框架

```text
                    Supervisor Agent
                  ┌────策略路由与阶段控制────┐
                  │                         │
                  ▼                         │
             专业 Agent 节点 ──执行结果─────┘
                          │ 结构化任务消息
       ┌──────────┬───────┼────────┬───────────┐
       ▼          ▼       ▼        ▼           ▼
 数据治理 Agent  聚合 Agent  统计检测 Agent  风险评估 Agent  解释 Agent
       │          │       │        │           │
 原始数据→统一事件  时间序列  三检测器    RiskEvidence   模板/本地LLM
       │          │       │        │           │
       └──────────┴───────┴────────┴─────┬─────┘
                                        ▼
                                  证据审计 Agent
                              通过 │          │ 拒绝
                                   ▼          └──→ Supervisor按阶段决定
                              持久化 Agent         修订/人审/停止
                                   │
                         RiskSignal / API / SQLite
```

全国中心不属于当前项目的可控范围。代码只提供结构化风险结果查询接口；不实现原始数据上传。

每个 Agent 都有独立名称、职责和能力白名单，通过 `AgentMessage` 交换任务及结果。每次请求和响应都写入 `agent_messages.jsonl`，响应通过 `correlation_id` 关联原请求。多 Agent 指的是职责、状态和消息协议上的分离，并不要求每个 Agent 都使用 LLM。

## 4. 多 Agent 与 LLM 的关系

风险判定由确定性统计模型完成，LLM不直接决定是否告警。这样做有四个原因：

- 同样的输入和配置可以重复得到相同的统计结果；
- 检测阈值和模型版本可以审计；
- LLM不可用时，监测主流程仍能运行；
- 论文可以把固定流程作为 Agent 方法的可靠基线。

当前多 Agent 角色如下：

| Agent | 核心职责 | 是否使用LLM |
|---|---|---|
| Supervisor Agent | 根据状态、前置条件和自主性阶段选择下一个白名单动作 | 否 |
| 数据治理 Agent | 数据源识别、隐私处理、质量检查 | 可选字段映射 |
| 聚合 Agent | 构造场景化时间序列 | 否 |
| 统计检测 Agent | EWMA、CUSUM、Shewhart | 否 |
| 风险评估 Agent | 融合检测证据并形成风险等级 | 否 |
| 解释 Agent | 根据 `RiskEvidence` 生成解释草稿 | 可选 |
| 证据审计 Agent | 校验数值、字段和禁止性表述 | 否 |
| 持久化 Agent | 保存最终信号和运行摘要 | 否 |

LLM目前用于两个受约束能力：

- 对新字段体系提出映射建议，建议必须经过字段存在性、必填字段和唯一映射验证；
- 根据 `RiskEvidence` 生成解释，解释必须经过数值一致性和禁用表述检查。

## 5. 代码结构

```text
code/
├─ config/
│  └─ default.json                 默认场景、模型、路径和隐私配置
├─ scripts/
│  ├─ run_demo.ps1                 运行三份数据的完整模拟
│  ├─ run_server.ps1               启动本地页面
│  └─ run_tests.ps1                运行自动化测试
├─ src/surveillance_agent/
│  ├─ adapters/
│  │  ├─ base.py                   表格读取、字段规范化、适配器接口
│  │  ├─ care_home.py              养老院适配器
│  │  ├─ hospital.py               医院适配器
│  │  ├─ school.py                 学校适配器
│  │  ├─ syndromes.py              症候群映射字典
│  │  └─ registry.py               场景自动识别
│  ├─ models/
│  │  ├─ base.py                   统计检测器接口
│  │  ├─ detectors.py              EWMA、CUSUM、Shewhart
│  │  └─ fusion.py                 多模型结果融合
│  ├─ agent/
│  │  ├─ orchestrator.py           Supervisor执行、消息路由和安全边界
│  │  ├─ supervisor.py             四阶段自主策略、动作白名单和轮次上限
│  │  ├─ messages.py               Agent消息信封和结果协议
│  │  ├─ roles.py                  七类职责独立的协作Agent
│  │  ├─ langgraph_workflow.py     Supervisor回环StateGraph
│  │  ├─ schema_mapping.py         受约束字段映射 Agent
│  │  ├─ model_policy.py           RQ2可解释模型选择策略
│  │  ├─ llm.py                    本地 OpenAI 兼容 LLM 客户端
│  │  └─ explanation.py            模板/LLM解释和证据验证器
│  ├─ api/
│  │  ├─ app.py                    FastAPI正式接口
│  │  └─ fallback_server.py        无FastAPI时的标准库回退服务器
│  ├─ research/
│  │  ├─ injection.py              半合成异常注入
│  │  ├─ schema_drift.py           模式漂移生成与评估
│  │  └─ experiments.py            RQ1、RQ2、RQ4实验入口
│  ├─ static/index.html             本地风险展示页面
│  ├─ aggregation.py                时间序列聚合
│  ├─ config.py                     JSON配置加载
│  ├─ domain.py                     统一事件、证据和风险数据结构
│  ├─ storage.py                    SQLite持久化
│  ├─ utils.py                      哈希、JSON/JSONL工具
│  └─ cli.py                        命令行入口
├─ tests/
│  └─ test_core.py                  15项核心和Supervisor策略测试
├─ var/
│  ├─ runs/                         每次运行的审计产物
│  └─ surveillance.db               本地数据库，首次运行后生成
├─ pyproject.toml
├─ requirements.txt
└─ README.md
```

## 6. 八项协作任务

`MultiAgentCoordinator`把八项任务交给注册的职责 Agent。`PipelineRunner`保留为兼容旧调用方的类名；它现在继承多 Agent 协调器。

### 6.1 ingest

- 读取 CSV/XLSX；
- 自动识别场景；
- 解析字段并生成 `SurveillanceEvent`；
- 哈希事件和机构标识；
- 输出 `events.jsonl`、`quality.json`。

### 6.2 aggregate

- 将一个事件展开为一个或多个症候群事件；
- 养老院、医院默认按省份和周聚合；
- 学校默认按机构和天聚合；
- 自动补齐没有事件的时间点；
- 输出 `aggregates.csv`。

### 6.3 inject

- 正常运行时保持聚合数据不变；
- 实验模式可注入 spike、gradual、cluster、multimodal 四类异常；
- 保存注入位置、强度和真实标签；
- 输出 `aggregates_for_detection.csv`、`injection_manifest.json`。

### 6.4 detect

并行运行：

- EWMA：强调持续变化；
- CUSUM：强调小幅但连续的偏移；
- Shewhart：强调单点突增。

基线只使用当前时间点之前的历史窗口，避免把当前异常泄漏进预期值。输出 `detector_points.csv`。

### 6.5 fuse

按同一场景、范围、症候群和时间窗口融合检测器：

- 两个及以上检测器告警：`high`；
- 一个检测器告警：`medium`；
- 尚未告警但接近阈值：`watch`；
- 其他：`normal`。

每条风险信号同时保存观察值、预期值、每个模型的分数、阈值、数据质量限制和模型版本。输出 `risk_signals.json`。

### 6.6 explain

默认使用完全确定的模板解释。如果配置本地 LLM，则 LLM只能读取 `RiskEvidence`，并输出结构化证据声明。
解释 Agent 只生成 `explanation_drafts.json`，不能自行把文本写入最终风险结果。

### 6.7 audit

证据审计 Agent 独立读取解释草稿和 `RiskEvidence`，拒绝：

- 与证据不一致的数字；
- 不存在的证据字段；
- “已经暴发”“确诊为”等确定性结论；
- 没有任何证据声明的解释。

如果解释被拒绝，证据审计 Agent 把拒绝的信号 ID 写回图状态。顺序基线维持原有的确定性模板重做；Supervisor图则根据自主性阶段决定持久化空解释并标记人审，或在限定轮次内退回解释 Agent 重做并重新审计。输出 `explanations.json`，只有通过验证的文本才进入最终 `RiskSignal`。

### 6.8 persist

- 保存运行摘要和风险信号到 SQLite；
- 保存最终 `summary.json`；
- 保存完整 `state.json` 和各步骤时间；
- 支持本地页面查询。

## 7. Supervisor LangGraph模式

项目把 LangGraph 放在协调层，而不是数据和统计计算层。图不再把八项任务首尾固定连接，而采用：

```text
START → Supervisor → 专业Agent → Supervisor → … → END
```

Supervisor只能从 `ingest、aggregate、inject、detect、fuse、explain、audit、revise、persist` 白名单中选择动作，并在执行前验证所需产物。所有路由写入 `supervisor_decisions.jsonl`，包括基线路由、自主建议、实际执行动作、选择原因和当时生效的安全上限。

自主性按以下四阶段逐步开放：

| 阶段 | 名称 | 实际行为 | 建议用途 |
|---|---|---|---|
| 0 | baseline | Supervisor执行固定八步顺序 | 论文和工程基线 |
| 1 | shadow | 计算受限自主建议，但仍执行固定顺序 | 默认上线观察阶段 |
| 2 | bounded | 允许跳过空解释任务，并在上限内自动修订和重新审计 | 验证安全后启用 |
| 3 | adaptive | 阶段2能力加上白名单幂等步骤的有限重试 | 稳定运行后启用 |

无论处于哪个阶段，Supervisor都不能修改统计风险等级、绕过证据审计、访问白名单外工具或向全国中心发送原始数据。自动修订超过 `max_revision_rounds` 后会持久化空解释并设置 `requires_human_review`，而不是继续无限循环。

阶段和安全上限在 `config/default.json` 中配置：

```json
{
  "supervisor": {
    "default_autonomy_stage": 1,
    "max_revision_rounds": 1,
    "max_step_retries": 1,
    "max_iterations": 32,
    "retryable_steps": ["explain", "audit"]
  }
}
```

阶段3也只能重试这里列出的步骤；数据导入、风险判定和持久化默认不自动重试，避免非幂等副作用。

目标环境是 Python 3.9.20，因此固定使用：

```text
langgraph==0.3.34
```

当前最新版 LangGraph 已不支持 Python 3.9。长期建议把 Agent 控制层升级到 Python 3.11，把需要保留 Python 3.9 的模型工作进程通过本机 HTTP/RPC 隔离。

如果没有安装 LangGraph但命令传入了 `--langgraph`，系统会在审计日志中记录回退原因，并使用同构顺序执行，主流程不会中断。

## 8. 运行方法

### 8.1 当前目录直接运行

在 `code` 目录执行：

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
python -m surveillance_agent run --inject --shape gradual --magnitude 10
```

或：

```powershell
.\scripts\run_demo.ps1
```

不注入异常：

```powershell
python -m surveillance_agent run
```

启用 Supervisor LangGraph，默认使用配置中的阶段1：

```powershell
python -m surveillance_agent run --inject --langgraph
```

显式选择阶段：

```powershell
python -m surveillance_agent run --inject --langgraph --autonomy-stage 2
```

### 8.2 启动本地页面

```powershell
.\scripts\run_server.ps1
```

浏览器访问：

```text
http://127.0.0.1:8080
```

如果 FastAPI/Uvicorn 已安装，自动使用 FastAPI；否则使用已经内置并验证过的标准库回退服务器。

### 8.3 正式离线环境安装

在有网络的同版本 Python 3.9.20 环境提前下载 wheel：

```powershell
pip download -r requirements.txt -d wheelhouse
```

把整个项目和 `wheelhouse` 拷贝到省内环境后：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --no-index --find-links .\wheelhouse -r requirements.txt
pip install --no-index --find-links .\wheelhouse -e .
```

部署现场不需要访问互联网。

## 9. 本地 LLM 接入

代码假定昇腾 910B 上的模型服务提供 OpenAI 兼容的 `/v1/chat/completions` 接口。配置示例：

```powershell
$env:SURVEILLANCE_LLM_MODE = "local_http"
$env:SURVEILLANCE_LLM_BASE_URL = "http://127.0.0.1:8001/v1"
$env:SURVEILLANCE_LLM_MODEL = "local-model"
$env:SURVEILLANCE_LLM_API_KEY = ""
```

统计模型运行在 CPU 即可，不需要占用 910B。LLM服务和统计模型工作进程通过接口解耦，便于以后更换 MindIE、vLLM 兼容服务或其他本地推理方案。

当前代码没有附带模型权重，也没有假设具体的昇腾推理服务器已经部署。

## 10. API

主要接口：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 查询演示配置 |
| GET | `/api/agents` | 查询协调Agent、角色能力和任务路由 |
| POST | `/api/runs` | 启动一次处理 |
| GET | `/api/runs` | 查询运行记录 |
| GET | `/api/risks` | 查询结构化风险结果 |
| GET | `/docs` | FastAPI模式下查看接口文档 |

`POST /api/runs`示例：

```json
{
  "inject_outbreak": true,
  "injection_shape": "gradual",
  "injection_magnitude": 10,
  "use_langgraph": true,
  "autonomy_stage": 1
}
```

## 11. 论文实验

### 11.1 RQ1：模式漂移与异构字段适配

```powershell
python -m surveillance_agent experiment rq1 --output var\rq1_results.json
```

自动生成：

- 原始字段；
- 已知别名；
- 空格/下划线格式噪声；
- 可选字段缺失；
- 必要字段缺失。

比较：

- `static_primary`：只接受首选字段名；
- `constrained`：别名、规范化、受限模糊匹配和必要字段验证。

指标包括 precision、recall、F1、正确拒绝和静默错误。

当前三份模拟数据实际运行产生30条实验记录；受约束方法在当前扰动集上的平均 F1 为1.0，静默错误为0。这只是代码正确性验证，不能作为论文最终结果。论文阶段需要扩大扰动类型、随机种子和未见数据源。

### 11.2 RQ2：检测器选择与融合

```powershell
python -m surveillance_agent experiment rq2 --output var\rq2_results.json
```

组合四种异常形状、三种强度、三个场景，比较：

- EWMA；
- CUSUM；
- Shewhart；
- 固定融合；
- 受约束自适应策略。

输出检出率、检出延迟和注入前误报数。当前运行产生180条结果。现有阈值未经调优，CUSUM误报偏高、EWMA灵敏度偏低，恰好说明后续需要校准，不应把当前数字当成模型性能结论。

### 11.3 RQ4：解释忠实性

```powershell
python -m surveillance_agent experiment rq4 --output var\rq4_results.json
```

默认验证模板解释。连接本地 LLM 后自动增加：

- `ungrounded_llm`：无严格证据约束的对照组；
- `grounded_llm`：只读取结构化证据的实验组。

输出证据声明数量、验证通过率和错误类型。当前模板解释30条全部通过验证；LLM组需要910B本地模型服务上线后执行。

## 12. 自动化测试与已完成验证

执行：

```powershell
.\scripts\run_tests.ps1
```

目前包含15项测试：

1. 三类数据自动识别；
2. 4,743个事件全部生成且事件ID唯一；
3. 必要字段缺失时正确拒绝；
4. 三个检测器能够处理异常尾部；
5. 异常注入生成可审计清单；
6. 模板解释通过证据验证、伪造数字被拒绝；
7. Agent消息的请求—响应关联可审计；
8. 证据审计 Agent 拒绝伪造数字，并把任务退回解释 Agent 重做；
9. 三份数据完整端到端运行，并验证多Agent注册表、审计任务和消息日志；
10. 阶段1只记录自主修订建议、仍执行固定基线；
11. 阶段2执行有限修订，并强制重新进入独立审计；
12. 阶段3只重试配置白名单内的步骤；
13. 完成持久化后Supervisor能够终止图循环；
14. 无风险信号时跳过解释与审计，持久化一次后正确终止；
15. 阶段2 Supervisor回环在三份数据上完成端到端执行。

在当前环境的实际检查结果：

- `compileall`通过；
- 15项测试全部通过；
- 三份数据端到端流程通过；
- RQ1、RQ2、RQ4实验入口通过；
- 标准库本地页面、健康接口返回 HTTP 200。

FastAPI和LangGraph在当前机器上未安装，因此它们的代码完成了语法检查，但本次运行分别使用标准库服务器和顺序编排回退。正式部署前应在目标 Python 3.9.20 环境使用离线 wheel 再执行一次完整测试。

## 13. 每次运行的审计产物

`var/runs/<run_id>/`包含：

```text
state.json                       多Agent注册表、状态、消息和节点时间
agent_messages.jsonl             Agent之间的请求、响应和关联ID
supervisor_decisions.jsonl       每次路由建议、实际动作、原因和安全上限
events.jsonl                     去标识化统一事件
quality.json                     字段映射和数据质量报告
aggregates.csv                   原始聚合时间序列
aggregates_for_detection.csv     注入后或原样检测数据
injection_manifest.json          半合成异常真实标签
detector_points.csv              每个检测器的逐时间点输出
risk_signals.json                最终风险信号
explanation_drafts.json          解释Agent提交的待审计草稿
explanations.json                解释、证据声明和验证结果
summary.json                     本次运行摘要
```

这些文件使同一次实验可以检查、重放和定位失败节点。

## 14. 当前边界与后续工作

已经实现的是完整的软件和实验骨架；尚未完成的是需要业务方、真实环境或专家参与的部分：

- 真实风险类型、症候群定义和阈值标定；
- 当地政务数据库/API接入；
- 910B本地模型服务部署与压力测试；
- 公共卫生专家对解释的盲评；
- 更大规模模式漂移和异常注入实验；
- 真实历史数据上的误报率与检出时间评估；
- 正式认证、权限、日志脱敏和安全审查；
- 全国中心接口协议确认。

代码预留了Agent注册、消息协议、适配器、模型注册、LLM客户端和解释器接口，后续添加新省份、新场景、新Agent或新模型时，不需要重写主流程。
