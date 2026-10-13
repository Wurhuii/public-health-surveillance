"""Clean dates, codes, duplicates, and population links in raw records."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from _shared import (
    configure_logging,
    load_pipeline_config,
    normalize_text,
    normalize_yes_no,
    parse_class_number,
    parse_grade,
    read_table,
    require_columns,
    write_excel,
)


def clean_records(
    raw: pd.DataFrame, roster: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    columns = config["columns"]
    require_columns(raw, columns.values(), "原始记录")
    require_columns(
        roster,
        ["class_id", "school_code", "school_name", "grade", "class", "population"],
        "班级人口表",
    )

    data = raw.copy()
    data.columns = [str(column).strip() for column in data.columns]
    data.insert(0, "source_row_id", np.arange(1, len(data) + 1))
    canonical_text = {
        "student_id": "student_id",
        "session": "session",
        "symptom_text": "symptom_text",
        "absence_type": "absence_type",
        "diagnosis": "diagnosis",
        "school_name": "school_name",
    }
    for config_key, target in canonical_text.items():
        data[target] = data[columns[config_key]].map(normalize_text)

    for config_key, target in (
        ("is_new", "is_new"),
        ("absence", "absence"),
        ("visit", "visit"),
        ("death", "death"),
    ):
        data[target] = data[columns[config_key]].map(normalize_yes_no)

    session_map = {"晨检": "morning", "午检": "afternoon", "上午": "morning", "下午": "afternoon"}
    data["session"] = data["session"].map(session_map).fillna("unknown")
    data["report_date"] = pd.to_datetime(data[columns["report_date"]], errors="coerce").dt.normalize()
    data["onset_date_original"] = pd.to_datetime(data[columns["onset_date"]], errors="coerce").dt.normalize()
    data["onset_missing_imputed"] = data["onset_date_original"].isna() & data["report_date"].notna()
    data["onset_after_report_flag"] = (
        data["onset_date_original"].notna()
        & data["report_date"].notna()
        & (data["onset_date_original"] > data["report_date"])
    )
    data["onset_date"] = data["onset_date_original"]
    repair_mask = data["onset_missing_imputed"] | data["onset_after_report_flag"]
    data.loc[repair_mask, "onset_date"] = data.loc[repair_mask, "report_date"]

    data["grade"] = data[columns["grade"]].map(parse_grade)
    data["class_number"] = data[columns["class_name"]].map(parse_class_number)
    roster_keys = roster.copy()
    roster_keys["school_name_key"] = roster_keys["school_name"].map(normalize_text)
    roster_keys["grade"] = pd.to_numeric(roster_keys["grade"], errors="coerce")
    roster_keys["class_number"] = pd.to_numeric(roster_keys["class"], errors="coerce")
    data["school_name_key"] = data["school_name"].map(normalize_text)
    data = data.merge(
        roster_keys[["school_name_key", "grade", "class_number", "class_id", "school_code", "population"]],
        on=["school_name_key", "grade", "class_number"],
        how="left",
        validate="many_to_one",
    )

    duplicate_key = ["student_id", "report_date", "session", "symptom_text", "class_id"]
    data["duplicate_record_flag"] = data.duplicated(duplicate_key, keep="first")
    duplicates = data.loc[data["duplicate_record_flag"]].copy()
    data = data.loc[~data["duplicate_record_flag"]].copy()
    data["valid_for_model"] = (
        data["student_id"].ne("")
        & data["report_date"].notna()
        & data["onset_date"].notna()
        & data["class_id"].notna()
        & pd.to_numeric(data["population"], errors="coerce").gt(0)
    )
    rejected = data.loc[~data["valid_for_model"]].copy()
    cleaned = data.loc[data["valid_for_model"]].copy()
    cleaned = cleaned.sort_values(["student_id", "onset_date", "report_date", "session", "source_row_id"])
    return cleaned.reset_index(drop=True), rejected.reset_index(drop=True), duplicates.reset_index(drop=True)


def run(config_path: str | Path) -> Path:
    config = load_pipeline_config(config_path)
    raw = read_table(Path(config["paths"]["raw_records"]))
    roster = read_table(Path(config["paths"]["class_population"]))
    cleaned, rejected, duplicates = clean_records(raw, roster, config)
    output = Path(config["paths"]["output_dir"]) / "02_clean_records.xlsx"
    write_excel(output, {"cleaned_records": cleaned, "rejected_records": rejected, "duplicate_records": duplicates})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    print(f"清理结果已保存: {run(args.config)}")


if __name__ == "__main__":
    main()

