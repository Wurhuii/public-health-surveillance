"""Standardize symptom text and derive reproducible respiratory syndromes."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from _shared import configure_logging, load_pipeline_config, normalize_text, require_columns, write_excel


SYMPTOM_DICTIONARY: dict[str, list[str]] = {
    "fever": ["发热", "发烧", "高热", "低热", "未退热"],
    "cough": ["咳嗽", "咳痰", "干咳", "咳", "有痰"],
    "sore_throat": ["咽痛", "喉咙痛", "嗓子痛", "嗓子疼", "咽喉痛"],
    "rhinorrhea": ["流鼻涕", "流涕", "鼻涕"],
    "nasal_congestion": ["鼻塞", "鼻子堵", "鼻堵"],
    "headache": ["头痛", "头疼", "头晕"],
    "fatigue": ["乏力", "没精神", "精神差", "疲倦", "无力"],
    "dyspnea": ["呼吸困难", "气促", "喘憋", "气短", "喘气"],
    "chest_pain": ["胸口痛", "胸痛", "胸闷"],
    "other_respiratory": ["其他呼吸道表现"],
}

RESPIRATORY_COMPONENTS = [
    "cough", "sore_throat", "rhinorrhea", "nasal_congestion", "dyspnea",
    "chest_pain", "other_respiratory",
]
NEGATION_WORDS = ("无", "未见", "没有", "否认", "不")
POSITIVE_EXCEPTIONS = ("未退热",)


def _is_nonnegated(text: str, synonym: str) -> bool:
    if synonym in POSITIVE_EXCEPTIONS and synonym in text:
        return True
    for match in re.finditer(re.escape(synonym), text):
        prefix = text[max(0, match.start() - 4):match.start()]
        if not any(prefix.endswith(word) for word in NEGATION_WORDS):
            return True
    return False


def symptom_flags(text: Any) -> dict[str, int]:
    normalized = normalize_text(text)
    return {
        symptom: int(any(_is_nonnegated(normalized, synonym) for synonym in synonyms))
        for symptom, synonyms in SYMPTOM_DICTIONARY.items()
    }


def extract_temperature(text: Any) -> float:
    normalized = normalize_text(text)
    match = re.search(r"(?:体温|发热)?[（(]?([3-4]\d(?:\.\d)?)[℃度）)]?", normalized)
    if not match:
        return np.nan
    value = float(match.group(1))
    return value if 34.0 <= value <= 43.0 else np.nan


def add_syndrome_flags(frame: pd.DataFrame, text_column: str) -> pd.DataFrame:
    result = frame.copy()
    flags = pd.DataFrame([symptom_flags(value) for value in result[text_column]], index=result.index)
    result = pd.concat([result, flags], axis=1)
    result["temperature"] = result[text_column].map(extract_temperature)
    result["respiratory_symptom_count"] = result[RESPIRATORY_COMPONENTS].sum(axis=1)
    result["broad_ari"] = result["respiratory_symptom_count"].ge(2).astype(int)
    result["fever_ari"] = (result["fever"].eq(1) & result["respiratory_symptom_count"].ge(1)).astype(int)
    result["ili_like"] = (result["fever"].eq(1) & (result["cough"].eq(1) | result["sore_throat"].eq(1))).astype(int)
    return result


def define_syndromes(
    episodes: pd.DataFrame, updates: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    require_columns(episodes, ["episode_id", "symptom_text_combined", "absence_final", "visit_final"], "episode表")
    require_columns(updates, ["episode_id", "symptom_text", "report_date", "session_order", "onset_date"], "episode更新表")
    episode_result = add_syndrome_flags(episodes, "symptom_text_combined")
    episode_result["respiratory_absence"] = (episode_result["broad_ari"].eq(1) & episode_result["absence_final"].eq("是")).astype(int)
    episode_result["respiratory_visit"] = (episode_result["broad_ari"].eq(1) & episode_result["visit_final"].eq("是")).astype(int)

    update_result = add_syndrome_flags(updates, "symptom_text")
    update_result = update_result.sort_values(["episode_id", "report_date", "session_order", "source_row_id"])
    symptom_columns = list(SYMPTOM_DICTIONARY)
    cumulative = update_result.groupby("episode_id")[symptom_columns].cummax()
    for column in symptom_columns:
        update_result[f"known_{column}"] = cumulative[column]
    update_result["known_respiratory_symptom_count"] = update_result[[f"known_{c}" for c in RESPIRATORY_COMPONENTS]].sum(axis=1)
    update_result["known_broad_ari"] = update_result["known_respiratory_symptom_count"].ge(2).astype(int)
    update_result["known_fever_ari"] = (
        update_result["known_fever"].eq(1) & update_result["known_respiratory_symptom_count"].ge(1)
    ).astype(int)
    update_result["known_ili_like"] = (
        update_result["known_fever"].eq(1)
        & (update_result["known_cough"].eq(1) | update_result["known_sore_throat"].eq(1))
    ).astype(int)

    for syndrome in ("broad_ari", "fever_ari", "ili_like"):
        known_column = f"known_{syndrome}"
        first_rows = update_result.loc[update_result[known_column].eq(1)].groupby("episode_id", as_index=False).first()
        first_rows = first_rows[["episode_id", "report_date", "session", "onset_date"]].rename(
            columns={
                "report_date": f"first_known_{syndrome}_date",
                "session": f"first_known_{syndrome}_session",
                "onset_date": f"known_onset_at_{syndrome}_detection",
            }
        )
        episode_result = episode_result.merge(first_rows, on="episode_id", how="left")

    dictionary_rows = [
        {"standard_symptom": symptom, "synonym": synonym, "is_respiratory_component": int(symptom in RESPIRATORY_COMPONENTS)}
        for symptom, synonyms in SYMPTOM_DICTIONARY.items()
        for synonym in synonyms
    ]
    return episode_result, update_result, pd.DataFrame(dictionary_rows)


def run(config_path: str | Path) -> Path:
    config = load_pipeline_config(config_path)
    input_path = Path(config["paths"]["output_dir"]) / "03_student_episodes.xlsx"
    episodes = pd.read_excel(input_path, sheet_name="episodes")
    updates = pd.read_excel(input_path, sheet_name="episode_updates")
    for frame in (episodes, updates):
        for column in ("onset_date", "first_report_date", "report_date"):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column], errors="coerce")
    episodes_out, updates_out, dictionary = define_syndromes(episodes, updates)
    output = Path(config["paths"]["output_dir"]) / "04_syndromic_episodes.xlsx"
    write_excel(output, {"episodes": episodes_out, "episode_updates": updates_out, "symptom_dictionary": dictionary})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    print(f"症候群定义结果已保存: {run(args.config)}")


if __name__ == "__main__":
    main()
