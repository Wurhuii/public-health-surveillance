"""Reconstruct one illness episode per student and retain update-level history."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from _shared import configure_logging, load_pipeline_config, require_columns, write_excel


def _join_unique(values: pd.Series) -> str:
    unique = [str(value) for value in values if pd.notna(value) and str(value).strip()]
    return " | ".join(dict.fromkeys(unique))


def assign_episode_ids(records: pd.DataFrame, gap_days: int) -> pd.DataFrame:
    data = records.sort_values(
        ["student_id", "onset_date", "report_date", "session", "source_row_id"]
    ).copy()
    episode_numbers = pd.Series(index=data.index, dtype="Int64")
    for _, group in data.groupby("student_id", sort=False):
        previous_onset: pd.Timestamp | None = None
        episode_number = 0
        for index, row in group.iterrows():
            onset = row["onset_date"]
            gap = (onset - previous_onset).days if previous_onset is not None else np.inf
            explicit_new = row["is_new"] == "是" and previous_onset is not None and onset != previous_onset
            if previous_onset is None or gap > gap_days or explicit_new:
                episode_number += 1
            episode_numbers.loc[index] = episode_number
            previous_onset = onset
    data["student_episode_number"] = episode_numbers.astype(int)
    student_key = data["student_id"].astype(str).str.replace(r"\W+", "", regex=True)
    data["episode_id"] = student_key + "_E" + data["student_episode_number"].astype(str).str.zfill(3)
    return data


def build_episodes(
    cleaned: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = [
        "student_id", "report_date", "onset_date", "session", "is_new",
        "symptom_text", "absence", "absence_type", "visit", "diagnosis", "death",
        "school_name", "school_code", "grade", "class_number", "class_id", "source_row_id",
    ]
    require_columns(cleaned, required, "清理后记录")
    if config["episode"]["include_if_illness_absence_or_symptomatic"]:
        include = cleaned["absence_type"].str.contains("因病", na=False) | cleaned["symptom_text"].ne("")
        data = cleaned.loc[include].copy()
    else:
        data = cleaned.copy()
    updates = assign_episode_ids(data, int(config["episode"]["gap_days"]))
    updates["session_order"] = updates["session"].map({"morning": 0, "afternoon": 1}).fillna(2)
    updates = updates.sort_values(["episode_id", "report_date", "session_order", "source_row_id"])

    rows: list[dict[str, Any]] = []
    for episode_id, group in updates.groupby("episode_id", sort=False):
        first = group.iloc[0]
        onset = group["onset_date"].min()
        first_report = group["report_date"].min()
        rows.append(
            {
                "episode_id": episode_id,
                "student_id": first["student_id"],
                "onset_date": onset,
                "first_report_date": first_report,
                "first_report_session": first["session"],
                "symptom_text_combined": _join_unique(group["symptom_text"]),
                "absence_final": "是" if group["absence"].eq("是").any() else "否",
                "visit_final": "是" if group["visit"].eq("是").any() else "否",
                "diagnosis_combined": _join_unique(group["diagnosis"]),
                "death_final": "是" if group["death"].eq("是").any() else "否",
                "first_absence_yes_date": group.loc[group["absence"].eq("是"), "report_date"].min(),
                "first_visit_yes_date": group.loc[group["visit"].eq("是"), "report_date"].min(),
                "school_name": first["school_name"],
                "school_code": first["school_code"],
                "grade": first["grade"],
                "class_number": first["class_number"],
                "class_id": first["class_id"],
                "record_count": len(group),
                "organization_inconsistent": int(group["class_id"].nunique(dropna=True) > 1),
                "lead_time_days": int((first_report - onset).days),
            }
        )
    episodes = pd.DataFrame(rows).sort_values(["school_code", "class_id", "onset_date", "episode_id"])
    return episodes.reset_index(drop=True), updates.reset_index(drop=True)


def run(config_path: str | Path) -> Path:
    config = load_pipeline_config(config_path)
    input_path = Path(config["paths"]["output_dir"]) / "02_clean_records.xlsx"
    cleaned = pd.read_excel(input_path, sheet_name="cleaned_records", parse_dates=["report_date", "onset_date"])
    episodes, updates = build_episodes(cleaned, config)
    output = Path(config["paths"]["output_dir"]) / "03_student_episodes.xlsx"
    write_excel(output, {"episodes": episodes, "episode_updates": updates})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    print(f"学生发病episode已保存: {run(args.config)}")


if __name__ == "__main__":
    main()

