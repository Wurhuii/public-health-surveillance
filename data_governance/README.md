# 重点场所数据治理包

本目录把协和提供的、当前相对成熟的数据治理代码与主监测系统放在同一仓库中。代码可随 GitHub 部署；原始工作簿与代码分开保存，避免人员和机构明细进入公开仓库。

## 目录约定

```text
data_governance/
├─ school/                    学校 00—16 原始治理与预警模型代码
├─ care_home/legacy/          养老机构 1—17 原始研究脚本（保留追溯）
├─ published_samples/        从代码包示例生成的去标识标准输入
└─ output/                    运行后生成的标准输入和审计产物
```

统一入口会优先读取私有原始工作簿；若未配置或文件不齐，则把仓库内置的去标识验证数据发布到 `output/`：

```bash
python scripts/run_data_governance.py
```

服务器使用私有工作簿重新治理：

```bash
GOVERNANCE_INPUT_ROOT=/data/home/6120260064/wrh/surveillance_data/governance_inputs \
python scripts/run_data_governance.py --require-raw
```

快速验证（学校包只运行至模块 05）：

```bash
python scripts/run_data_governance.py --fast
```

生成供主系统读取的两个文件：

- `data_governance/output/school_governed.csv`
- `data_governance/output/care_home_governed.csv`

完整治理记录写入 `data_governance/output/governance_manifest.json`。`config/governed_samples.json` 读取这两个输出，医院、农贸市场和旧宜昌数据源默认关闭。

## 养老机构样例的边界

养老机构原始 1—17 脚本仍保存在 `care_home/legacy/`，用于追溯事件定义和处理口径。交付脚本含开发者本机绝对路径，样例中的诊疗日期被掩码，老人底册与诊疗表也没有可直接连接的一致人员键，因此不能原样用于服务器自动运行。

可移植入口仅为演示数据补充两个字段：

1. 用确定性哈希模拟跨来源人员关联；
2. 在 2026-10-03 至 2026-10-09 内生成可排序的演示事件日期。

生成结果明确保留 `模拟人员关联=是` 和 `模拟事件日期=是`，不能作为真实业务数据或模型验证结果。正式接入时必须把示例文件替换为同结构真实数据，并提供跨来源一致的不可逆人员键、有效事件日期、稳定机构编码和在住起止日期。

## 服务器放置路径

若服务器项目根目录为 `/data/home/6120260064/wrh/code`，数据和代码包统一放置为：

```text
/data/home/6120260064/wrh/code/data_governance/
```

代码包原始示例或真实私有数据统一放在仓库外：

```text
/data/home/6120260064/wrh/surveillance_data/governance_inputs/
├─ school/
│  ├─ school_data.xlsx
│  └─ class_population_base.xlsx
└─ care_home/
   └─ *.xlsx
```

原始工作簿不要提交到 GitHub。设置 `GOVERNANCE_INPUT_ROOT` 后，一键启动脚本会自动使用该目录；没有该目录时仍可直接用公开的去标识验证数据演示。
