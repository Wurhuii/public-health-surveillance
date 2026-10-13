"""Shared utilities for the school syndromic-surveillance pipeline."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import nbinom, poisson


LOGGER = logging.getLogger("school_warning")


def load_pipeline_config(path: str | Path | None) -> dict[str, Any]:
    """Load ``00_config.py`` without relying on an invalid numeric import name."""
    module_path = Path(__file__).with_name("00_config.py")
    spec = importlib.util.spec_from_file_location("school_warning_config", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载配置模块: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_config(path)


def configure_logging(verbose: bool = False) -> None:
    """Configure a concise process-wide logger."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge dictionaries without mutating either input."""
    merged = deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, default=str)


def resolve_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def read_table(path: Path, **kwargs: Any) -> pd.DataFrame:
    """Read CSV/XLS/XLSX with explicit, predictable fallbacks."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            return pd.read_csv(path, encoding="utf-8-sig", low_memory=False, **kwargs)
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="gb18030", low_memory=False, **kwargs)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, **kwargs)
    raise ValueError(f"不支持的表格格式: {path}")


def write_excel(path: Path, sheets: Mapping[str, pd.DataFrame]) -> None:
    """Write one or more DataFrames to an XLSX workbook."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=sheet_name[:31], index=False)


def require_columns(df: pd.DataFrame, columns: Iterable[str], context: str) -> None:
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise ValueError(f"{context}缺少必要字段: {missing}")


def normalize_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", "", str(value).strip())


def normalize_yes_no(value: Any) -> str:
    text = normalize_text(value).lower()
    yes_values = {"是", "有", "true", "1", "yes", "y"}
    no_values = {"否", "无", "false", "0", "no", "n"}
    if text in yes_values:
        return "是"
    if text in no_values:
        return "否"
    return "未知"


def parse_grade(value: Any) -> float:
    """Convert primary/middle/high-school grade labels to absolute grade 1-12."""
    text = normalize_text(value)
    match = re.search(r"(\d+)", text)
    if not match:
        return np.nan
    number = int(match.group(1))
    if "初中" in text or text.startswith("初"):
        number += 6
    elif "高中" in text or text.startswith("高"):
        number += 9
    return float(number) if 1 <= number <= 12 else np.nan


def parse_class_number(value: Any) -> float:
    text = normalize_text(value)
    match = re.search(r"(\d+)", text)
    return float(int(match.group(1))) if match else np.nan


def safe_divide(
    numerator: pd.Series | np.ndarray,
    denominator: pd.Series | np.ndarray,
    fill_value: float = np.nan,
) -> np.ndarray:
    numerator_array = np.asarray(numerator, dtype=float)
    denominator_array = np.asarray(denominator, dtype=float)
    result = np.full(np.broadcast(numerator_array, denominator_array).shape, fill_value)
    valid = np.isfinite(denominator_array) & (denominator_array != 0)
    np.divide(numerator_array, denominator_array, out=result, where=valid)
    return result


def bh_fdr(pvalues: Sequence[float]) -> np.ndarray:
    """Benjamini-Hochberg adjusted q-values in original row order."""
    values = np.asarray(pvalues, dtype=float)
    adjusted = np.full(values.shape, np.nan, dtype=float)
    valid = np.isfinite(values)
    if not valid.any():
        return adjusted
    finite_values = values[valid]
    order = np.argsort(finite_values)
    ranked = finite_values[order]
    ranks = np.arange(1, len(ranked) + 1)
    qvalues = np.minimum.accumulate((ranked * len(ranked) / ranks)[::-1])[::-1]
    qvalues = np.clip(qvalues, 0.0, 1.0)
    restored = np.empty_like(qvalues)
    restored[order] = qvalues
    adjusted[valid] = restored
    return adjusted


def estimate_nb_alpha(observed: Sequence[float], expected: Sequence[float]) -> float:
    """Moment estimate for Var(Y)=mu+alpha*mu^2."""
    observed_array = np.asarray(observed, dtype=float)
    expected_array = np.asarray(expected, dtype=float)
    valid = np.isfinite(observed_array) & np.isfinite(expected_array) & (expected_array > 0)
    if not valid.any():
        return 0.0
    o = observed_array[valid]
    e = expected_array[valid]
    denominator = float(np.sum(e**2))
    if denominator <= 0:
        return 0.0
    return max(float(np.sum((o - e) ** 2 - e) / denominator), 0.0)


def count_upper_limit(mu: Sequence[float], alpha: float, quantile: float) -> np.ndarray:
    """Poisson/NB upper prediction limit with non-negative means."""
    means = np.maximum(np.asarray(mu, dtype=float), 0.0)
    if alpha <= 1e-12:
        return poisson.ppf(quantile, means)
    theta = 1.0 / alpha
    probability = theta / (theta + means)
    return nbinom.ppf(quantile, theta, probability)


def count_tail_probability(
    observed: Sequence[float], mu: Sequence[float], alpha: float
) -> np.ndarray:
    """Return P(Y >= observed) under a Poisson/NB count model."""
    observations = np.asarray(observed, dtype=float)
    means = np.maximum(np.asarray(mu, dtype=float), 0.0)
    if alpha <= 1e-12:
        return poisson.sf(observations - 1, means)
    theta = 1.0 / alpha
    probability = theta / (theta + means)
    return nbinom.sf(observations - 1, theta, probability)


def teaching_day_index(dates: pd.Series) -> pd.Series:
    """Return a stable one-based index across sorted unique monitoring dates."""
    unique_dates = pd.Series(pd.to_datetime(dates).dropna().unique()).sort_values()
    mapping = {date: index + 1 for index, date in enumerate(unique_dates)}
    return pd.to_datetime(dates).map(mapping).astype("Int64")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_finite_nonnegative(series: pd.Series, name: str) -> None:
    values = pd.to_numeric(series, errors="coerce")
    if values.isna().any() or (values < 0).any():
        raise ValueError(f"{name}必须为有限非负数")


def json_scalar(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value
