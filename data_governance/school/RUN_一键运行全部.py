"""学校监测预警模型的一键运行入口。

使用方式：在 PyCharm、VS Code 等 IDE 中打开本文件，点击 Run，或在文件上
右键选择“运行”。不需要在 CMD/PowerShell 中输入命令。
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any


# ------------------------ 常用运行设置（可直接修改） ------------------------
CONFIG_FILENAME = "config.json"
START_AT = 1          # 1 表示从数据导入审计开始
STOP_AFTER = 16       # 16 表示运行至图形输出
VERBOSE = True        # True 显示各模块详细日志
DRY_RUN = False       # True 只核对顺序，不运行、不生成结果
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_pipeline import run_pipeline  # noqa: E402


class UserCancelled(RuntimeError):
    """用户主动取消首次配置。"""


def build_config(
    raw_records: str | Path,
    class_population: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """基于交付模板构建使用绝对路径的运行配置。"""

    template_path = ROOT / "config.example.json"
    if not template_path.is_file():
        raise FileNotFoundError(f"找不到配置模板：{template_path}")
    config = json.loads(template_path.read_text(encoding="utf-8"))
    config.setdefault("paths", {})
    config["paths"].update(
        {
            "data_root": str(ROOT),
            "raw_records": str(Path(raw_records).expanduser().resolve()),
            "class_population": str(Path(class_population).expanduser().resolve()),
            "output_dir": str(Path(output_dir).expanduser().resolve()),
        }
    )
    return config


def create_config_with_dialog(config_path: Path) -> Path:
    """首次运行时用系统文件选择窗口生成 config.json。"""

    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError as exc:
        raise RuntimeError(
            "当前 Python 缺少 tkinter，无法打开文件选择窗口。"
            "请复制 config.example.json 为 config.json 并填写数据路径。"
        ) from exc

    window = tk.Tk()
    window.withdraw()
    try:
        messagebox.showinfo(
            "首次运行配置",
            "请选择两个输入文件。程序会在代码目录生成 config.json，"
            "以后点击 Run 将直接使用该配置。",
            parent=window,
        )
        raw_records = filedialog.askopenfilename(
            title="请选择学生晨午检、缺勤和就诊原始记录",
            filetypes=[("表格文件", "*.xlsx *.xls *.csv"), ("所有文件", "*.*")],
            parent=window,
        )
        if not raw_records:
            raise UserCancelled("已取消选择原始记录，未运行模型。")

        class_population = filedialog.askopenfilename(
            title="请选择完整班级人口表",
            filetypes=[("表格文件", "*.xlsx *.xls *.csv"), ("所有文件", "*.*")],
            parent=window,
        )
        if not class_population:
            raise UserCancelled("已取消选择班级人口表，未运行模型。")

        output_dir = ROOT / "OUTPUT_DELIVERY"
        config = build_config(raw_records, class_population, output_dir)
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        messagebox.showinfo(
            "配置已生成",
            f"已生成：{config_path}\n\n分析结果将输出到：{output_dir}\n现在开始运行全部模块。",
            parent=window,
        )
        return config_path
    finally:
        window.destroy()


def validate_config_inputs(config_path: Path) -> Path:
    """在启动16个模块前发现常见路径填写错误。"""

    data = json.loads(config_path.read_text(encoding="utf-8"))
    paths = data.get("paths", {})
    data_root = Path(paths.get("data_root", config_path.parent)).expanduser()
    if not data_root.is_absolute():
        data_root = config_path.parent / data_root

    missing: list[str] = []
    for key, label in (
        ("raw_records", "学生原始记录"),
        ("class_population", "班级人口表"),
    ):
        value = paths.get(key, "")
        candidate = Path(value).expanduser() if value else Path()
        if value and not candidate.is_absolute():
            candidate = data_root / candidate
        if not value or not candidate.resolve().is_file():
            missing.append(f"{label}：{candidate if value else '未填写'}")
    if missing:
        raise FileNotFoundError(
            "config.json 中以下输入无效：\n- " + "\n- ".join(missing)
            + "\n请修改 config.json；也可以删除该文件后重新运行本入口并再次选择。"
        )
    return config_path


def show_error(message: str) -> None:
    """尽可能通过弹窗提示错误；无图形环境时保留控制台输出。"""

    try:
        import tkinter as tk
        from tkinter import messagebox

        window = tk.Tk()
        window.withdraw()
        try:
            messagebox.showerror("模型运行失败", message, parent=window)
        finally:
            window.destroy()
    except Exception:
        pass


def main() -> int:
    config_path = ROOT / CONFIG_FILENAME
    try:
        if not config_path.is_file():
            config_path = create_config_with_dialog(config_path)
        validate_config_inputs(config_path)
        commands = run_pipeline(
            config_path,
            start_at=START_AT,
            stop_after=STOP_AFTER,
            verbose=VERBOSE,
            dry_run=DRY_RUN,
        )
        print("\n一键运行结束。", flush=True)
        print(f"配置文件：{config_path}", flush=True)
        print(f"共处理模块：{len(commands)}", flush=True)
        return 0
    except UserCancelled as exc:
        print(str(exc), flush=True)
        return 1
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        print("\n模型运行失败：" + message, file=sys.stderr, flush=True)
        traceback.print_exc()
        show_error(message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
