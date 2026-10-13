"""Detect class and grade concentration with conditional binomial tests."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import binom

from _shared import bh_fdr, configure_logging, load_pipeline_config, require_columns, safe_divide, write_excel


def concentration_long(
    class_daily: pd.DataFrame,
    unit: str,
    windows: list[int],
    fdr_alpha: float,
    min_cases: int,
) -> pd.DataFrame:
    require_columns(class_daily, ["date", "school_code", "grade", "class_id", "class_population", "new_known_febrile_ari"], "班级日表")
    data = class_daily[["date", "school_code", "grade", "class_id", "class_population", "new_known_febrile_ari"]].copy()
    data = data.rename(columns={"new_known_febrile_ari": "O"})
    if unit == "grade":
        data = data.groupby(["date", "school_code", "grade"], as_index=False).agg(O=("O", "sum"), population=("class_population", "sum"))
        unit_column = "grade"
    else:
        data = data.rename(columns={"class_population": "population"})
        unit_column = "class_id"
    data = data.sort_values(["school_code", unit_column, "date"])
    parts: list[pd.DataFrame] = []
    for window in windows:
        current = data.copy()
        current["x"] = current.groupby(["school_code", unit_column])["O"].transform(
            lambda series: series.rolling(window, min_periods=1).sum()
        )
        current["M_school"] = current.groupby(["school_code", "date"])["x"].transform("sum")
        current["N_school"] = current.groupby(["school_code", "date"])["population"].transform("sum")
        current["population_share"] = safe_divide(current["population"], current["N_school"])
        valid = current["M_school"].gt(0) & current["population_share"].gt(0)
        current["p_cluster"] = np.nan
        current.loc[valid, "p_cluster"] = binom.sf(
            current.loc[valid, "x"] - 1,
            current.loc[valid, "M_school"],
            current.loc[valid, "population_share"],
        )
        current["concentration_ratio"] = safe_divide(
            safe_divide(current["x"], current["M_school"]), current["population_share"]
        )
        current["window"] = window
        parts.append(current)
    result = pd.concat(parts, ignore_index=True)
    result["q_fdr"] = result.groupby(["school_code", "date"])["p_cluster"].transform(lambda series: bh_fdr(series.to_numpy()))
    result["cluster_candidate"] = (
        result["q_fdr"].le(fdr_alpha)
        & result["concentration_ratio"].gt(1)
        & result["x"].ge(min_cases)
    ).astype(int)
    result["level"] = unit
    return result


def class_wide(long_result: pd.DataFrame) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for window, group in long_result.groupby("window"):
        columns = ["date", "school_code", "class_id", "x", "M_school", "population_share", "p_cluster", "q_fdr", "concentration_ratio", "cluster_candidate"]
        part = group[columns].rename(
            columns={
                "x": f"B_x_{window}d", "M_school": f"B_M_school_{window}d",
                "population_share": f"B_population_share_{window}d", "p_cluster": f"B_p_cluster_{window}d",
                "q_fdr": f"B_q_fdr_{window}d", "concentration_ratio": f"B_CR_{window}d",
                "cluster_candidate": f"B_candidate_{window}d",
            }
        )
        parts.append(part)
    wide = parts[0]
    for part in parts[1:]:
        wide = wide.merge(part, on=["date", "school_code", "class_id"], how="outer")
    candidate_columns = [column for column in wide if column.startswith("B_candidate_")]
    wide["B_any_candidate"] = wide[candidate_columns].fillna(0).max(axis=1).astype(int)
    return wide


def run(config_path: str | Path) -> Path:
    config = load_pipeline_config(config_path)
    path = Path(config["paths"]["output_dir"]) / "05-2_class_daily.xlsx"
    daily = pd.read_excel(path, sheet_name="data", parse_dates=["date"])
    windows = [int(value) for value in config["detectors"]["b_windows"]]
    fdr_alpha = float(config["detectors"]["b_fdr_alpha"])
    min_cases = int(config["detectors"]["b_min_cases"])
    class_result = concentration_long(daily, "class", windows, fdr_alpha, min_cases)
    grade_result = concentration_long(daily, "grade", windows, fdr_alpha, min_cases)
    wide = class_wide(class_result)
    output = Path(config["paths"]["output_dir"]) / "07_cluster_concentration.xlsx"
    write_excel(output, {"class_long": class_result, "class_wide": wide, "grade_long": grade_result})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    print(f"集中性探测结果已保存: {run(args.config)}")


if __name__ == "__main__":
    main()

