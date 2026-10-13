"""Build leakage-safe class, grade, and school monitoring tables."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from _shared import configure_logging, load_pipeline_config, read_table, require_columns, safe_divide, write_excel


def monitoring_dates(episodes: pd.DataFrame, config: dict[str, Any]) -> pd.DatetimeIndex:
    calendar_path = config["paths"].get("school_calendar", "")
    if calendar_path and Path(calendar_path).exists():
        calendar = read_table(Path(calendar_path))
        require_columns(calendar, ["date", "is_school_day"], "学校日历")
        calendar["date"] = pd.to_datetime(calendar["date"], errors="coerce").dt.normalize()
        return pd.DatetimeIndex(calendar.loc[calendar["is_school_day"].astype(bool), "date"].dropna().sort_values().unique())
    start = min(episodes["onset_date"].min(), episodes["first_report_date"].min())
    end = episodes["first_report_date"].max()
    return pd.bdate_range(start=start, end=end, freq="B")


def _event_contributions(events: pd.DataFrame, dates: pd.DatetimeIndex, window: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    date_set = set(dates)
    for event in events.itertuples(index=False):
        detection = pd.Timestamp(event.detection_date).normalize()
        onset = pd.Timestamp(event.known_onset_date).normalize()
        for current_date in dates:
            if current_date < detection:
                continue
            if onset <= current_date <= onset + pd.Timedelta(days=window - 1):
                rows.append({"date": current_date, "class_id": event.class_id, "episode_id": event.episode_id})
    if not rows:
        return pd.DataFrame(columns=["date", "class_id", f"known_onset_{window}d"])
    contributions = pd.DataFrame(rows)
    return contributions.groupby(["date", "class_id"], as_index=False)["episode_id"].nunique().rename(
        columns={"episode_id": f"known_onset_{window}d"}
    )


def build_realtime_tables(
    episodes: pd.DataFrame, roster: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    primary = config["syndromes"]["primary"]
    first_known_column = f"first_known_{primary}_date"
    first_session_column = f"first_known_{primary}_session"
    onset_column = f"known_onset_at_{primary}_detection"
    require_columns(
        episodes,
        ["episode_id", "class_id", "school_code", "grade", "onset_date", "first_report_date", first_known_column, first_session_column, onset_column],
        "症候群episode表",
    )
    require_columns(roster, ["class_id", "school_code", "grade", "population"], "班级人口表")
    for column in ("onset_date", "first_report_date", first_known_column, onset_column, "first_absence_yes_date", "first_visit_yes_date"):
        if column in episodes:
            episodes[column] = pd.to_datetime(episodes[column], errors="coerce").dt.normalize()

    dates = monitoring_dates(episodes, config)
    roster_clean = roster[["class_id", "school_code", "grade", "population"]].drop_duplicates("class_id").copy()
    roster_clean["population"] = pd.to_numeric(roster_clean["population"], errors="coerce")
    if roster_clean["population"].isna().any() or roster_clean["population"].le(0).any():
        raise ValueError("班级人口表包含缺失或非正人口")
    date_frame = pd.DataFrame({"date": dates})
    roster_clean["_key"] = 1
    date_frame["_key"] = 1
    class_daily = roster_clean.merge(date_frame, on="_key", how="inner").drop(columns="_key")

    events = episodes.loc[episodes[first_known_column].notna()].copy()
    events = events.rename(columns={first_known_column: "detection_date", onset_column: "known_onset_date", first_session_column: "detection_session"})
    new_counts = events.groupby(["detection_date", "class_id"], as_index=False)["episode_id"].nunique().rename(
        columns={"detection_date": "date", "episode_id": "new_known_febrile_ari"}
    )
    class_daily = class_daily.merge(new_counts, on=["date", "class_id"], how="left")
    for window in config["syndromes"]["windows"]:
        class_daily = class_daily.merge(_event_contributions(events, dates, int(window)), on=["date", "class_id"], how="left")

    if events.empty:
        session_counts = pd.DataFrame(columns=["date", "class_id", "morning_count", "afternoon_new"])
    else:
        session_counts = events.pivot_table(
            index=["detection_date", "class_id"], columns="detection_session", values="episode_id", aggfunc="nunique", fill_value=0
        ).reset_index().rename(columns={"detection_date": "date", "morning": "morning_count", "afternoon": "afternoon_new"})
    for column in ("morning_count", "afternoon_new"):
        if column not in session_counts:
            session_counts[column] = 0
    class_daily = class_daily.merge(session_counts[["date", "class_id", "morning_count", "afternoon_new"]], on=["date", "class_id"], how="left")

    event_3d_rows: list[dict[str, Any]] = []
    for event in events.itertuples(index=False):
        for current_date in dates:
            if current_date < event.detection_date:
                continue
            if event.known_onset_date <= current_date <= event.known_onset_date + pd.Timedelta(days=2):
                event_3d_rows.append(
                    {
                        "date": current_date,
                        "class_id": event.class_id,
                        "episode_id": event.episode_id,
                        "resp_absence": int(getattr(event, "respiratory_absence", 0) == 1 and pd.notna(event.first_absence_yes_date) and event.first_absence_yes_date <= current_date),
                        "visited": int(pd.notna(event.first_visit_yes_date) and event.first_visit_yes_date <= current_date),
                        "report_delay": max(int((event.detection_date - event.known_onset_date).days), 0),
                    }
                )
    event_3d = pd.DataFrame(event_3d_rows)
    if not event_3d.empty:
        enhancements = event_3d.groupby(["date", "class_id"], as_index=False).agg(
            resp_absence_count=("resp_absence", "sum"),
            visit_count=("visited", "sum"),
            report_delay_mean=("report_delay", "mean"),
        )
        class_daily = class_daily.merge(enhancements, on=["date", "class_id"], how="left")
    else:
        class_daily[["resp_absence_count", "visit_count", "report_delay_mean"]] = np.nan

    count_columns = ["new_known_febrile_ari", "morning_count", "afternoon_new", "resp_absence_count", "visit_count"] + [
        f"known_onset_{window}d" for window in config["syndromes"]["windows"]
    ]
    for column in count_columns:
        class_daily[column] = class_daily[column].fillna(0).astype(int)
    for window in config["syndromes"]["windows"]:
        class_daily[f"rate_{window}d"] = np.round(
            safe_divide(class_daily[f"known_onset_{window}d"], class_daily["population"], 0.0) * 1000,
            3,
        )
    class_daily = class_daily.rename(columns={"population": "class_population"})
    class_daily["weekday"] = class_daily["date"].dt.dayofweek
    class_daily["is_school_day"] = 1
    class_daily = class_daily.sort_values(["school_code", "class_id", "date"]).reset_index(drop=True)

    class_daily["affected_3d"] = class_daily["known_onset_3d"].gt(0).astype(int)
    class_daily["newly_affected_3d"] = (
        class_daily["affected_3d"].eq(1)
        & class_daily.groupby("class_id")["affected_3d"].shift(fill_value=0).eq(0)
    ).astype(int)
    class_daily["class_rate_3d_raw"] = safe_divide(class_daily["known_onset_3d"], class_daily["class_population"], 0.0)

    grade_daily = class_daily.groupby(["date", "school_code", "grade"], as_index=False).agg(
        grade_population=("class_population", "sum"),
        grade_cases=("known_onset_3d", "sum"),
        affected_classes=("affected_3d", "sum"),
        total_classes=("class_id", "nunique"),
        max_class_cases=("known_onset_3d", "max"),
        max_class_ratio=("class_rate_3d_raw", "max"),
        new_affected_classes=("newly_affected_3d", "sum"),
    )
    grade_daily["grade_rate"] = np.round(safe_divide(grade_daily["grade_cases"], grade_daily["grade_population"], 0.0) * 1000, 3)
    grade_daily["grade_rate_raw"] = safe_divide(grade_daily["grade_cases"], grade_daily["grade_population"], 0.0)
    grade_daily["affected_class_ratio"] = safe_divide(grade_daily["affected_classes"], grade_daily["total_classes"], 0.0)

    grade_daily["affected_grade"] = grade_daily["grade_cases"].gt(0).astype(int)
    school_daily = class_daily.groupby(["date", "school_code"], as_index=False).agg(
        school_population=("class_population", "sum"),
        school_cases=("known_onset_3d", "sum"),
        affected_classes=("affected_3d", "sum"),
        total_classes=("class_id", "nunique"),
        max_class_concentration=("class_rate_3d_raw", "max"),
    )
    grade_spread = grade_daily.groupby(["date", "school_code"], as_index=False).agg(
        affected_grades=("affected_grade", "sum"), total_grades=("grade", "nunique"), max_grade_concentration=("grade_rate_raw", "max")
    )
    school_daily = school_daily.merge(grade_spread, on=["date", "school_code"], how="left")
    school_daily["school_rate"] = np.round(safe_divide(school_daily["school_cases"], school_daily["school_population"], 0.0) * 1000, 3)
    school_daily["cross_class_spread"] = safe_divide(school_daily["affected_classes"], school_daily["total_classes"], 0.0)
    school_daily["cross_grade_spread"] = safe_divide(school_daily["affected_grades"], school_daily["total_grades"], 0.0)

    realtime_summary = class_daily.groupby("date", as_index=False).agg(
        new_known_primary=("new_known_febrile_ari", "sum"),
        known_onset_1d=("known_onset_1d", "sum"),
        known_onset_3d=("known_onset_3d", "sum"),
        affected_classes=("affected_3d", "sum"),
        afternoon_new=("afternoon_new", "sum"),
    )
    return realtime_summary, class_daily.drop(columns=["class_rate_3d_raw"]), grade_daily, school_daily


def run(config_path: str | Path) -> list[Path]:
    config = load_pipeline_config(config_path)
    input_path = Path(config["paths"]["output_dir"]) / "04_syndromic_episodes.xlsx"
    episodes = pd.read_excel(input_path, sheet_name="episodes")
    roster = read_table(Path(config["paths"]["class_population"]))
    summary, class_daily, grade_daily, school_daily = build_realtime_tables(episodes, roster, config)
    output_dir = Path(config["paths"]["output_dir"])
    outputs = [
        output_dir / "05-1_realtime_summary.xlsx",
        output_dir / "05-2_class_daily.xlsx",
        output_dir / "05-3_grade_daily.xlsx",
        output_dir / "05-4_school_daily.xlsx",
    ]
    for path, frame in zip(outputs, (summary, class_daily, grade_daily, school_daily)):
        write_excel(path, {"data": frame})
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    for output in run(args.config):
        print(f"实时分析表已保存: {output}")


if __name__ == "__main__":
    main()
