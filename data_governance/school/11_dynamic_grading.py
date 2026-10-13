"""Convert detector evidence into a hysteretic green-to-red event state."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from _shared import configure_logging, load_pipeline_config, require_columns, write_excel


LEVELS = ["green", "blue", "yellow", "orange", "red"]
LEVEL_TO_SCORE = {level: score for score, level in enumerate(LEVELS)}


def dimension_levels(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    result["A_level"] = result["max_a_strength"].fillna(0).clip(0, 3).astype(int)
    result.loc[(result["max_a_strength"].ge(3) & result["current_cases"].ge(5)), "A_level"] = 4
    result["K_level"] = 0
    result.loc[result["min_concentration_q"].le(0.05) & result["max_concentration_ratio"].gt(1), "K_level"] = 1
    result.loc[result["min_concentration_q"].le(0.01) & result["max_concentration_ratio"].ge(2), "K_level"] = 2
    result.loc[result["min_concentration_q"].le(0.001) & result["current_cases"].ge(3), "K_level"] = 3
    result.loc[result["affected_classes"].ge(2) | result["affected_grades"].ge(2), "K_level"] = 4
    result["G_level"] = 0
    result.loc[result["max_sequential_statistic"].gt(0), "G_level"] = 1
    result.loc[result["progression_probability"].ge(0.5), "G_level"] = 2
    result.loc[result["progression_probability"].ge(0.75), "G_level"] = 3
    result.loc[result["affected_classes"].ge(3) | result["affected_grades"].ge(2), "G_level"] = 4
    result["H_level"] = 0
    result.loc[result["resp_absence_count"].gt(0), "H_level"] = 1
    result.loc[result["visit_count"].gt(0), "H_level"] = 2
    return result


def provisional_level(row: pd.Series) -> str:
    if row["H_level"] >= 4 or (row["affected_grades"] >= 3 and row["current_cases"] >= 6):
        return "red"
    if (
        (row["A_level"] >= 3 and row["K_level"] >= 2)
        or row["G_level"] >= 3
        or (row["affected_classes"] >= 2 and row["A_level"] >= 2)
    ):
        return "orange"
    if row["K_level"] >= 2 or (row["A_level"] >= 2 and row["G_level"] >= 1) or row["detector_count"] >= 2:
        return "yellow"
    if max(row["A_level"], row["K_level"], row["G_level"], row["H_level"]) >= 1:
        return "blue"
    return "green"


def grade_events(event_daily: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if event_daily.empty:
        empty = event_daily.copy()
        for column in ("A_level", "K_level", "G_level", "H_level", "provisional_level", "final_level", "direction", "reason_text"):
            empty[column] = pd.Series(dtype="string")
        return empty
    require_columns(
        event_daily,
        ["cluster_event_id", "date", "current_cases", "new_known_cases", "event_trigger", "max_a_strength", "min_concentration_q", "max_concentration_ratio", "max_sequential_statistic", "progression_probability", "affected_classes", "affected_grades", "resp_absence_count", "visit_count", "detector_count"],
        "事件进展表",
    )
    result = dimension_levels(event_daily).sort_values(["cluster_event_id", "date"]).copy()
    result["provisional_level"] = result.apply(provisional_level, axis=1)
    confirmation_needed = int(config["grading"]["downgrade_confirm_updates"])
    final_levels: list[str] = []
    directions: list[str] = []
    lifecycle_states: list[str] = []
    close_after = int(config["grading"]["close_after_no_new_teaching_days"])
    for _, group in result.groupby("cluster_event_id", sort=False):
        previous_score = 0
        lower_count = 0
        quiet_count = 0
        for row in group.itertuples(index=False):
            provisional_score = LEVEL_TO_SCORE[row.provisional_level]
            if provisional_score > previous_score:
                current_score = provisional_score
                lower_count = 0
                direction = "up"
            elif provisional_score == previous_score:
                current_score = previous_score
                lower_count = 0
                direction = "stable"
            else:
                lower_count += 1
                if lower_count >= confirmation_needed:
                    current_score = max(previous_score - 1, provisional_score)
                    lower_count = 0
                    direction = "down"
                else:
                    current_score = previous_score
                    direction = "stable"
            final_levels.append(LEVELS[current_score])
            directions.append(direction)
            if row.event_trigger == 0 and row.new_known_cases == 0 and max(row.A_level, row.K_level, row.G_level) <= 1:
                quiet_count += 1
            else:
                quiet_count = 0
            lifecycle_states.append("closed" if quiet_count >= close_after else ("recovery" if quiet_count > 0 else "active"))
            previous_score = current_score
    result["final_level"] = final_levels
    result["direction"] = directions
    result["lifecycle_state"] = lifecycle_states
    result["reason_text"] = result.apply(
        lambda row: (
            f"A{row.A_level}/K{row.K_level}/G{row.G_level}/H{row.H_level}; "
            f"近窗{int(row.current_cases)}例，涉及{int(row.affected_classes)}班，"
            f"未来3日风险{row.progression_probability:.1%}，状态{row.lifecycle_state}"
        ),
        axis=1,
    )
    result["recommended_action"] = result["final_level"].map(
        {
            "green": "常规监测",
            "blue": "核查数据并关注下一次更新",
            "yellow": "校内核实症状、发病日期、缺勤与就诊",
            "orange": "启动报告和现场调查流程",
            "red": "升级响应并联动疾控和教育部门",
        }
    )
    return result


def run(config_path: str | Path) -> Path:
    config = load_pipeline_config(config_path)
    output_dir = Path(config["paths"]["output_dir"])
    event_daily = pd.read_excel(output_dir / "10_progression_risk.xlsx", sheet_name="event_daily_risk", parse_dates=["date", "first_signal_date"])
    graded = grade_events(event_daily, config)
    latest = graded.sort_values("date").groupby("cluster_event_id", as_index=False).tail(1) if not graded.empty else graded.copy()
    output = output_dir / "11_dynamic_grading.xlsx"
    write_excel(output, {"event_daily_grades": graded, "latest_event_status": latest})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    print(f"动态风险分级已保存: {run(args.config)}")


if __name__ == "__main__":
    main()
