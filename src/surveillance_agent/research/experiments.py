from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict

from ..utils import write_json
from .injection import inject_anomalies
from .schema_drift import (
    constrained_map,
    evaluate_method,
    generate_drift_cases,
    static_primary_map,
)


def run_rq1(output_path: str = "") -> Dict[str, Any]:
    sources = ["hospital", "care_home", "school"]
    methods = [("static_primary", static_primary_map), ("constrained", constrained_map)]

    results = []
    for source in sources:
        cases = generate_drift_cases(source)
        for name, method in methods:
            metrics = evaluate_method(cases, method)
            results.append({"source": source, "method": name, **metrics})

    summary = {}
    for name, _ in methods:
        rows = [r for r in results if r["method"] == name]
        summary[name] = {
            "avg_f1": round(sum(r["f1"] for r in rows) / len(rows), 4) if rows else 0.0,
            "avg_recall": round(sum(r["recall"] for r in rows) / len(rows), 4) if rows else 0.0,
            "total_silent_error": sum(r["silent_error"] for r in rows),
            "total_correct_reject": sum(r["correct_reject"] for r in rows),
        }

    out = {"results": results, "summary": summary}
    if output_path:
        write_json(output_path, out)
    return out


def calibrate_detection_cfg(cfg: Dict, base_aggregates, margin: float = 0.1) -> Dict:
    """在无注入基线上估计各检测器的经验控制限。

    对每条基线条列，用默认参数计算每个时间点的得分，取每个检测器在
    受控(基线)数据上的得分上限×(1+margin)作为新阈值，保证基线内不报警。
    校准集(无注入基线)与测试集(注入后数据)分离，属于经验控制限做法；
    正式论文阶段建议再用一条独立的未注入序列做校准集，避免数据窥探。
    """
    import copy

    from ..models import build_detectors

    detectors = build_detectors(cfg.get("detection", {}))
    min_history = cfg.get("detection", {}).get("min_history", 4)

    series_map = defaultdict(list)
    for p in base_aggregates:
        series_map[(p.source, p.scope_type, p.scope_key, p.syndrome)].append(p)

    by_det = defaultdict(list)
    for series in series_map.values():
        points = sorted(series, key=lambda x: x.date)
        counts = [p.count for p in points]
        for i in range(min_history, len(counts)):
            history = counts[:i]
            current = counts[i]
            for name, det in detectors.items():
                score, _, _, _ = det.compute(history, current)
                by_det[name].append(score)

    new_cfg = copy.deepcopy(cfg)
    det_cfg = new_cfg.setdefault("detection", {})
    for name, scores in by_det.items():
        if not scores:
            continue
        m = max(scores)
        if m <= 0:
            continue
        key = "h" if name == "cusum" else "threshold"
        det_cfg[name][key] = round(m * (1 + margin), 4)
    return new_cfg


def run_rq2(output_path: str = "") -> Dict[str, Any]:
    from ..agent import MultiAgentCoordinator
    from ..agent.model_policy import select_models
    from ..config import load_config

    cfg = load_config()
    base_coord = MultiAgentCoordinator(cfg=cfg, autonomy_stage=0)
    base_coord._task_ingest()
    base_coord._task_aggregate()
    base_aggregates = base_coord.state["aggregates"]
    cal_cfg = calibrate_detection_cfg(cfg, base_aggregates)

    shapes = ["spike", "gradual", "cluster", "multimodal"]
    magnitudes = [2.0, 5.0, 10.0]
    policies = [("fixed_fusion", None), ("adaptive", select_models)]
    threshold_sets = [("default", cfg), ("calibrated", cal_cfg)]

    results = []
    for tname, tcfg in threshold_sets:
        coord = MultiAgentCoordinator(cfg=tcfg, autonomy_stage=0)
        coord._task_ingest()
        coord._task_aggregate()
        aggregates = coord.state["aggregates"]
        for pname, selector in policies:
            coord.model_selector = selector
            for shape in shapes:
                for mag in magnitudes:
                    injected, manifest = inject_anomalies(aggregates, shape, mag)
                    injected_series = defaultdict(set)
                    for inj in manifest["injections"]:
                        injected_series[(inj["source"], inj["scope_key"], inj["syndrome"])].add(inj["date"])

                    coord.state["aggregates_for_detection"] = injected
                    coord._task_detect()
                    coord._task_fuse()

                    alarm_series = defaultdict(list)
                    for s in coord.state["risk_signals"]:
                        if s.level in ("high", "medium"):
                            alarm_series[(s.evidence.source, s.evidence.scope_key, s.evidence.syndrome)].append(s)

                    detected = 0
                    for skey, inj_dates in injected_series.items():
                        for s in alarm_series.get(skey, []):
                            s_dates = set(s.evidence.run_dates or [s.evidence.date])
                            if s_dates & inj_dates:
                                detected += 1
                                break

                    false_alarms = 0
                    for skey, sigs in alarm_series.items():
                        if skey not in injected_series:
                            false_alarms += len(sigs)
                            continue
                        inj_dates = injected_series[skey]
                        for s in sigs:
                            s_dates = set(s.evidence.run_dates or [s.evidence.date])
                            if not (s_dates & inj_dates):
                                false_alarms += 1

                    detection_rate = detected / max(1, len(injected_series))
                    results.append(
                        {
                            "threshold_set": tname,
                            "policy": pname,
                            "shape": shape,
                            "magnitude": mag,
                            "injected_series": len(injected_series),
                            "detected_series": detected,
                            "detection_rate": round(detection_rate, 4),
                            "false_alarms": false_alarms,
                        }
                    )

    summary = {}
    for tname, _ in threshold_sets:
        for pname, _ in policies:
            rows = [r for r in results if r["threshold_set"] == tname and r["policy"] == pname]
            summary[f"{pname}/{tname}"] = {
                "avg_detection_rate": round(sum(r["detection_rate"] for r in rows) / max(1, len(rows)), 4),
                "total_false_alarms": sum(r["false_alarms"] for r in rows),
                "runs": len(rows),
            }

    out = {"results": results, "summary": summary, "total": len(results)}
    if output_path:
        write_json(output_path, out)
    return out


def run_rq4(output_path: str = "") -> Dict[str, Any]:
    import os

    from ..agent import MultiAgentCoordinator
    from ..agent.explanation import template_explain, validate_draft
    from ..config import load_config

    cfg = load_config()
    coord = MultiAgentCoordinator(cfg=cfg, autonomy_stage=0)
    coord._task_ingest()
    coord._task_aggregate()
    coord.state["aggregates_for_detection"] = coord.state["aggregates"]
    coord._task_detect()
    coord._task_fuse()
    signals = coord.state["risk_signals"]

    template_results = []
    passed = 0
    for s in signals:
        draft = template_explain(s.evidence, s.level)
        ok, errors = validate_draft(draft, s.evidence)
        if ok:
            passed += 1
        template_results.append(
            {"signal_id": s.signal_id, "passed": ok, "errors": errors, "claim_count": len(draft.get("claims", []))}
        )

    forged_results = []
    forged_rejected = 0
    for s in signals[:10]:
        draft = template_explain(s.evidence, s.level)
        for c in draft["claims"]:
            if c["field"] == "observed":
                c["value"] = 999.0
        ok, errors = validate_draft(draft, s.evidence)
        if not ok:
            forged_rejected += 1
        forged_results.append({"signal_id": s.signal_id, "passed": ok, "errors": errors})

    llm_mode = os.environ.get("SURVEILLANCE_LLM_MODE", "off")
    llm_ready = llm_mode == "local_http"
    out = {
        "template": {
            "total": len(signals),
            "passed": passed,
            "pass_rate": round(passed / max(1, len(signals)), 4),
            "results": template_results,
        },
        "ungrounded_forged": {
            "total": len(forged_results),
            "rejected": forged_rejected,
            "results": forged_results,
        },
        "grounded_llm": {"status": "ready" if llm_ready else "skipped_no_llm"},
        "ungrounded_llm": {"status": "ready" if llm_ready else "skipped_no_llm"},
    }
    if output_path:
        write_json(output_path, out)
    return out


RUNNERS = {"rq1": run_rq1, "rq2": run_rq2, "rq4": run_rq4}