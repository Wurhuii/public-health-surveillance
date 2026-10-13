"""Estimate candidate-event progression risk or use a transparent rule proxy."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from _shared import configure_logging, load_pipeline_config, require_columns, write_excel


FEATURES = [
    "current_cases", "expected_cases", "max_oe", "min_tail_p", "max_a_strength",
    "max_concentration_ratio", "min_concentration_q", "max_sequential_statistic",
    "detector_count", "resp_absence_count", "visit_count", "affected_classes", "affected_grades",
]


def add_progression_labels(event_daily: pd.DataFrame, horizon: int) -> pd.DataFrame:
    result = event_daily.sort_values(["cluster_event_id", "date"]).copy()
    result["progression_label"] = 0
    for _, group in result.groupby("cluster_event_id"):
        indices = list(group.index)
        for position, index in enumerate(indices):
            future = group.iloc[position + 1:position + 1 + horizon]
            if future.empty:
                result.loc[index, "progression_label"] = np.nan
                continue
            current = result.loc[index]
            progressed = (
                future["current_cases"].max() >= current["current_cases"] + 2
                or future["affected_classes"].max() > current["affected_classes"]
                or future["affected_grades"].max() > current["affected_grades"]
            )
            result.loc[index, "progression_label"] = int(progressed)
    return result


def rule_proxy(frame: pd.DataFrame) -> np.ndarray:
    score = (
        0.8 * frame["current_cases"].ge(3).astype(float)
        + 0.8 * frame["max_a_strength"].ge(2).astype(float)
        + 0.6 * frame["max_concentration_ratio"].ge(2).astype(float)
        + 0.6 * frame["max_sequential_statistic"].gt(0).astype(float)
        + 0.8 * frame["affected_classes"].ge(2).astype(float)
        + 0.6 * frame["affected_grades"].ge(2).astype(float)
        + 0.4 * frame["visit_count"].gt(0).astype(float)
        - 2.0
    )
    return 1.0 / (1.0 + np.exp(-score.to_numpy()))


def fit_progression(
    event_daily: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if event_daily.empty:
        empty = event_daily.copy()
        empty["progression_probability"] = pd.Series(dtype=float)
        empty["progression_method"] = pd.Series(dtype="string")
        return empty, {"method": "no_candidate_events", "model": None}
    require_columns(event_daily, ["cluster_event_id", "date", *FEATURES], "候选事件日表")
    labelled = add_progression_labels(event_daily, int(config["progression"]["horizon_teaching_days"]))
    train = labelled.loc[labelled["progression_label"].notna()].copy()
    enough = (
        train["cluster_event_id"].nunique() >= int(config["progression"]["min_events_for_model"])
        and int(train["progression_label"].sum()) >= int(config["progression"]["min_positive_events"])
        and train["progression_label"].nunique() == 2
    )
    model: Pipeline | None = None
    if enough:
        transformer = ColumnTransformer(
            [("numeric", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), FEATURES)]
        )
        model = Pipeline(
            [("features", transformer), ("model", LogisticRegression(penalty="l2", class_weight="balanced", max_iter=1000, random_state=int(config["progression"]["random_seed"])))]
        )
        model.fit(train[FEATURES], train["progression_label"].astype(int))
        labelled["progression_probability"] = model.predict_proba(labelled[FEATURES])[:, 1]
        method = "penalized_logistic"
    else:
        labelled["progression_probability"] = rule_proxy(labelled)
        method = "rule_proxy_insufficient_events"
    labelled["progression_method"] = method
    labelled["progression_risk_band"] = pd.cut(
        labelled["progression_probability"], bins=[-np.inf, 0.25, 0.5, 0.75, np.inf], labels=["low", "medium", "high", "very_high"]
    ).astype("string")
    return labelled, {"method": method, "model": model, "training_rows": len(train), "events": int(train["cluster_event_id"].nunique()), "positive_rows": int(train["progression_label"].sum())}


def run(config_path: str | Path) -> list[Path]:
    config = load_pipeline_config(config_path)
    output_dir = Path(config["paths"]["output_dir"])
    event_daily = pd.read_excel(output_dir / "09_candidate_events.xlsx", sheet_name="event_daily", parse_dates=["date", "first_signal_date"])
    result, model_info = fit_progression(event_daily, config)
    output = output_dir / "10_progression_risk.xlsx"
    model_path = output_dir / "10_progression_model.joblib"
    metadata = pd.DataFrame([{key: value for key, value in model_info.items() if key != "model"}])
    write_excel(output, {"event_daily_risk": result, "model_status": metadata})
    joblib.dump({"model": model_info["model"], "features": FEATURES, "metadata": metadata.to_dict(orient="records")}, model_path)
    return [output, model_path]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    for output in run(args.config):
        print(f"进展风险结果已保存: {output}")


if __name__ == "__main__":
    main()
