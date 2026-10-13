"""Create a cryptographic model/version manifest after calibration."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from _shared import configure_logging, dump_json, load_pipeline_config, sha256_file


def build_manifest(config_path: str | Path, force_prototype_freeze: bool = False) -> tuple[Path, dict[str, Any]]:
    config = load_pipeline_config(config_path)
    output_dir = Path(config["paths"]["output_dir"])
    diagnostics = pd.read_excel(output_dir / "06_baseline_predictions.xlsx", sheet_name="diagnostics").iloc[0].to_dict()
    prototype_only = int(diagnostics.get("prototype_only", 1)) == 1
    status = "FROZEN_MODEL_1_0" if (not prototype_only or force_prototype_freeze) else "NOT_FROZEN_PROTOTYPE"
    code_dir = Path(__file__).parent
    tracked_files = sorted(code_dir.glob("*.py")) + [Path(config_path)]
    output_artifacts = [
        output_dir / "06_baseline_model.joblib",
        output_dir / "08_sequential_detection.xlsx",
        output_dir / "10_progression_model.joblib",
        output_dir / "12_threshold_injection.xlsx",
    ]
    tracked_files.extend(path for path in output_artifacts if path.exists())
    manifest = {
        "status": status,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "prototype_only": prototype_only,
        "warning": "当前数据不足以冻结生产模型；本清单仅用于原型追溯。" if status == "NOT_FROZEN_PROTOTYPE" else "",
        "diagnostics": diagnostics,
        "files": [
            {"path": str(path.resolve()), "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in tracked_files
            if path.exists()
        ],
    }
    output = output_dir / "13_model_freeze_manifest.json"
    dump_json(manifest, output)
    return output, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--force-prototype-freeze", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    output, manifest = build_manifest(args.config, args.force_prototype_freeze)
    print(f"模型版本清单已保存: {output} | status={manifest['status']}")


if __name__ == "__main__":
    main()

