"""Create a blinded reference-event template or evaluate locked events."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from _shared import configure_logging, load_pipeline_config, read_table, write_excel


REFERENCE_COLUMNS = [
    "reference_event_id", "school_code", "start_date", "end_date", "class_ids",
    "reference_label", "reviewer_1", "reviewer_2", "adjudicator", "locked_at",
]


def class_set(value: Any) -> set[str]:
    if pd.isna(value):
        return set()
    return {item.strip() for item in str(value).replace(",", ";").split(";") if item.strip()}


def evaluate(alerts: pd.DataFrame, references: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    tolerance = int(config["evaluation"]["event_overlap_days"])
    minimum_jaccard = float(config["evaluation"]["minimum_class_jaccard"])
    alerts = alerts.loc[alerts["final_level"].isin(["yellow", "orange", "red"])].copy()
    first_alert = alerts.sort_values("date").groupby("cluster_event_id", as_index=False).first()
    references = references.copy()
    references["start_date"] = pd.to_datetime(references["start_date"], errors="coerce")
    references["end_date"] = pd.to_datetime(references["end_date"], errors="coerce")
    matches: list[dict[str, Any]] = []
    used_alerts: set[str] = set()
    for reference in references.itertuples(index=False):
        best: dict[str, Any] | None = None
        reference_classes = class_set(reference.class_ids)
        for alert in first_alert.itertuples(index=False):
            if alert.school_code != reference.school_code or alert.cluster_event_id in used_alerts:
                continue
            alert_date = pd.Timestamp(alert.date)
            if alert_date < reference.start_date - pd.Timedelta(days=tolerance) or alert_date > reference.end_date + pd.Timedelta(days=tolerance):
                continue
            alert_classes = class_set(alert.class_ids)
            union = reference_classes | alert_classes
            jaccard = len(reference_classes & alert_classes) / len(union) if union else 1.0
            if jaccard < minimum_jaccard:
                continue
            candidate = {
                "reference_event_id": reference.reference_event_id,
                "cluster_event_id": alert.cluster_event_id,
                "reference_start": reference.start_date,
                "first_alert_date": alert_date,
                "lead_time_days": (reference.start_date - alert_date).days,
                "class_jaccard": jaccard,
            }
            if best is None or candidate["class_jaccard"] > best["class_jaccard"]:
                best = candidate
        if best:
            matches.append(best)
            used_alerts.add(best["cluster_event_id"])
        else:
            matches.append({"reference_event_id": reference.reference_event_id, "cluster_event_id": "", "reference_start": reference.start_date, "first_alert_date": pd.NaT, "lead_time_days": np.nan, "class_jaccard": np.nan})
    matches_frame = pd.DataFrame(matches)
    true_events = references["reference_label"].isin(["high_confidence", "probable"])
    true_ids = set(references.loc[true_events, "reference_event_id"].astype(str))
    detected_true = matches_frame["reference_event_id"].astype(str).isin(true_ids) & matches_frame["cluster_event_id"].ne("")
    matched_true_alerts = matches_frame.loc[
        matches_frame["reference_event_id"].astype(str).isin(true_ids), "cluster_event_id"
    ].replace("", np.nan).dropna().nunique()
    metrics = pd.DataFrame(
        [
            {
                "reference_true_events": len(true_ids),
                "detected_true_events": int(detected_true.sum()),
                "event_sensitivity": int(detected_true.sum()) / len(true_ids) if true_ids else np.nan,
                "alert_events": first_alert["cluster_event_id"].nunique(),
                "matched_alert_events": matched_true_alerts,
                "event_ppv": matched_true_alerts / first_alert["cluster_event_id"].nunique() if len(first_alert) else np.nan,
                "median_lead_time_days": matches_frame.loc[detected_true, "lead_time_days"].median(),
            }
        ]
    )
    return matches_frame, metrics


def run(config_path: str | Path) -> list[Path]:
    config = load_pipeline_config(config_path)
    output_dir = Path(config["paths"]["output_dir"])
    alerts = pd.read_excel(output_dir / "11_dynamic_grading.xlsx", sheet_name="event_daily_grades", parse_dates=["date"])
    reference_path_text = config["paths"].get("reference_events", "")
    template_path = output_dir / "14_reference_event_template.xlsx"
    evaluation_path = output_dir / "14_reference_evaluation.xlsx"
    if not reference_path_text or not Path(reference_path_text).exists():
        template = pd.DataFrame(columns=REFERENCE_COLUMNS)
        status = pd.DataFrame([{"status": "not_evaluated", "reason": "未提供锁定、盲法判定的参考事件库；不得据此声称敏感度或PPV。"}])
        write_excel(template_path, {"reference_events": template, "instructions": status})
        write_excel(evaluation_path, {"status": status})
        return [template_path, evaluation_path]
    references = read_table(Path(reference_path_text))
    missing = sorted(set(REFERENCE_COLUMNS[:6]) - set(references.columns))
    if missing:
        raise ValueError(f"参考事件库缺少字段: {missing}")
    matches, metrics = evaluate(alerts, references, config)
    write_excel(evaluation_path, {"matches": matches, "metrics": metrics})
    return [evaluation_path]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    for output in run(args.config):
        print(f"参考事件评价产物已保存: {output}")


if __name__ == "__main__":
    main()
