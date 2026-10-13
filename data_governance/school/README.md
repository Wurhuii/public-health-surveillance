# 学校急性呼吸道症候群监测预警代码包

本目录实现技术方案约定的 00–16 模块。代码默认不包含任何本机绝对路径；所有路径、窗口和原型阈值由单一 JSON 配置文件管理。

## 快速运行（推荐：无需 CMD）

1. 在 PyCharm 或 VS Code 中打开 `RUN_一键运行全部.py`。
2. 点击编辑器右上角的 **Run/运行**，或者右键该文件选择 **运行**。
3. 第一次运行时，通过弹出的窗口选择“学生原始记录”和“完整班级人口表”。程序会自动生成 `config.json`。
4. 模块 01—16 将按顺序批量运行，结果默认写入代码目录下的 `OUTPUT_DELIVERY`。

以后再次运行时，程序直接读取已有 `config.json`，不再要求输入命令或重复选择文件。需要更换数据时，可编辑 `config.json`，或删除它后重新运行一键入口。

`run_pipeline.py` 也支持直接点击 Run；其默认读取同目录 `config.json`。命令行方式仅作为服务器运行和自动化调度的兼容入口。

输入目录至少应包含：

- `DATA/school_data.xlsx`：学生晨午检、缺勤和就诊记录；
- `DATA/class_population_base.xlsx`：完整班级名册和人口分母。

输出写入配置中的 `output_dir`。若历史教学日或主症候群病例不足，基线模块仍可产生“研究原型”结果，但会明确标记 `prototype_only=1`，不得解释为已校准的生产阈值。

模块 16 会在输出目录下建立 `16_FIGURES`，生成 7 张 PNG 图、`16_figure_manifest.csv` 和 `16_figure_index.md`。不同运行方式和故障排查见本目录的 `运行指令.txt`。

## 运行顺序

`01_import_audit` → `02_clean_records` → `03_build_episode` → `04_define_syndromes` → `05_build_realtime_tables` → `06_fit_baseline` → `07_cluster_concentration` → `08_sequential_detection` → `09_merge_events` → `10_progression_model` → `11_dynamic_grading` → `12_threshold_injection` → `13_freeze_model` → `14_reference_evaluation` → `15_generate_report` → `16_generate_figures`。

模型冻结和最终参考事件评价必须在锁定评价数据上按盲法流程执行。没有独立参考事件时，模块 14 只生成待填写模板，不会伪造性能指标。
