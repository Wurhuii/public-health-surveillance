"""Fit a pooled negative-binomial dynamic baseline with shrunk class effects."""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from _shared import (
    configure_logging,
    count_tail_probability,
    count_upper_limit,
    estimate_nb_alpha,
    load_pipeline_config,
    require_columns,
    safe_divide,
    teaching_day_index,
    write_excel,
)


def _vector_upper_limit(mu: np.ndarray, alpha: np.ndarray, quantile: float) -> np.ndarray:
    return np.array([count_upper_limit([m], float(a), quantile)[0] for m, a in zip(mu, alpha)])


def _vector_tail(observed: np.ndarray, mu: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    return np.array([count_tail_probability([o], [m], float(a))[0] for o, m, a in zip(observed, mu, alpha)])


def _fallback_expected(data: pd.DataFrame, training: pd.DataFrame) -> tuple[np.ndarray, dict[str, Any]]:
    total_population_days = float(training["class_population"].sum())
    global_rate = (float(training["y"].sum()) + 0.5) / max(total_population_days + 0.5, 1.0)
    school_stats = training.groupby("school_code", as_index=False).agg(
        cases=("y", "sum"), population_days=("class_population", "sum")
    )
    prior_population = float(training["class_population"].median() * max(training["date"].nunique(), 1))
    school_stats["rate"] = (
        school_stats["cases"] + global_rate * prior_population
    ) / (school_stats["population_days"] + prior_population)
    rate_map = school_stats.set_index("school_code")["rate"]
    rate = data["school_code"].map(rate_map).fillna(global_rate).to_numpy(dtype=float)
    return np.maximum(data["class_population"].to_numpy(dtype=float) * rate, 1e-6), {
        "fit_method": "gamma_poisson_fallback",
        "global_rate": global_rate,
    }


def fit_dynamic_baseline(
    class_daily: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    require_columns(
        class_daily,
        ["date", "school_code", "grade", "class_id", "class_population", "new_known_febrile_ari", "weekday"],
        "班级日表",
    )
    data = class_daily.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    data["y"] = pd.to_numeric(data["new_known_febrile_ari"], errors="coerce").fillna(0).astype(int)
    data["class_population"] = pd.to_numeric(data["class_population"], errors="raise")
    if data["class_population"].le(0).any():
        raise ValueError("class_population必须为正数，不能用1静默填补缺失分母")
    data["term_day"] = teaching_day_index(data["date"]).astype(int)
    if "holiday" in data.columns:
        data["holiday"] = pd.to_numeric(data["holiday"], errors="coerce").fillna(0).astype(int)
    else:
        data["holiday"] = 0
    training_end_text = config["baseline"].get("training_end", "")
    training_end = pd.Timestamp(training_end_text).normalize() if training_end_text else data["date"].max()
    training_mask = data["date"].le(training_end)
    training = data.loc[training_mask].copy()
    history_days = int(training["date"].nunique())
    total_cases = int(training["y"].sum())
    prototype_only = int(
        history_days < int(config["baseline"]["min_history_teaching_days"])
        or total_cases < int(config["baseline"]["min_total_primary_cases"])
        or not training_end_text
    )

    offset_training = np.log(training["class_population"].to_numpy(dtype=float))
    spline_df = max(3, min(int(config["baseline"]["spline_df"]), max(history_days - 1, 3)))
    formula = f"y ~ C(school_code) + C(grade) + C(weekday) + bs(term_day, df={spline_df}, degree=3)"
    model_object: Any = None
    diagnostics: dict[str, Any]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            initial = smf.glm(
                formula=formula,
                data=training,
                family=sm.families.Poisson(),
                offset=offset_training,
            ).fit(maxiter=200)
        initial_mu = np.maximum(initial.predict(training, offset=offset_training), 1e-6)
        residual = (training["y"].to_numpy() - initial_mu) / np.sqrt(initial_mu)
        positive = residual[residual > 0]
        cutoff = np.quantile(positive, float(config["baseline"]["outlier_quantile"])) if len(positive) else np.inf
        keep = residual < cutoff
        robust_training = training.loc[keep].copy()
        robust_offset = np.log(robust_training["class_population"].to_numpy(dtype=float))
        alpha_initial = estimate_nb_alpha(
            robust_training["y"],
            np.maximum(initial.predict(robust_training, offset=robust_offset), 1e-6),
        )
        alpha_fit = max(alpha_initial, 1e-8)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model_object = smf.glm(
                formula=formula,
                data=robust_training,
                family=sm.families.NegativeBinomial(alpha=alpha_fit),
                offset=robust_offset,
            ).fit(maxiter=300)
        base_mu = np.maximum(
            model_object.predict(data, offset=np.log(data["class_population"].to_numpy(dtype=float))),
            float(config["baseline"]["minimum_mean"]),
        )
        diagnostics = {
            "fit_method": "pooled_nb_glm_plus_eb_class_effect",
            "formula": formula,
            "excluded_high_residual_rows": int((~keep).sum()),
        }
    except Exception as exc:
        base_mu, diagnostics = _fallback_expected(data, training)
        diagnostics["fit_error"] = repr(exc)
        prototype_only = 1

    training_base = pd.DataFrame(
        {"class_id": data.loc[training_mask, "class_id"].values, "y": data.loc[training_mask, "y"].values, "base_mu": base_mu[training_mask.to_numpy()]}
    )
    class_stats = training_base.groupby("class_id", as_index=False).agg(y_sum=("y", "sum"), base_sum=("base_mu", "sum"))
    prior = float(config["baseline"]["class_effect_prior"])
    class_stats["class_rate_ratio"] = (class_stats["y_sum"] + prior) / (class_stats["base_sum"] + prior)
    class_multiplier = data["class_id"].map(class_stats.set_index("class_id")["class_rate_ratio"]).fillna(1.0).to_numpy()
    expected = np.maximum(base_mu * class_multiplier, float(config["baseline"]["minimum_mean"]))
    alpha = estimate_nb_alpha(data.loc[training_mask, "y"], expected[training_mask.to_numpy()])
    result = data[["date", "school_code", "grade", "class_id", "class_population", "y", "term_day", "weekday"]].copy()
    result = result.rename(columns={"y": "O"})
    result["E"] = expected
    result["alpha"] = alpha
    result["theta"] = np.inf if alpha <= 1e-12 else 1.0 / alpha
    result["O_E_ratio"] = safe_divide(result["O"], result["E"])
    result["excess"] = result["O"] - result["E"]
    result["tail_p"] = count_tail_probability(result["O"], result["E"], alpha)
    quantiles = [float(value) for value in config["baseline"]["quantiles"]]
    for quantile in quantiles:
        label = str(quantile * 100).replace(".", "").rstrip("0")
        result[f"PI{label}"] = count_upper_limit(result["E"], alpha, quantile)

    result = result.sort_values(["school_code", "class_id", "date"]).reset_index(drop=True)
    result["A_O_3d"] = result.groupby("class_id")["O"].transform(lambda series: series.rolling(3, min_periods=1).sum())
    result["A_E_3d"] = result.groupby("class_id")["E"].transform(lambda series: series.rolling(3, min_periods=1).sum())
    result["_daily_variance"] = result["E"] + alpha * result["E"] ** 2
    result["_variance_3d"] = result.groupby("class_id")["_daily_variance"].transform(lambda series: series.rolling(3, min_periods=1).sum())
    result["A_alpha_3d"] = np.maximum(
        safe_divide(result["_variance_3d"] - result["A_E_3d"], result["A_E_3d"] ** 2, 0.0), 0.0
    )
    result["A_OE_3d"] = safe_divide(result["A_O_3d"], result["A_E_3d"])
    result["A_tail_p_3d"] = _vector_tail(result["A_O_3d"].to_numpy(), result["A_E_3d"].to_numpy(), result["A_alpha_3d"].to_numpy())
    for quantile in quantiles:
        label = str(quantile * 100).replace(".", "").rstrip("0")
        result[f"A_PI{label}_3d"] = _vector_upper_limit(result["A_E_3d"].to_numpy(), result["A_alpha_3d"].to_numpy(), quantile)
    result["A_strength"] = 0
    result.loc[(result["O"] > result["PI95"]) | (result["A_O_3d"] > result["A_PI95_3d"]), "A_strength"] = 1
    medium = (
        ((result["O"] > result["PI975"]) | (result["A_O_3d"] > result["A_PI975_3d"]))
        & result["A_O_3d"].ge(int(config["detectors"]["a_min_medium_cases"]))
    )
    result.loc[medium, "A_strength"] = 2
    strong = (
        ((result["O"] > result["PI995"]) | (result["A_O_3d"] > result["A_PI99_3d"]))
        & result["A_O_3d"].ge(int(config["detectors"]["a_min_strong_cases"]))
        & result["A_OE_3d"].ge(float(config["detectors"]["a_strong_oe_ratio"]))
    )
    result.loc[strong, "A_strength"] = 3
    result["prototype_only"] = prototype_only
    result["is_training_period"] = training_mask.astype(int)
    result = result.drop(columns=["_daily_variance", "_variance_3d"])

    training_result = result.loc[result["is_training_period"].eq(1)]
    diagnostics.update(
        {
            "training_end": training_end,
            "history_teaching_days": history_days,
            "training_primary_cases": total_cases,
            "classes": int(data["class_id"].nunique()),
            "alpha": alpha,
            "prototype_only": prototype_only,
            "prototype_reason": "历史教学日或主症候群病例不足，或未设置独立训练截止日" if prototype_only else "",
            "pi95_coverage_in_training": float((training_result["O"] <= training_result["PI95"]).mean()),
            "pi95_exceed_per_1000_class_days": float((training_result["O"] > training_result["PI95"]).mean() * 1000),
        }
    )
    return result, pd.DataFrame([diagnostics]), {"model": model_object, "class_effects": class_stats, "diagnostics": diagnostics, "config": config}


def run(config_path: str | Path) -> list[Path]:
    config = load_pipeline_config(config_path)
    input_path = Path(config["paths"]["output_dir"]) / "05-2_class_daily.xlsx"
    class_daily = pd.read_excel(input_path, sheet_name="data", parse_dates=["date"])
    predictions, diagnostics, bundle = fit_dynamic_baseline(class_daily, config)
    output_dir = Path(config["paths"]["output_dir"])
    prediction_path = output_dir / "06_baseline_predictions.xlsx"
    model_path = output_dir / "06_baseline_model.joblib"
    write_excel(prediction_path, {"predictions": predictions, "diagnostics": diagnostics})
    try:
        joblib.dump(bundle, model_path)
    except Exception:
        joblib.dump({"class_effects": bundle["class_effects"], "diagnostics": bundle["diagnostics"], "config": config}, model_path)
    return [prediction_path, model_path]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    for output in run(args.config):
        print(f"动态基线结果已保存: {output}")


if __name__ == "__main__":
    main()
