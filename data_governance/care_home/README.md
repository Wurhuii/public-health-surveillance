# 养老机构治理代码说明

`legacy/` 保存协和提供的 1—17 步研究脚本，包括白名单、每日在院人数、诊疗清洗、入住期间过滤、流感相关诊断/ILI/检验/用药事件识别、7 天去重、七来源合并和机构日面板。

这些原始脚本含 Windows 绝对路径，并依赖样例中未提供的一致人员键和未掩码日期，因此作为规则来源保留，不由一键脚本逐文件直接执行。

服务器可执行入口位于项目根目录：

```bash
python scripts/run_data_governance.py
```

该入口从环境变量 `GOVERNANCE_INPUT_ROOT` 指定目录的 `care_home/*.xlsx` 识别老人底册和诊断表，生成主系统适配器可读取的 `data_governance/output/care_home_governed.csv`，并在清单中记录所有模拟补齐字段。未提供私有工作簿时，系统使用仓库内 `published_samples/care_home_governed.csv` 的去标识验证结果。
