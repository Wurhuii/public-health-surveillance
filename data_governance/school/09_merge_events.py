"""Fuse independent detector evidence and merge signals into candidate events."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from _shared import configure_logging, load_pipeline_config, require_columns, write_excel


def fuse_signals(
    baseline: pd.DataFrame,
    concentration: pd.DataFrame,
    sequential: pd.DataFrame,
    class_daily: pd.DataFrame,
) -> pd.DataFrame:
    keys = ["date", "school_code", "class_id"]
    a_columns = keys + ["grade", "O", "E", "A_O_3d", "A_E_3d", "A_OE_3d", "A_tail_p_3d", "A_strength", "prototype_only"]
    result = baseline[a_columns].copy()
    b_columns = keys + [column for column in concentration if column.startswith("B_")]
    result = result.merge(concentration[b_columns], on=keys, how="left")
    c_columns = keys + ["C_z", "C_max_statistic", "C_any_candidate", "C_prototype_only"]
    result = result.merge(sequential[c_columns], on=keys, how="left")
    enhancements = class_daily[keys + ["resp_absence_count", "visit_count", "new_known_febrile_ari"]]
    result = result.merge(enhancements, on=keys, how="left")
    result["B_any_candidate"] = result["B_any_candidate"].fillna(0).astype(int)
    result["C_any_candidate"] = result["C_any_candidate"].fillna(0).astype(int)
    result["A_candidate"] = result["A_strength"].ge(1).astype(int)
    result["medium_evidence_count"] = (
        result["A_strength"].ge(2).astype(int)
        + result["B_any_candidate"]
        + result["C_any_candidate"]
        + ((result["resp_absence_count"] > 0) | (result["visit_count"] > 0)).astype(int)
    )
    result["strong_evidence"] = (
        result["A_strength"].ge(3)
        | (result["A_strength"].ge(2) & result["B_any_candidate"].eq(1))
    ).astype(int)
    result["event_trigger"] = (
        result["strong_evidence"].eq(1) | result["medium_evidence_count"].ge(2)
    ).astype(int)
    result["blue_observation"] = (
        result[["A_candidate", "B_any_candidate", "C_any_candidate"]].max(axis=1).eq(1)
        & result["event_trigger"].eq(0)
    ).astype(int)
    result["detector_count"] = result[["A_candidate", "B_any_candidate", "C_any_candidate"]].sum(axis=1)
    return result


def merge_candidate_events(signals: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    triggered = signals.loc[signals["event_trigger"].eq(1)].copy().sort_values(["school_code", "date", "class_id"])
    if triggered.empty:
        return triggered.assign(cluster_event_id=pd.Series(dtype="string")), pd.DataFrame()
    unique_dates = sorted(signals["date"].dropna().unique())
    date_index = {pd.Timestamp(date): index for index, date in enumerate(unique_dates)}
    gap = int(config["events"]["merge_gap_teaching_days"])
    same_grade = bool(config["events"]["merge_same_grade"])
    registry: list[dict[str, Any]] = []
    assignments: list[str] = []
    counters: dict[str, int] = {}
    for row in triggered.itertuples(index=False):
        current_index = date_index[pd.Timestamp(row.date)]
        candidates = [
            event for event in registry
            if event["school_code"] == row.school_code
            and current_index - event["last_index"] <= gap
            and (
                row.class_id in event["classes"]
                or (same_grade and row.grade in event["grades"] and current_index - event["last_index"] <= 1)
            )
        ]
        if candidates:
            event = max(candidates, key=lambda item: item["last_index"])
        else:
            counters[row.school_code] = counters.get(row.school_code, 0) + 1
            event = {
                "event_id": f"{row.school_code}_{pd.Timestamp(row.date):%Y%m%d}_{counters[row.school_code]:03d}",
                "school_code": row.school_code,
                "classes": set(),
                "grades": set(),
                "first_date": row.date,
                "last_index": current_index,
            }
            registry.append(event)
        event["classes"].add(row.class_id)
        event["grades"].add(row.grade)
        event["last_index"] = current_index
        assignments.append(event["event_id"])
    triggered["cluster_event_id"] = assignments
    # Expand every event to successive monitoring updates.  This is essential for
    # recovery/closure logic; retaining trigger dates only would make a state
    # machine unable to observe quiet days.
    close_days = int(config["events"]["close_after_no_new_teaching_days"])
    event_rows: list[dict[str, Any]] = []
    for event in registry:
        start_index = date_index[pd.Timestamp(event["first_date"])]
        last_trigger_index = int(event["last_index"])
        end_index = min(last_trigger_index + close_days, len(unique_dates) - 1)
        for current_index in range(start_index, end_index + 1):
            current_date = pd.Timestamp(unique_dates[current_index])
            subset = signals.loc[
                signals["school_code"].eq(event["school_code"])
                & signals["date"].eq(current_date)
                & signals["class_id"].isin(event["classes"])
            ]
            if subset.empty:
                continue
            affected = subset.loc[subset["A_O_3d"].gt(0)]
            event_rows.append(
                {
                    "cluster_event_id": event["event_id"],
                    "date": current_date,
                    "school_code": event["school_code"],
                    "current_cases": float(subset["A_O_3d"].sum()),
                    "expected_cases": float(subset["A_E_3d"].sum()),
                    "max_oe": subset["A_OE_3d"].max(),
                    "min_tail_p": subset["A_tail_p_3d"].min(),
                    "max_a_strength": int(subset["A_strength"].max()),
                    "max_concentration_ratio": subset["B_CR_3d"].max(),
                    "min_concentration_q": subset["B_q_fdr_3d"].min(),
                    "max_sequential_statistic": subset["C_max_statistic"].max(),
                    "detector_count": int(subset["detector_count"].max()),
                    "resp_absence_count": int(subset["resp_absence_count"].sum()),
                    "visit_count": int(subset["visit_count"].sum()),
                    "new_known_cases": int(subset["new_known_febrile_ari"].sum()),
                    "event_trigger": int(subset["event_trigger"].max()),
                    "affected_classes": int(affected["class_id"].nunique()),
                    "affected_grades": int(affected["grade"].nunique()),
                    "class_ids": ";".join(sorted(map(str, event["classes"]))),
                    "grades": ";".join(sorted(map(str, event["grades"]))),
                    "first_signal_date": pd.Timestamp(event["first_date"]),
                    "last_trigger_date": pd.Timestamp(unique_dates[last_trigger_index]),
                    "days_since_last_trigger": max(current_index - last_trigger_index, 0),
                }
            )
    event_daily = pd.DataFrame(event_rows).sort_values(["cluster_event_id", "date"]).reset_index(drop=True)
    return triggered, event_daily


def run(config_path: str | Path) -> Path:
    config = load_pipeline_config(config_path)
    output_dir = Path(config["paths"]["output_dir"])
    baseline = pd.read_excel(output_dir / "06_baseline_predictions.xlsx", sheet_name="predictions", parse_dates=["date"])
    concentration = pd.read_excel(output_dir / "07_cluster_concentration.xlsx", sheet_name="class_wide", parse_dates=["date"])
    sequential = pd.read_excel(output_dir / "08_sequential_detection.xlsx", sheet_name="sequential", parse_dates=["date"])
    class_daily = pd.read_excel(output_dir / "05-2_class_daily.xlsx", sheet_name="data", parse_dates=["date"])
    signals = fuse_signals(baseline, concentration, sequential, class_daily)
    triggered, event_daily = merge_candidate_events(signals, config)
    output = output_dir / "09_candidate_events.xlsx"
    write_excel(output, {"class_daily_signals": signals, "triggered_signals": triggered, "event_daily": event_daily})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    print(f"候选事件结果已保存: {run(args.config)}")


if __name__ == "__main__":
    main()
