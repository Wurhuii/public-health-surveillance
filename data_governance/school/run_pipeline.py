"""按固定顺序运行学校监测预警模型的 01—16 模块。

既可在 IDE 中直接 Run/右键运行，也保留命令行参数用于自动化任务。
直接运行时默认读取本文件同目录下的 ``config.json``。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence


MODULES: tuple[str, ...] = (
    "01_import_audit.py",
    "02_clean_records.py",
    "03_build_episode.py",
    "04_define_syndromes.py",
    "05_build_realtime_tables.py",
    "06_fit_baseline.py",
    "07_cluster_concentration.py",
    "08_sequential_detection.py",
    "09_merge_events.py",
    "10_progression_model.py",
    "11_dynamic_grading.py",
    "12_threshold_injection.py",
    "13_freeze_model.py",
    "14_reference_evaluation.py",
    "15_generate_report.py",
    "16_generate_figures.py",
)


def run_pipeline(
    config_path: str | Path,
    *,
    start_at: int = 1,
    stop_after: int = 16,
    verbose: bool = False,
    dry_run: bool = False,
    python_executable: str | Path | None = None,
    root: str | Path | None = None,
) -> list[list[str]]:
    """依次执行指定范围的模块，并返回实际构造的命令列表。

    每个模块使用独立 Python 子进程运行，某一模块失败时立即停止，避免后续
    模块继续读取不完整的上游结果。``dry_run=True`` 仅检查配置和模块文件并
    打印执行顺序，不会运行模型。
    """

    module_root = Path(root).resolve() if root else Path(__file__).resolve().parent
    config = Path(config_path).expanduser().resolve()
    executable = str(Path(python_executable).resolve()) if python_executable else sys.executable

    if not 1 <= start_at <= len(MODULES):
        raise ValueError(f"start_at 必须在 1—{len(MODULES)} 之间，当前为 {start_at}")
    if not 1 <= stop_after <= len(MODULES):
        raise ValueError(f"stop_after 必须在 1—{len(MODULES)} 之间，当前为 {stop_after}")
    if start_at > stop_after:
        raise ValueError("start_at 不能大于 stop_after")
    if not config.is_file():
        raise FileNotFoundError(
            f"找不到配置文件：{config}\n"
            "建议直接运行 RUN_一键运行全部.py，由程序首次生成 config.json。"
        )

    missing = [name for name in MODULES if not (module_root / name).is_file()]
    if missing:
        raise FileNotFoundError("代码包缺少模块：" + "、".join(missing))

    selected = [
        (index, name)
        for index, name in enumerate(MODULES, start=1)
        if start_at <= index <= stop_after
    ]
    commands: list[list[str]] = []
    mode = "检查执行顺序" if dry_run else "开始运行"
    print("=" * 72, flush=True)
    print(f"学校监测预警模型：{mode}", flush=True)
    print(f"配置文件：{config}", flush=True)
    print(f"模块范围：{start_at:02d}—{stop_after:02d}（共 {len(selected)} 个）", flush=True)
    print("=" * 72, flush=True)

    for index, script_name in selected:
        command = [executable, str(module_root / script_name), "--config", str(config)]
        if verbose:
            command.append("--verbose")
        commands.append(command)
        prefix = "[DRY-RUN]" if dry_run else f"[{index:02d}/{len(MODULES):02d}]"
        print(f"{prefix} {script_name}", flush=True)
        if dry_run:
            continue
        try:
            subprocess.run(command, cwd=module_root, check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"模块 {index:02d}（{script_name}）运行失败，退出码为 {exc.returncode}。"
            ) from exc

    if dry_run:
        print("执行顺序检查完成；未运行模型、未写入分析结果。", flush=True)
    else:
        print("全部指定模块运行完成。", flush=True)
    return commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("config.json")),
        help="配置文件路径；默认读取代码目录中的 config.json",
    )
    parser.add_argument("--start-at", type=int, default=1, choices=range(1, 17))
    parser.add_argument("--stop-after", type=int, default=16, choices=range(1, 17))
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="只检查执行顺序，不运行模块")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        run_pipeline(
            args.config,
            start_at=args.start_at,
            stop_after=args.stop_after,
            verbose=args.verbose,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"运行失败：{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
