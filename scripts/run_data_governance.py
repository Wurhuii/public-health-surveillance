"""Run the bundled governance packages and publish adapter-ready demo datasets.

The school package is executed as its original 01-16 pipeline.  The care-home
sample needs a portable bridge because the delivered research scripts contain
developer-machine paths and the example clinical dates/person keys are masked.
The bridge keeps that limitation explicit in the generated audit manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
GOV_ROOT = ROOT / "data_governance"
SAMPLES = GOV_ROOT / "sample_data"
PUBLISHED = GOV_ROOT / "published_samples"
OUTPUT = GOV_ROOT / "output"
SCHOOL_PACKAGE = GOV_ROOT / "school"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def first_workbook_with(required: set[str], folder: Path) -> tuple[Path, pd.DataFrame]:
    for path in sorted(folder.glob("*.xlsx")):
        frame = pd.read_excel(path, dtype=str)
        if required.issubset(set(frame.columns)):
            return path, frame
    raise FileNotFoundError(f"{folder} 中找不到包含字段 {sorted(required)} 的工作簿")


def run_school(full_model: bool = True) -> dict[str, Any]:
    output_dir = OUTPUT / "school_model"
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = OUTPUT / "school_pipeline_config.json"
    config = {
        "paths": {
            "data_root": str(ROOT),
            "raw_records": str((SAMPLES / "school" / "school_data.xlsx").resolve()),
            "class_population": str((SAMPLES / "school" / "class_population_base.xlsx").resolve()),
            "school_calendar": "",
            "output_dir": str(output_dir.resolve()),
            "reference_events": "",
        },
        "baseline": {
            "training_end": "",
            "min_history_teaching_days": 60,
            "min_total_primary_cases": 100,
        },
    }
    write_json(config_path, config)
    stop_after = "16" if full_model else "5"
    if full_model:
        check = subprocess.run(
            [
                sys.executable,
                "-c",
                "import numpy,pandas,scipy,statsmodels.api,sklearn,openpyxl,matplotlib,joblib",
            ],
            cwd=SCHOOL_PACKAGE,
        )
        if check.returncode:
            raise RuntimeError(
                "学校完整模型依赖不兼容。请先执行 "
                "python -m pip install -r requirements.txt；"
                "项目已固定 scipy==1.13.1 与 statsmodels==0.14.4。"
            )
    subprocess.run(
        [
            sys.executable,
            str(SCHOOL_PACKAGE / "run_pipeline.py"),
            "--config",
            str(config_path),
            "--stop-after",
            stop_after,
        ],
        cwd=SCHOOL_PACKAGE,
        check=True,
    )

    episodes_path = output_dir / "04_syndromic_episodes.xlsx"
    episodes = pd.read_excel(episodes_path, sheet_name="episodes", dtype=str)
    populations = pd.read_excel(SAMPLES / "school" / "class_population_base.xlsx", dtype=str)
    population_map = populations.set_index("class_id")["population"].to_dict()
    flags = episodes.get("broad_ari", pd.Series("0", index=episodes.index)).astype(str)
    governed = episodes.loc[flags.isin({"1", "1.0", "True", "true"})].copy()
    if governed.empty:
        governed = episodes.loc[
            episodes.get("fever_ari", pd.Series("0", index=episodes.index)).astype(str).isin({"1", "1.0"})
        ].copy()
    school_names = {code: f"示例学校 {code}" for code in governed["school_code"].dropna().unique()}
    out = pd.DataFrame(
        {
            "记录ID": governed["episode_id"],
            "学校名称": governed["school_code"].map(school_names),
            "学校编码": governed["school_code"],
            "省": "示例省",
            "城市": "示例市",
            "区县": governed["school_code"].map(lambda x: f"示例区-{x}"),
            "日期": pd.to_datetime(governed["onset_date"], errors="coerce").dt.strftime("%Y-%m-%d"),
            "症状": governed["symptom_text_combined"].fillna("急性呼吸道症状"),
            "班级": governed["grade"].fillna("") + "年级" + governed["class_number"].fillna("") + "班",
            "班级编码": governed["class_id"],
            "在册人数": governed["class_id"].map(population_map),
            "数据更新时间": pd.to_datetime(governed["first_report_date"], errors="coerce").dt.strftime("%Y-%m-%d 16:00:00"),
            "是否休假日": "否",
            "教学日类型": "正常教学日",
            "是否补录": "否",
        }
    ).dropna(subset=["日期", "学校编码", "班级编码"])
    output_file = OUTPUT / "school_governed.csv"
    out.to_csv(output_file, index=False, encoding="utf-8-sig")
    return {
        "package": "school_00_16",
        "modules_completed": int(stop_after),
        "raw_rows": len(episodes),
        "published_rows": len(out),
        "output": str(output_file.relative_to(ROOT)),
        "prototype_only": True,
    }


def parse_icd(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"J\s*([0-9]{2})", text)
    return f"J{match.group(1)}" if match else ""


def run_care_home() -> dict[str, Any]:
    folder = SAMPLES / "care_home"
    base_path, residents = first_workbook_with({"id", "org_code", "admit_time"}, folder)
    diagnosis_frames: list[pd.DataFrame] = []
    source_files: list[str] = []
    for path in sorted(folder.glob("*.xlsx")):
        frame = pd.read_excel(path, dtype=str)
        if {"jbzdbm", "zhenduanriqi"}.issubset(frame.columns):
            frame = frame.copy()
            frame["_source_file"] = path.name
            diagnosis_frames.append(frame)
            source_files.append(path.name)
    if not diagnosis_frames:
        raise FileNotFoundError("养老机构样例包中未找到诊断表")
    diagnoses = pd.concat(diagnosis_frames, ignore_index=True)
    diagnoses["_icd_group"] = diagnoses["jbzdbm"].map(parse_icd)
    respiratory = diagnoses.loc[diagnoses["_icd_group"].str.startswith("J")].copy()
    if respiratory.empty:
        raise ValueError("养老机构样例包中没有可识别的呼吸道诊断")

    valid_residents = residents.dropna(subset=["org_code"]).copy().reset_index(drop=True)
    valid_residents["org_code"] = valid_residents["org_code"].astype(str).str.strip()
    valid_residents = valid_residents.loc[valid_residents["org_code"] != ""]
    counts = valid_residents.groupby("org_code")["id"].nunique().to_dict()
    start = datetime(2026, 10, 3)
    rows: list[dict[str, Any]] = []
    id_col = next((c for c in respiratory.columns if "local_id" in c.lower()), "")
    visit_col = next((c for c in ("menzhenliushuihao", "zhuyuanliushuihao") if c in respiratory.columns), "")
    for index, record in respiratory.reset_index(drop=True).iterrows():
        raw_person = str(record.get(id_col, "") or f"row-{index}")
        digest = hashlib.sha256(f"care-home-demo:{raw_person}".encode("utf-8")).hexdigest()
        resident = valid_residents.iloc[int(digest[:8], 16) % len(valid_residents)]
        event_date = start + timedelta(days=index % 7)
        org_code = str(resident["org_code"])
        rows.append(
            {
                "老人信息Id": f"DEMO-{digest[:16]}",
                "住院号": str(record.get(visit_col, "") or f"VISIT-{index:05d}"),
                "机构编码": org_code,
                "机构名称": f"示例养老机构 {org_code}",
                "省": "示例省",
                "城市": "示例市",
                "区县": f"示例区-{org_code[-2:]}",
                "入院时间": event_date.strftime("%Y-%m-%d"),
                "入院诊断": f"呼吸道疾病（{record['_icd_group']}）",
                "诊断名称": str(record.get("jbzdmc", "") or record["_icd_group"]),
                "状态": "在院",
                "数据更新时间": (event_date + timedelta(hours=17)).strftime("%Y-%m-%d %H:%M:%S"),
                "在住人数": counts.get(org_code, 0),
                "人员脱敏键": f"SIM-{digest}",
                "事件类型": "诊断事件",
                "病原体名称": "未明确",
                "病原检测结果": "未提供",
                "机构地址": "示例地址（非真实地点）",
                "模拟人员关联": "是",
                "模拟事件日期": "是",
                "原始来源文件": record["_source_file"],
            }
        )
    out = pd.DataFrame(rows)
    output_file = OUTPUT / "care_home_governed.csv"
    out.to_csv(output_file, index=False, encoding="utf-8-sig")
    return {
        "package": "care_home_01_17_portable_bridge",
        "base_file": base_path.name,
        "diagnosis_files": source_files,
        "resident_rows": len(residents),
        "respiratory_events": len(out),
        "facilities": out["机构编码"].nunique(),
        "output": str(output_file.relative_to(ROOT)),
        "simulated_fields": ["人员与养老机构关联", "事件日期"],
        "production_blocker": "正式接入前必须提供跨来源一致的不可逆人员键和可排序到日的真实或一致平移日期。",
    }


def stage_published_samples(reason: str) -> dict[str, Any]:
    """Publish the repository-safe, de-identified sample outputs.

    Raw workbooks are deliberately kept outside Git because their filenames and
    schemas may contain institution or person-level information.  These CSVs
    were derived from the delivered packages, with demo identities, locations
    and dates substituted before publication.
    """
    outputs: dict[str, str] = {}
    for name in ("school_governed.csv", "care_home_governed.csv"):
        source = PUBLISHED / name
        if not source.exists():
            raise FileNotFoundError(f"缺少仓库内置的脱敏验证数据: {source}")
        target = OUTPUT / name
        shutil.copy2(source, target)
        outputs[name] = str(target.relative_to(ROOT))
    return {
        "mode": "published_deidentified_samples",
        "reason": reason,
        "outputs": outputs,
        "raw_workbooks_used": False,
        "yichang_focus_imported": False,
    }


def main() -> int:
    global SAMPLES
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="学校包只运行到模块05，用于快速开发验证")
    parser.add_argument(
        "--input-root",
        type=Path,
        default=None,
        help="私有原始数据根目录；也可设置 GOVERNANCE_INPUT_ROOT",
    )
    parser.add_argument(
        "--require-raw",
        action="store_true",
        help="原始工作簿不完整时直接报错，不回退到仓库内置脱敏验证数据",
    )
    args = parser.parse_args()
    configured_root = args.input_root or (
        Path(value) if (value := os.environ.get("GOVERNANCE_INPUT_ROOT")) else None
    )
    if configured_root is not None:
        SAMPLES = configured_root.expanduser().resolve()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    started = datetime.now()

    required_school = [SAMPLES / "school" / "school_data.xlsx", SAMPLES / "school" / "class_population_base.xlsx"]
    care_home_dir = SAMPLES / "care_home"
    raw_ready = all(path.is_file() for path in required_school) and care_home_dir.is_dir() and any(care_home_dir.glob("*.xlsx"))
    if not raw_ready:
        message = f"原始治理输入不完整: {SAMPLES}"
        if args.require_raw:
            raise FileNotFoundError(message)
        print(f"[governance] {message}，使用仓库内置脱敏验证数据。", flush=True)
        staged = stage_published_samples(message)
        manifest = {
            "started_at": started.isoformat(timespec="seconds"),
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            **staged,
        }
        write_json(OUTPUT / "governance_manifest.json", manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
        return 0

    print("[governance] 运行学校数据治理包……", flush=True)
    school = run_school(full_model=not args.fast)
    print("[governance] 运行养老机构可移植治理桥……", flush=True)
    care_home = run_care_home()
    manifest = {
        "started_at": started.isoformat(timespec="seconds"),
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "input_mode": "private_raw_workbooks",
        "input_root": str(SAMPLES),
        "yichang_focus_imported": False,
        "school": school,
        "care_home": care_home,
    }
    write_json(OUTPUT / "governance_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
