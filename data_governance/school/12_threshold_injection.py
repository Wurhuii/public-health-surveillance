"""Create semi-synthetic events and screen baseline-threshold candidates."""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from _shared import configure_logging, load_pipeline_config, safe_divide, write_excel


SCENARIOS = {
    "micro_cluster": [1, 1],
    "rapid_cluster": [4],
    "slow_growth": [1, 1, 1, 1, 1],
}


def inject_scenarios(
    baseline: pd.DataFrame, seed: int, repetitions: int = 10
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    data = baseline.copy().sort_values(["class_id", "date"]).reset_index(drop=True)
    data["O_background"] = data["O"]
    data["injected_cases"] = 0
    data["injection_id"] = ""
    manifest: list[dict[str, Any]] = []
    class_groups = {class_id: group.index.to_numpy() for class_id, group in data.groupby("class_id")}
    eligible_classes = [class_id for class_id, indices in class_groups.items() if len(indices) >= 10]
    counter = 0
    for scenario, pattern in SCENARIOS.items():
        for _ in range(repetitions):
            class_id = str(rng.choice(eligible_classes))
            indices = class_groups[class_id]
            start_position = int(rng.integers(2, len(indices) - len(pattern)))
            selected = indices[start_position:start_position + len(pattern)]
            counter += 1
            injection_id = f"INJ_{counter:04d}_{scenario}"
            for row_index, added in zip(selected, pattern):
                data.loc[row_index, "injected_cases"] += int(added)
                data.loc[row_index, "injection_id"] = injection_id
            manifest.append(
                {
                    "injection_id": injection_id,
                    "scenario": scenario,
                    "school_code": data.loc[selected[0], "school_code"],
                    "class_id": class_id,
                    "start_date": data.loc[selected[0], "date"],
                    "end_date": data.loc[selected[-1], "date"],
                    "added_cases": int(sum(pattern)),
                }
            )
    data["O_injected"] = data["O_background"] + data["injected_cases"]
    return data, pd.DataFrame(manifest)


def evaluate_grid(injected: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    background_mask = injected["injection_id"].eq("")
    for minimum_cases, quantile, minimum_oe in itertools.product([2, 3, 4, 5, 6], [95, 975, 99, 995], [2, 3, 4, 5]):
        threshold_column = f"PI{quantile}"
        signal = (
            injected["O_injected"].ge(minimum_cases)
            & injected["O_injected"].gt(injected[threshold_column])
            & (safe_divide(injected["O_injected"], injected["E"]) >= minimum_oe)
        )
        detected_ids = set(injected.loc[signal & injected["injection_id"].ne(""), "injection_id"])
        rows.append(
            {
                "minimum_cases": minimum_cases,
                "prediction_limit": quantile,
                "minimum_oe": minimum_oe,
                "injection_sensitivity": len(detected_ids) / max(len(manifest), 1),
                "false_signals_per_1000_class_days": float(signal[background_mask].mean() * 1000),
                "detected_injections": len(detected_ids),
                "total_injections": len(manifest),
            }
        )
    return pd.DataFrame(rows).sort_values(["false_signals_per_1000_class_days", "injection_sensitivity"], ascending=[True, False])


def run(config_path: str | Path) -> Path:
    config = load_pipeline_config(config_path)
    output_dir = Path(config["paths"]["output_dir"])
    baseline = pd.read_excel(output_dir / "06_baseline_predictions.xlsx", sheet_name="predictions", parse_dates=["date"])
    injected, manifest = inject_scenarios(baseline, int(config["progression"]["random_seed"]))
    grid = evaluate_grid(injected, manifest)
    note = pd.DataFrame(
        [{"status": "prototype_screen", "note": "本表仅筛选动态基线A参数；正式阈值需把注入数据重新通过A/B/C、事件合并和状态机，并在固定报警负担下比较。"}]
    )
    output = output_dir / "12_threshold_injection.xlsx"
    write_excel(output, {"injected_class_days": injected, "scenario_manifest": manifest, "threshold_grid": grid, "method_note": note})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    print(f"半合成注入与阈值网格已保存: {run(args.config)}")


if __name__ == "__main__":
    main()
