"""Configuration contract for the school monitoring and warning pipeline.

Run ``python 00_config.py --write-example config.json`` to create an editable
configuration.  All other modules read this same JSON file; machine-specific
paths and prototype thresholds are therefore not embedded in analysis code.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from _shared import deep_merge, dump_json, load_json, resolve_path


DEFAULT_CONFIG: dict[str, Any] = {
    "paths": {
        "data_root": ".",
        "raw_records": "DATA/school_data.xlsx",
        "class_population": "DATA/class_population_base.xlsx",
        "school_calendar": "",
        "output_dir": "OUTPUT_DELIVERY",
        "reference_events": "",
    },
    "columns": {
        "student_id": "ID",
        "report_date": "上报日期",
        "onset_date": "出现症状日期",
        "session": "晨午检时段",
        "is_new": "新发",
        "symptom_text": "症状表现",
        "absence": "缺课",
        "absence_type": "缺课类型",
        "visit": "就诊",
        "diagnosis": "疾病",
        "death": "死亡",
        "school_name": "学校",
        "grade": "年级",
        "class_name": "班级",
    },
    "episode": {
        "gap_days": 7,
        "sensitivity_gap_days": [5, 10],
        "include_if_illness_absence_or_symptomatic": True,
    },
    "syndromes": {
        "primary": "fever_ari",
        "windows": [1, 3, 5, 7],
    },
    "baseline": {
        "training_end": "",
        "min_history_teaching_days": 60,
        "min_total_primary_cases": 100,
        "spline_df": 5,
        "class_effect_prior": 20.0,
        "outlier_quantile": 0.99,
        "quantiles": [0.95, 0.975, 0.99, 0.995],
        "minimum_mean": 1e-6,
    },
    "detectors": {
        "a_min_medium_cases": 2,
        "a_min_strong_cases": 3,
        "a_strong_oe_ratio": 2.0,
        "b_windows": [1, 3, 5],
        "b_fdr_alpha": 0.05,
        "b_min_cases": 2,
        "ewma_lambdas": [0.2, 0.3, 0.4],
        "cusum_k": [0.25, 0.5],
        "sequential_calibration_quantile": 0.99,
        "sequential_min_consecutive": 2,
    },
    "events": {
        "merge_gap_teaching_days": 3,
        "merge_same_grade": True,
        "close_after_no_new_teaching_days": 3,
    },
    "progression": {
        "horizon_teaching_days": 3,
        "min_events_for_model": 50,
        "min_positive_events": 15,
        "random_seed": 20260811,
    },
    "grading": {
        "downgrade_confirm_updates": 2,
        "close_after_no_new_teaching_days": 3,
    },
    "evaluation": {
        "event_overlap_days": 3,
        "minimum_class_jaccard": 0.0,
    },
}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    config_path = Path(path).resolve() if path else None
    if config_path:
        config = deep_merge(config, load_json(config_path))
        config["_config_path"] = str(config_path)
        base_dir = config_path.parent
    else:
        base_dir = Path.cwd()

    data_root = resolve_path(base_dir, config["paths"]["data_root"]).resolve()
    config["paths"]["data_root"] = str(data_root)
    for key in ("raw_records", "class_population", "school_calendar", "reference_events"):
        value = config["paths"].get(key, "")
        config["paths"][key] = str(resolve_path(data_root, value).resolve()) if value else ""
    config["paths"]["output_dir"] = str(
        resolve_path(data_root, config["paths"]["output_dir"]).resolve()
    )
    return config


def write_example(path: Path, overrides: Mapping[str, Any] | None = None) -> None:
    config = deep_merge(DEFAULT_CONFIG, overrides or {})
    dump_json(config, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-example", type=Path, required=True)
    parser.add_argument("--data-root", default=".")
    args = parser.parse_args()
    write_example(args.write_example, {"paths": {"data_root": args.data_root}})
    print(f"配置模板已写入: {args.write_example.resolve()}")


if __name__ == "__main__":
    main()

