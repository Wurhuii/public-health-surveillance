"""Generate a concise Markdown operations report from pipeline outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from _shared import configure_logging, load_pipeline_config


def generate_report(config_path: str | Path) -> Path:
    config = load_pipeline_config(config_path)
    output_dir = Path(config["paths"]["output_dir"])
    diagnostics = pd.read_excel(output_dir / "06_baseline_predictions.xlsx", sheet_name="diagnostics").iloc[0]
    latest = pd.read_excel(output_dir / "11_dynamic_grading.xlsx", sheet_name="latest_event_status")
    grid = pd.read_excel(output_dir / "12_threshold_injection.xlsx", sheet_name="threshold_grid").head(10)
    with (output_dir / "13_model_freeze_manifest.json").open("r", encoding="utf-8") as handle:
        freeze = json.load(handle)
    evaluation_status = pd.read_excel(output_dir / "14_reference_evaluation.xlsx", sheet_name=0).iloc[0].to_dict()

    lines = [
        "# 学校急性呼吸道症候群监测预警运行报告",
        "",
        "## 模型状态",
        "",
        f"- 冻结状态：`{freeze['status']}`",
        f"- 基线方法：`{diagnostics['fit_method']}`",
        f"- 历史教学日：{int(diagnostics['history_teaching_days'])}",
        f"- 主症候群病例：{int(diagnostics['training_primary_cases'])}",
        f"- 生产可用：{'否（仅研究原型）' if int(diagnostics['prototype_only']) else '是（仍需独立评价）'}",
        "",
        "## 当前候选事件",
        "",
    ]
    if latest.empty:
        lines.append("当前没有满足候选事件触发条件的事件。")
    else:
        for row in latest.sort_values(["final_level", "date"], ascending=[False, False]).itertuples(index=False):
            lines.extend(
                [
                    f"### {row.cluster_event_id} | {row.final_level} ({row.direction})",
                    "",
                    f"- 日期：{pd.Timestamp(row.date):%Y-%m-%d}",
                    f"- 涉及单位：{row.class_ids}",
                    f"- 证据：{row.reason_text}",
                    f"- 建议：{row.recommended_action}",
                    "",
                ]
            )
    lines.extend(
        [
            "## 阈值与评价声明",
            "",
            "- 半合成注入表只用于原型筛选，正式阈值必须在固定报警负担下通过全链路A/B/C与事件状态机复测。",
            f"- 参考事件评价状态：`{evaluation_status.get('status', 'completed')}`。",
            "- 本系统输出急性呼吸道症候群异常和疑似聚集，不确认具体病原或传播链。",
            "",
        ]
    )
    if not grid.empty:
        lines.extend(["## 原型阈值网格前10项", "", grid.to_markdown(index=False), ""])
    lines.extend(
        [
            "## 图形输出",
            "",
            "完整流水线运行后，模块 16 会生成以下可视化结果：",
            "",
            "- [图形索引](16_figure_index.md)",
            "- [PNG 图形目录](16_FIGURES)",
            "- [图形清单](16_figure_manifest.csv)",
            "",
        ]
    )
    output = output_dir / "15_monitoring_report.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    print(f"监测报告已保存: {generate_report(args.config)}")


if __name__ == "__main__":
    main()
