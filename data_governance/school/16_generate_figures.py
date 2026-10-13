"""Generate decision-oriented PNG figures from the pipeline result tables.

The figures are presentation outputs only.  They do not change detector
thresholds, event definitions, warning grades, or any upstream model result.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from _shared import configure_logging, load_pipeline_config


COLORS = {
    "navy": "#17365D",
    "blue": "#2E75B6",
    "cyan": "#00A6A6",
    "gold": "#D89B00",
    "orange": "#ED7D31",
    "red": "#C00000",
    "gray": "#7F8C8D",
    "light_gray": "#E9EEF3",
    "green": "#548235",
}

LEVEL_ORDER = ["green", "blue", "yellow", "orange", "red"]
LEVEL_LABELS = {
    "green": "绿色",
    "blue": "蓝色",
    "yellow": "黄色",
    "orange": "橙色",
    "red": "红色",
}
LEVEL_COLORS = {
    "green": "#70AD47",
    "blue": "#5B9BD5",
    "yellow": "#FFD966",
    "orange": "#ED7D31",
    "red": "#C00000",
}


def configure_figure_style() -> None:
    """Apply a cross-platform Chinese-capable, print-friendly style."""
    plt.rcParams.update(
        {
            "font.sans-serif": [
                "Microsoft YaHei",
                "SimHei",
                "Noto Sans CJK SC",
                "Arial Unicode MS",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#B7C3D0",
            "axes.labelcolor": "#263746",
            "axes.titlecolor": COLORS["navy"],
            "axes.titleweight": "bold",
            "grid.color": "#DDE4EA",
            "grid.alpha": 0.8,
            "legend.frameon": False,
            "savefig.facecolor": "white",
        }
    )


def read_excel_required(path: Path, sheet_name: str) -> pd.DataFrame:
    """Read one required sheet and raise an actionable error if it is absent."""
    if not path.exists():
        raise FileNotFoundError(f"缺少绘图所需结果文件: {path}")
    try:
        return pd.read_excel(path, sheet_name=sheet_name)
    except ValueError as exc:
        raise ValueError(f"{path.name} 缺少工作表 {sheet_name!r}") from exc


def format_date_axis(ax: plt.Axes) -> None:
    locator = mdates.AutoDateLocator(minticks=4, maxticks=10)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.grid(axis="y")


def add_source_note(fig: plt.Figure, note: str) -> None:
    fig.text(0.01, 0.006, note, ha="left", va="bottom", fontsize=7.5, color=COLORS["gray"])


def save_figure(fig: plt.Figure, path: Path, note: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    add_source_note(fig, note)
    fig.savefig(path, dpi=180, bbox_inches="tight", pad_inches=0.16)
    plt.close(fig)


def draw_empty(ax: plt.Axes, title: str, message: str) -> None:
    ax.set_title(title, loc="left")
    ax.text(
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        transform=ax.transAxes,
        fontsize=12,
        color=COLORS["gray"],
    )
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def plot_realtime_summary(frame: pd.DataFrame, path: Path) -> str:
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values("date")

    fig, axes = plt.subplots(2, 1, figsize=(11.5, 7.2), sharex=True)
    fig.suptitle("学校急性呼吸道症候群实时趋势", fontsize=16, fontweight="bold", color=COLORS["navy"])

    axes[0].bar(data["date"], data["new_known_primary"], color=COLORS["blue"], alpha=0.8, label="当日首次已知主症候群")
    axes[0].plot(data["date"], data["known_onset_3d"], color=COLORS["orange"], marker="o", ms=3.5, lw=2, label="已知发病3日窗")
    axes[0].set_ylabel("episode 数")
    axes[0].set_title("病例信号", loc="left")
    axes[0].legend(loc="upper left", ncol=2)

    axes[1].plot(data["date"], data["affected_classes"], color=COLORS["cyan"], marker="o", ms=3.5, lw=2, label="受影响班级")
    axes[1].plot(data["date"], data["afternoon_new"], color=COLORS["gold"], lw=1.8, label="午检新增")
    axes[1].set_ylabel("班级/episode 数")
    axes[1].set_title("空间扩展与午检新增", loc="left")
    axes[1].legend(loc="upper left", ncol=2)
    format_date_axis(axes[1])

    fig.subplots_adjust(top=0.88, bottom=0.12, hspace=0.30)
    save_figure(fig, path, "来源：05-1_realtime_summary.xlsx；仅描述当前数据，不代表已确认暴发。")
    return "展示当日新识别主症候群、3日发病窗、受影响班级和午检新增的时间趋势。"


def plot_baseline_fit(frame: pd.DataFrame, path: Path) -> str:
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["above_pi95"] = pd.to_numeric(data["O"], errors="coerce").gt(pd.to_numeric(data["PI95"], errors="coerce"))
    daily = data.groupby("date", as_index=False).agg(
        observed=("O", "sum"),
        expected=("E", "sum"),
        above_pi95=("above_pi95", "sum"),
        a_signal=("A_strength", lambda values: pd.to_numeric(values, errors="coerce").ge(1).sum()),
    )
    daily = daily.sort_values("date")
    date_values = mdates.date2num(daily["date"].dt.to_pydatetime())

    fig, axes = plt.subplots(2, 1, figsize=(11.5, 7.2), sharex=True)
    fig.suptitle("观察值与动态基线", fontsize=16, fontweight="bold", color=COLORS["navy"])
    axes[0].plot(date_values, daily["observed"].to_numpy(), color=COLORS["blue"], marker="o", ms=3.5, lw=2.2, label="观察值 O")
    axes[0].plot(date_values, daily["expected"].to_numpy(), color=COLORS["orange"], lw=2.2, label="期望值 E")
    axes[0].fill_between(date_values, daily["expected"].to_numpy(), color=COLORS["orange"], alpha=0.10)
    axes[0].set_ylabel("班级日病例合计")
    axes[0].set_title("主症候群观察值与模型期望值", loc="left")
    axes[0].legend(loc="upper left", ncol=2)
    axes[0].grid(axis="y")

    width = 0.65
    axes[1].bar(date_values, daily["above_pi95"].to_numpy(), width=width, color=COLORS["red"], alpha=0.75, label="超过班级PI95")
    axes[1].plot(date_values, daily["a_signal"].to_numpy(), color=COLORS["gold"], marker="o", ms=3.5, lw=1.8, label="A探测器候选班级")
    axes[1].set_ylabel("班级数")
    axes[1].set_title("班级级超限数量", loc="left")
    axes[1].legend(loc="upper left", ncol=2)
    axes[1].set_xlim(date_values.min() - 1, date_values.max() + 1)
    format_date_axis(axes[1])

    fig.subplots_adjust(top=0.88, bottom=0.12, hspace=0.30)
    save_figure(fig, path, "来源：06_baseline_predictions.xlsx；总期望值为班级期望值之和，PI95按班级逐项判断。")
    return "比较每日观察值与负二项动态基线，并显示班级级预测上限超限数量。"


def plot_detector_timeline(frame: pd.DataFrame, path: Path) -> str:
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    columns = ["A_candidate", "B_any_candidate", "C_any_candidate", "event_trigger"]
    daily = data.groupby("date", as_index=False)[columns].sum().sort_values("date")

    fig, ax = plt.subplots(figsize=(11.5, 5.6))
    ax.plot(daily["date"], daily["A_candidate"], color=COLORS["blue"], marker="o", ms=3.5, lw=1.9, label="A：动态基线")
    ax.plot(daily["date"], daily["B_any_candidate"], color=COLORS["cyan"], marker="o", ms=3.5, lw=1.9, label="B：空间集中")
    ax.plot(daily["date"], daily["C_any_candidate"], color=COLORS["gold"], marker="o", ms=3.5, lw=1.9, label="C：连续增长")
    ax.scatter(daily["date"], daily["event_trigger"], color=COLORS["red"], s=34, zorder=4, label="融合触发")
    ax.set_title("三个核心探测器及融合触发时间序列", loc="left", fontsize=15)
    ax.set_ylabel("候选班级数")
    ax.legend(loc="upper left", ncol=4)
    format_date_axis(ax)
    fig.subplots_adjust(bottom=0.15)
    save_figure(fig, path, "来源：09_candidate_events.xlsx / class_daily_signals；A/B/C 数量可在同一班级日重叠。")
    return "按日期展示动态基线、空间集中、连续增长三个探测器及最终融合触发数量。"


def plot_school_heatmap(frame: pd.DataFrame, path: Path) -> str:
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["any_signal"] = data[["A_candidate", "B_any_candidate", "C_any_candidate"]].max(axis=1).astype(int)
    daily = data.groupby(["school_code", "date"], as_index=False)["any_signal"].sum()
    heat = daily.pivot(index="school_code", columns="date", values="any_signal").fillna(0).sort_index()

    fig, ax = plt.subplots(figsize=(12.0, max(4.8, 0.42 * len(heat.index) + 2.2)))
    image = ax.imshow(heat.to_numpy(), aspect="auto", cmap="YlOrRd", interpolation="nearest", vmin=0)
    ax.set_title("各校异常班级数热图（至少一个探测器）", loc="left", fontsize=15)
    ax.set_yticks(np.arange(len(heat.index)), labels=heat.index)
    if heat.shape[1] > 0:
        step = max(1, int(np.ceil(heat.shape[1] / 10)))
        positions = np.arange(0, heat.shape[1], step)
        labels = [pd.Timestamp(heat.columns[index]).strftime("%m-%d") for index in positions]
        ax.set_xticks(positions, labels=labels, rotation=45, ha="right")
    ax.set_xlabel("监测日期")
    ax.set_ylabel("学校")
    colorbar = fig.colorbar(image, ax=ax, pad=0.015)
    colorbar.set_label("异常班级数")
    fig.subplots_adjust(bottom=0.18)
    save_figure(fig, path, "来源：09_candidate_events.xlsx / class_daily_signals；热度表示当日至少一个探测器候选的班级数量。")
    return "以学校×日期热图定位异常班级在空间和时间上的聚集。"


def plot_event_lifecycle(frame: pd.DataFrame, path: Path) -> str:
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    fig, ax = plt.subplots(figsize=(11.5, 5.8))
    if data.empty:
        draw_empty(ax, "候选事件生命周期", "当前没有候选事件")
    else:
        data["level_rank"] = data["final_level"].map({name: rank for rank, name in enumerate(LEVEL_ORDER, start=1)}).fillna(1)
        ranking = (
            data.groupby("cluster_event_id")
            .agg(max_level=("level_rank", "max"), last_date=("date", "max"))
            .sort_values(["max_level", "last_date"], ascending=False)
            .head(8)
            .index
        )
        selected = data[data["cluster_event_id"].isin(ranking)].copy()
        for event_id, group in selected.groupby("cluster_event_id", sort=False):
            group = group.sort_values("date")
            ax.plot(group["date"], group["progression_probability"], lw=1.6, alpha=0.78, label=str(event_id))
            colors = group["final_level"].map(LEVEL_COLORS).fillna(COLORS["gray"])
            ax.scatter(group["date"], group["progression_probability"], c=colors, s=38, edgecolor="white", linewidth=0.5, zorder=4)
        ax.set_title("候选事件生命周期与未来3日进展风险", loc="left", fontsize=15)
        ax.set_ylabel("进展风险（规则代理或模型概率）")
        ax.set_ylim(-0.03, 1.03)
        ax.legend(loc="upper left", fontsize=7.5, ncol=2)
        format_date_axis(ax)
    fig.subplots_adjust(bottom=0.16)
    save_figure(fig, path, "来源：11_dynamic_grading.xlsx / event_daily_grades；点颜色表示当日最终等级。事件不足时风险值来自规则代理。")
    return "展示高优先候选事件的逐日进展风险及预警等级变化。"


def plot_warning_summary(frame: pd.DataFrame, path: Path) -> str:
    data = frame.copy()
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.9))
    fig.suptitle("当前候选事件状态概览", fontsize=16, fontweight="bold", color=COLORS["navy"])
    if data.empty:
        draw_empty(axes[0], "最终预警等级", "当前没有候选事件")
        draw_empty(axes[1], "生命周期状态", "当前没有候选事件")
    else:
        level_counts = data["final_level"].value_counts().reindex(LEVEL_ORDER, fill_value=0)
        labels = [LEVEL_LABELS[level] for level in LEVEL_ORDER]
        bars = axes[0].bar(labels, level_counts.values, color=[LEVEL_COLORS[level] for level in LEVEL_ORDER])
        axes[0].set_title("最终预警等级", loc="left")
        axes[0].set_ylabel("事件数")
        axes[0].grid(axis="y")
        axes[0].bar_label(bars, padding=3, fontsize=9)

        state_order = [state for state in ["active", "recovery", "closed"] if state in set(data["lifecycle_state"])]
        state_counts = data["lifecycle_state"].value_counts().reindex(state_order, fill_value=0)
        state_labels = {"active": "活动", "recovery": "恢复", "closed": "关闭"}
        bars = axes[1].bar(
            [state_labels.get(state, state) for state in state_order],
            state_counts.values,
            color=[COLORS["red"], COLORS["gold"], COLORS["gray"]][: len(state_order)],
        )
        axes[1].set_title("生命周期状态", loc="left")
        axes[1].set_ylabel("事件数")
        axes[1].grid(axis="y")
        axes[1].bar_label(bars, padding=3, fontsize=9)
    fig.subplots_adjust(top=0.82, bottom=0.14, wspace=0.28)
    save_figure(fig, path, "来源：11_dynamic_grading.xlsx / latest_event_status；等级用于核查优先级，不等同于确诊暴发。")
    return "汇总最新候选事件的颜色等级和活动、恢复、关闭状态。"


def plot_threshold_tradeoff(frame: pd.DataFrame, path: Path) -> str:
    data = frame.copy()
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 5.2))
    fig.suptitle("半合成注入阈值筛选（原型）", fontsize=16, fontweight="bold", color=COLORS["navy"])
    if data.empty:
        draw_empty(axes[0], "注入检出灵敏度", "无阈值网格结果")
        draw_empty(axes[1], "灵敏度—错误信号负担", "无阈值网格结果")
    else:
        case_values = sorted(pd.to_numeric(data["minimum_cases"], errors="coerce").dropna().unique())
        limit_values = sorted(pd.to_numeric(data["prediction_limit"], errors="coerce").dropna().unique())
        case_colors = dict(zip(case_values, plt.cm.tab10(np.linspace(0, 0.8, max(len(case_values), 1)))))
        line_styles = ["-", "--", ":", "-."]
        limit_styles = {value: line_styles[index % len(line_styles)] for index, value in enumerate(limit_values)}
        for (minimum_cases, prediction_limit), group in data.groupby(["minimum_cases", "prediction_limit"]):
            group = group.sort_values("minimum_oe")
            axes[0].plot(
                group["minimum_oe"],
                group["injection_sensitivity"],
                marker="o",
                ms=3.8,
                lw=1.5,
                color=case_colors[minimum_cases],
                linestyle=limit_styles[prediction_limit],
                alpha=0.82,
            )
        axes[0].set_title("O/E阈值与注入检出率", loc="left")
        axes[0].set_xlabel("最低 O/E")
        axes[0].set_ylabel("注入检出灵敏度")
        axes[0].set_ylim(-0.03, 1.03)
        axes[0].grid()
        case_handles = [
            Line2D([0], [0], color=case_colors[value], lw=2, label=f"病例≥{int(value)}")
            for value in case_values
        ]
        limit_handles = [
            Line2D([0], [0], color=COLORS["gray"], lw=2, linestyle=limit_styles[value], label=f"PI{value:g}")
            for value in limit_values
        ]
        legend_cases = axes[0].legend(handles=case_handles, title="病例下限", fontsize=7.5, title_fontsize=8, loc="upper left", ncol=2)
        axes[0].add_artist(legend_cases)
        axes[0].legend(handles=limit_handles, title="预测限", fontsize=7.5, title_fontsize=8, loc="upper right", ncol=2)

        performance = (
            data.groupby(["false_signals_per_1000_class_days", "injection_sensitivity"], as_index=False)
            .size()
            .rename(columns={"size": "parameter_combinations"})
        )
        axes[1].scatter(
            performance["false_signals_per_1000_class_days"],
            performance["injection_sensitivity"],
            s=80 + 18 * performance["parameter_combinations"],
            color=COLORS["blue"],
            alpha=0.72,
            edgecolor="white",
            linewidth=0.8,
        )
        for row in performance.itertuples(index=False):
            axes[1].annotate(
                f"n={int(row.parameter_combinations)}",
                (row.false_signals_per_1000_class_days, row.injection_sensitivity),
                xytext=(7, 7),
                textcoords="offset points",
                fontsize=8,
                color=COLORS["navy"],
            )
        axes[1].set_title("灵敏度—错误信号性能点", loc="left")
        axes[1].set_xlabel("每1000班级日错误信号")
        axes[1].set_ylabel("注入检出灵敏度")
        axes[1].set_ylim(-0.03, 1.03)
        axes[1].grid()
        axes[1].text(
            0.02,
            0.96,
            "气泡大小及 n 表示重合的参数组合数",
            transform=axes[1].transAxes,
            va="top",
            fontsize=8.5,
            color=COLORS["gray"],
        )
    fig.subplots_adjust(top=0.82, bottom=0.16, wspace=0.28)
    save_figure(fig, path, "来源：12_threshold_injection.xlsx / threshold_grid；当前仅筛选探测器A，不是正式生产阈值。")
    return "展示探测器A原型阈值的注入检出率与错误信号负担权衡。"


def generate_figures(config_path: str | Path) -> list[Path]:
    """Generate all PNG figures, a CSV manifest, and a Markdown figure index."""
    configure_figure_style()
    config = load_pipeline_config(config_path)
    output_dir = Path(config["paths"]["output_dir"])
    figure_dir = output_dir / "16_FIGURES"
    figure_dir.mkdir(parents=True, exist_ok=True)

    realtime = read_excel_required(output_dir / "05-1_realtime_summary.xlsx", "data")
    baseline = read_excel_required(output_dir / "06_baseline_predictions.xlsx", "predictions")
    signals = read_excel_required(output_dir / "09_candidate_events.xlsx", "class_daily_signals")
    event_grades = read_excel_required(output_dir / "11_dynamic_grading.xlsx", "event_daily_grades")
    latest = read_excel_required(output_dir / "11_dynamic_grading.xlsx", "latest_event_status")
    threshold_grid = read_excel_required(output_dir / "12_threshold_injection.xlsx", "threshold_grid")

    jobs: list[tuple[str, str, pd.DataFrame, Callable[[pd.DataFrame, Path], str], str]] = [
        ("16_01_realtime_trend.png", "实时症候群趋势", realtime, plot_realtime_summary, "05-1_realtime_summary.xlsx"),
        ("16_02_observed_expected.png", "观察值与动态基线", baseline, plot_baseline_fit, "06_baseline_predictions.xlsx"),
        ("16_03_detector_timeline.png", "A/B/C探测器时间序列", signals, plot_detector_timeline, "09_candidate_events.xlsx"),
        ("16_04_school_signal_heatmap.png", "学校异常班级热图", signals, plot_school_heatmap, "09_candidate_events.xlsx"),
        ("16_05_event_lifecycle.png", "候选事件生命周期", event_grades, plot_event_lifecycle, "11_dynamic_grading.xlsx"),
        ("16_06_warning_summary.png", "当前预警等级分布", latest, plot_warning_summary, "11_dynamic_grading.xlsx"),
        ("16_07_threshold_tradeoff.png", "阈值注入权衡", threshold_grid, plot_threshold_tradeoff, "12_threshold_injection.xlsx"),
    ]

    manifest_rows = []
    generated: list[Path] = []
    for filename, title, frame, plotter, source in jobs:
        target = figure_dir / filename
        description = plotter(frame, target)
        generated.append(target)
        manifest_rows.append(
            {
                "figure": filename,
                "title": title,
                "source": source,
                "status": "generated",
                "description": description,
            }
        )

    manifest = pd.DataFrame(manifest_rows)
    manifest_path = output_dir / "16_figure_manifest.csv"
    manifest.to_csv(manifest_path, index=False, encoding="utf-8-sig")

    index_lines = [
        "# 学校急性呼吸道症候群监测预警图形索引",
        "",
        "> 图形用于辅助核查和呈现，不改变模型结果。当前验证数据对应研究原型，不得将候选事件直接解释为确诊暴发。",
        "",
    ]
    for row in manifest.itertuples(index=False):
        index_lines.extend(
            [
                f"## {row.title}",
                "",
                row.description,
                "",
                f"![{row.title}](16_FIGURES/{row.figure})",
                "",
            ]
        )
    index_path = output_dir / "16_figure_index.md"
    index_path.write_text("\n".join(index_lines), encoding="utf-8")
    return generated + [manifest_path, index_path]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    outputs = generate_figures(args.config)
    print(f"图形输出已生成: {len(outputs) - 2} 张 PNG")
    print(f"图形目录: {outputs[0].parent}")
    print(f"图形清单: {outputs[-2]}")
    print(f"图形索引: {outputs[-1]}")


if __name__ == "__main__":
    main()
