"""Import raw school records and produce a traceable data-quality audit."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from _shared import (
    configure_logging,
    load_pipeline_config,
    parse_class_number,
    parse_grade,
    read_table,
    require_columns,
    write_excel,
)


def audit_inputs(
    records: pd.DataFrame, roster: pd.DataFrame, config: dict[str, Any]
) -> dict[str, pd.DataFrame]:
    columns = config["columns"]
    required_record_columns = list(columns.values())
    required_roster_columns = [
        "class_id",
        "school_code",
        "school_name",
        "grade",
        "class",
        "population",
    ]
    require_columns(records, required_record_columns, "原始记录")
    require_columns(roster, required_roster_columns, "班级人口表")

    file_summary = pd.DataFrame(
        [
            {
                "dataset": "raw_records",
                "rows": len(records),
                "columns": len(records.columns),
                "duplicate_rows": int(records.duplicated().sum()),
            },
            {
                "dataset": "class_population",
                "rows": len(roster),
                "columns": len(roster.columns),
                "duplicate_rows": int(roster.duplicated().sum()),
            },
        ]
    )

    variable_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    frequency_rows: list[dict[str, Any]] = []
    for dataset_name, frame in (("raw_records", records), ("class_population", roster)):
        for column in frame.columns:
            series = frame[column]
            blank = series.astype("string").fillna("").str.strip().eq("")
            missing = series.isna() | blank
            variable_rows.append(
                {
                    "dataset": dataset_name,
                    "column": column,
                    "dtype": str(series.dtype),
                    "unique_nonmissing": int(series.nunique(dropna=True)),
                }
            )
            missing_rows.append(
                {
                    "dataset": dataset_name,
                    "column": column,
                    "rows": len(frame),
                    "missing_n": int(missing.sum()),
                    "missing_pct": round(float(missing.mean() * 100), 3),
                }
            )
            if not pd.api.types.is_numeric_dtype(series):
                counts = series.astype("string").fillna("<NA>").str.strip().value_counts().head(20)
                for rank, (value, count) in enumerate(counts.items(), start=1):
                    frequency_rows.append(
                        {
                            "dataset": dataset_name,
                            "column": column,
                            "rank": rank,
                            "value": value,
                            "count": int(count),
                        }
                    )

    date_rows: list[dict[str, Any]] = []
    for key in ("report_date", "onset_date"):
        column = columns[key]
        parsed = pd.to_datetime(records[column], errors="coerce")
        date_rows.append(
            {
                "column": column,
                "valid_n": int(parsed.notna().sum()),
                "invalid_n": int(parsed.isna().sum()),
                "min": parsed.min(),
                "max": parsed.max(),
            }
        )

    roster_check = roster.copy()
    roster_check["school_name_key"] = roster_check["school_name"].astype("string").str.strip()
    roster_check["grade_key"] = pd.to_numeric(roster_check["grade"], errors="coerce")
    roster_check["class_key"] = pd.to_numeric(roster_check["class"], errors="coerce")
    raw_keys = records[[columns["school_name"], columns["grade"], columns["class_name"]]].copy()
    raw_keys.columns = ["school_name_key", "grade_raw", "class_raw"]
    raw_keys["school_name_key"] = raw_keys["school_name_key"].astype("string").str.strip()
    raw_keys["grade_key"] = raw_keys["grade_raw"].map(parse_grade)
    raw_keys["class_key"] = raw_keys["class_raw"].map(parse_class_number)
    matched = raw_keys.merge(
        roster_check[["school_name_key", "grade_key", "class_key", "class_id"]],
        on=["school_name_key", "grade_key", "class_key"],
        how="left",
    )

    issues: list[dict[str, Any]] = []
    if roster["class_id"].duplicated().any():
        issues.append({"severity": "error", "issue": "班级人口表class_id重复", "n": int(roster["class_id"].duplicated(False).sum())})
    invalid_population = pd.to_numeric(roster["population"], errors="coerce").le(0) | pd.to_numeric(roster["population"], errors="coerce").isna()
    if invalid_population.any():
        issues.append({"severity": "error", "issue": "班级人口缺失或非正数", "n": int(invalid_population.sum())})
    if matched["class_id"].isna().any():
        issues.append({"severity": "error", "issue": "原始记录无法匹配班级人口表", "n": int(matched["class_id"].isna().sum())})
    report_date = pd.to_datetime(records[columns["report_date"]], errors="coerce")
    onset_date = pd.to_datetime(records[columns["onset_date"]], errors="coerce")
    future_onset = report_date.notna() & onset_date.notna() & (onset_date > report_date)
    if future_onset.any():
        issues.append({"severity": "warning", "issue": "症状日期晚于上报日期", "n": int(future_onset.sum())})
    if not issues:
        issues.append({"severity": "info", "issue": "未发现阻断性结构问题", "n": 0})

    return {
        "00_file_summary": file_summary,
        "01_issues": pd.DataFrame(issues),
        "02_variables": pd.DataFrame(variable_rows),
        "03_missing": pd.DataFrame(missing_rows),
        "04_dates": pd.DataFrame(date_rows),
        "05_frequencies": pd.DataFrame(frequency_rows),
        "06_unmatched_classes": matched.loc[matched["class_id"].isna()].drop_duplicates(),
    }


def run(config_path: str | Path) -> Path:
    config = load_pipeline_config(config_path)
    records = read_table(Path(config["paths"]["raw_records"]))
    roster = read_table(Path(config["paths"]["class_population"]))
    output = Path(config["paths"]["output_dir"]) / "01_import_audit.xlsx"
    write_excel(output, audit_inputs(records, roster, config))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    print(f"数据质量审计已保存: {run(args.config)}")


if __name__ == "__main__":
    main()

