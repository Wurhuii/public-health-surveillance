"""Run one-sided EWMA and CUSUM on negative-binomial Pearson residuals."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from _shared import configure_logging, load_pipeline_config, require_columns, write_excel


def ewma_one_sided(values: np.ndarray, lam: float) -> np.ndarray:
    output = np.zeros(len(values), dtype=float)
    previous = 0.0
    for index, value in enumerate(values):
        value = float(value) if np.isfinite(value) else 0.0
        previous = max(0.0, lam * value + (1.0 - lam) * previous)
        output[index] = previous
    return output


def cusum_one_sided(values: np.ndarray, k: float) -> np.ndarray:
    output = np.zeros(len(values), dtype=float)
    previous = 0.0
    for index, value in enumerate(values):
        value = float(value) if np.isfinite(value) else 0.0
        previous = max(0.0, previous + value - k)
        output[index] = previous
    return output


def consecutive_true(values: pd.Series) -> pd.Series:
    group = (~values).cumsum()
    return values.astype(int).groupby(group).cumsum()


def run_sequential(predictions: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    require_columns(predictions, ["date", "school_code", "class_id", "O", "E", "alpha", "A_strength"], "基线预测表")
    result = predictions.copy().sort_values(["school_code", "class_id", "date"]).reset_index(drop=True)
    variance = np.maximum(result["E"] + result["alpha"] * result["E"] ** 2, 1e-8)
    result["C_z"] = (result["O"] - result["E"]) / np.sqrt(variance)
    statistics: list[str] = []
    for lam in config["detectors"]["ewma_lambdas"]:
        column = f"C_EWMA_{str(lam).replace('.', '')}"
        result[column] = result.groupby(["school_code", "class_id"])["C_z"].transform(
            lambda series: ewma_one_sided(series.to_numpy(), float(lam))
        )
        statistics.append(column)
    for k in config["detectors"]["cusum_k"]:
        column = f"C_CUSUM_k{str(k).replace('.', '')}"
        result[column] = result.groupby(["school_code", "class_id"])["C_z"].transform(
            lambda series: cusum_one_sided(series.to_numpy(), float(k))
        )
        statistics.append(column)

    training_end_text = config["baseline"].get("training_end", "")
    unique_dates = pd.Series(result["date"].dropna().sort_values().unique())
    if training_end_text:
        calibration_end = pd.Timestamp(training_end_text)
        prototype = 0
    else:
        calibration_end = unique_dates.iloc[max(int(len(unique_dates) * 0.7) - 1, 0)]
        prototype = 1
    calibration_mask = result["date"].le(calibration_end) & result["A_strength"].eq(0)
    quantile = float(config["detectors"]["sequential_calibration_quantile"])
    minimum_consecutive = int(config["detectors"]["sequential_min_consecutive"])
    threshold_rows: list[dict] = []
    candidate_columns: list[str] = []
    for column in statistics:
        normal_values = result.loc[calibration_mask, column].dropna()
        threshold = float(normal_values.quantile(quantile)) if len(normal_values) else np.inf
        exceed = result[column].gt(threshold)
        run_length = exceed.groupby([result["school_code"], result["class_id"]], group_keys=False).transform(consecutive_true)
        candidate = f"{column}_candidate"
        result[f"{column}_run"] = run_length.astype(int)
        result[candidate] = (exceed & run_length.ge(minimum_consecutive)).astype(int)
        candidate_columns.append(candidate)
        threshold_rows.append(
            {"statistic": column, "threshold": threshold, "quantile": quantile, "calibration_end": calibration_end, "prototype_only": prototype}
        )
    result["C_any_candidate"] = result[candidate_columns].max(axis=1).astype(int)
    result["C_max_statistic"] = result[statistics].max(axis=1)
    result["C_prototype_only"] = prototype
    return result, pd.DataFrame(threshold_rows)


def run(config_path: str | Path) -> Path:
    config = load_pipeline_config(config_path)
    path = Path(config["paths"]["output_dir"]) / "06_baseline_predictions.xlsx"
    predictions = pd.read_excel(path, sheet_name="predictions", parse_dates=["date"])
    result, thresholds = run_sequential(predictions, config)
    output = Path(config["paths"]["output_dir"]) / "08_sequential_detection.xlsx"
    write_excel(output, {"sequential": result, "thresholds": thresholds})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    print(f"EWMA/CUSUM结果已保存: {run(args.config)}")


if __name__ == "__main__":
    main()

