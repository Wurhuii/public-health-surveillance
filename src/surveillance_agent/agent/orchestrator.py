from __future__ import annotations

import csv
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..adapters import detect_adapter_from_file, map_syndromes, read_rows
from ..adapters.yichang_focus import ingest_yichang_focus_bundle
from ..aggregation import aggregate
from ..config import PROJECT_ROOT, data_dir, load_config, resolve_source_file
from ..domain import (
    AggregatePoint,
    DetectorPoint,
    RiskEvidence,
    RiskSignal,
    SurveillanceEvent,
)
from ..models import build_detectors, fuse_alarms
from ..storage import Storage
from ..utils import append_jsonl, get_salt, hash_id, write_json
from .explanation import llm_explain_many, template_explain, validate_draft
from .llm import get_llm, get_llm_settings
from .messages import AgentMessage, new_correlation_id
from .roles import ACTION_TO_ROLE, list_roles

BASE_ORDER = ["ingest", "aggregate", "inject", "detect", "fuse", "explain", "audit", "persist"]

_LEVEL_RANK = {"high": 3, "medium": 2, "watch": 1, "normal": 0}

_SIGNAL_CATALOG = {
    "21": {"name": "医院病区急性呼吸道感染聚集线索", "setting_code": "HOS", "type_code": "E", "boundary": "医院病区内病例在短期窗口集中或持续异常升高。"},
    "22": {"name": "农贸市场从业人员急性呼吸道症候群异常升高", "setting_code": "MKT", "type_code": "E", "boundary": "市场从业人员症候群监测值超过历史基线。"},
    "23": {"name": "农贸市场从业人员传染病聚集线索", "setting_code": "MKT", "type_code": "E", "boundary": "需要传染病诊断或实验室结果支持；仅有症候数据时不生成。"},
    "24": {"name": "养老机构入住老人急性呼吸道感染异常增多", "setting_code": "ELD", "type_code": "E", "boundary": "入住老人在机构内出现呼吸道事件异常增多。"},
    "25": {"name": "养老机构外部呼吸道疫情输入风险", "setting_code": "ELD", "type_code": "R", "boundary": "需要周边医疗或社会面疫情与人员流动信息支持。"},
    "26": {"name": "学校班级学生急性呼吸道症候群聚集事件", "setting_code": "SCH", "type_code": "E", "boundary": "同一班级在教学日窗口内集中出现呼吸道症候群。"},
    "27": {"name": "学校学生呼吸道发病水平异常", "setting_code": "SCH", "type_code": "E", "boundary": "学校层面发病水平高于教学日历史基线。"},
    "28": {"name": "跨学校社会面呼吸道疫情放大与延续风险", "setting_code": "REG", "type_code": "R", "boundary": "需要多学校或社会面数据共同支持，不代表单个学校暴发。"},
}


class MultiAgentCoordinator:
    def __init__(
        self,
        cfg: Dict = None,
        run_dir: str = "",
        use_langgraph: bool = False,
        autonomy_stage: Optional[int] = None,
    ):
        self.cfg = cfg if cfg is not None else load_config()
        self.use_langgraph = use_langgraph
        self.autonomy_stage = (
            autonomy_stage
            if autonomy_stage is not None
            else self.cfg.get("supervisor", {}).get("default_autonomy_stage", 1)
        )
        sup = self.cfg.get("supervisor", {})
        self.max_revision_rounds = sup.get("max_revision_rounds", 1)
        self.max_step_retries = sup.get("max_step_retries", 1)
        self.max_iterations = sup.get("max_iterations", 32)
        self.retryable_steps = sup.get("retryable_steps", ["explain", "audit"])

        self.run_id = time.strftime("%Y%m%d-%H%M%S")
        self.run_dir = Path(run_dir) if run_dir else PROJECT_ROOT / "var" / "runs" / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.salt = get_salt(self.cfg.get("privacy", {}).get("default_salt", "demo-only-change-me"))
        self.roles = list_roles()
        self.msg_log = self.run_dir / "agent_messages.jsonl"
        self.decision_log = self.run_dir / "supervisor_decisions.jsonl"
        self.model_selector = None

        self.state: Dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "events": [],
            "quality": {},
            "aggregates": [],
            "aggregates_for_detection": [],
            "injection_manifest": {},
            "detector_points": [],
            "risk_signals": [],
            "explanation_drafts": [],
            "explanations": [],
            "summary": {},
            "node_times": {},
        }

    def _log_message(self, sender: str, receiver: str, task: str, payload: Dict, cid: str, kind: str) -> None:
        msg = AgentMessage(
            correlation_id=cid,
            sender=sender,
            receiver=receiver,
            task=task,
            payload={"kind": kind, **payload},
        )
        append_jsonl(str(self.msg_log), msg.to_dict())

    def _log_decision(self, action: str, suggestion: str, actual: str, reason: str) -> None:
        append_jsonl(
            str(self.decision_log),
            {
                "action": action,
                "baseline": action,
                "suggestion": suggestion,
                "actual": actual,
                "reason": reason,
                "autonomy_stage": self.autonomy_stage,
                "limits": {
                    "max_revision_rounds": self.max_revision_rounds,
                    "max_step_retries": self.max_step_retries,
                    "max_iterations": self.max_iterations,
                },
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )

    def _execute(self, action: str) -> Dict:
        role = ACTION_TO_ROLE.get(action, "supervisor")
        cid = new_correlation_id()
        self._log_message("supervisor", role, action, {"action": action}, cid, "request")
        method = getattr(self, f"_task_{action}")
        started = time.monotonic()
        try:
            result = method()
        finally:
            elapsed = time.monotonic() - started
            timing = self.state["node_times"].setdefault(
                action, {"calls": 0, "total_seconds": 0.0, "last_seconds": 0.0}
            )
            timing["calls"] += 1
            timing["total_seconds"] = round(timing["total_seconds"] + elapsed, 3)
            timing["last_seconds"] = round(elapsed, 3)
        self._log_message(role, "supervisor", action, {"summary": result}, cid, "response")
        if action == "persist":
            # persist itself is measured only after the first write; refresh the
            # human-readable artifacts so they contain the complete timings.
            self._build_summary()
            write_json(str(self.run_dir / "summary.json"), self.state["summary"])
            self._write_state()
        return result

    # ---------------- tasks ----------------

    def _task_ingest(self) -> Dict:
        events: List[SurveillanceEvent] = []
        per_source: Dict[str, Any] = {}
        issues: List[str] = []

        for source, source_cfg in self.cfg.get("sources", {}).items():
            if not source_cfg.get("enabled", True):
                per_source[source] = {"status": "disabled"}
                continue
            path = resolve_source_file(self.cfg, source)
            if source_cfg.get("kind") == "yichang_focus_bundle":
                if not os.path.isdir(str(path)):
                    per_source[source] = {"status": "missing", "directory": str(path)}
                    issues.append(f"missing_directory:{source}")
                    continue
                source_events, bundle_report = ingest_yichang_focus_bundle(
                    str(path), self.salt, source_cfg.get("person_key_fields")
                )
                events.extend(source_events)
                per_source[source] = bundle_report
                if bundle_report.get("status") != "ok":
                    issues.append(f"not_ready_for_alerting:{source}")
                continue
            if not os.path.isfile(str(path)):
                per_source[source] = {"status": "missing", "file": str(path)}
                issues.append(f"missing_file:{source}")
                continue

            adapter_cls = detect_adapter_from_file(str(path))
            if adapter_cls is None:
                per_source[source] = {"status": "unrecognized", "file": str(path)}
                issues.append(f"unrecognized_schema:{source}")
                continue

            adapter = adapter_cls()
            source_events: List[SurveillanceEvent] = []
            dup_keys: List[str] = []
            seen = Counter()
            quality_counter = Counter()
            total_rows = 0

            for row in read_rows(str(path)):
                total_rows += 1
                for issue in adapter.quality_issues(row):
                    quality_counter[issue] += 1
                dup_key = row.get("门诊流水号") or row.get("住院号") or ""
                if dup_key:
                    seen[dup_key] += 1
                ev = adapter.parse(row, self.salt)
                if ev is not None:
                    source_events.append(ev)

            dup_count = sum(1 for k, v in seen.items() if v > 1)
            if dup_count:
                dup_keys = [k for k, v in seen.items() if v > 1][:20]

            events.extend(source_events)
            per_source[source] = {
                "status": "ok",
                "file": str(path),
                "total_rows": total_rows,
                "events": len(source_events),
                "duplicate_keys": dup_count,
                "duplicate_key_samples": dup_keys,
                "quality_issues": dict(quality_counter),
            }

        self.state["events"] = events
        self.state["quality"] = {"per_source": per_source, "issues": issues, "total_events": len(events)}

        import json
        with open(self.run_dir / "events.jsonl", "w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
        write_json(str(self.run_dir / "quality.json"), self.state["quality"])

        event_ids = [e.event_id for e in events]
        unique_ids = len(set(event_ids))
        return {
            "total_events": len(events),
            "unique_event_ids": unique_ids,
            "per_source": {k: v.get("events", 0) for k, v in per_source.items()},
        }

    def _task_aggregate(self) -> Dict:
        include_other = self.cfg.get("aggregation", {}).get("include_other", False)
        points = aggregate(self.state["events"], self.cfg.get("scenarios", {}), include_other=include_other)
        self.state["aggregates"] = points
        self._write_points_csv("aggregates.csv", points)
        return {"aggregate_points": len(points)}

    def _task_inject(self) -> Dict:
        points: List[AggregatePoint] = [p for p in self.state["aggregates"]]
        if not self.inject_enabled:
            self.state["aggregates_for_detection"] = points
            write_json(str(self.run_dir / "injection_manifest.json"), {"enabled": False, "injections": []})
            self._write_points_csv("aggregates_for_detection.csv", points)
            return {"enabled": False}

        shape = self.inject_shape
        magnitude = self.inject_magnitude

        series_map = defaultdict(list)
        for p in points:
            series_map[(p.source, p.scope_type, p.scope_key, p.syndrome)].append(p)

        injections = []
        modified = dict((id(p), p) for p in points)
        targets = [k for k, v in series_map.items() if len(v) >= 6][:5]

        for key in targets:
            series = sorted(series_map[key], key=lambda x: x.date)
            n = len(series)
            mid = n // 2
            chosen = self._injection_positions(shape, mid, n)
            for pos in chosen:
                p = series[pos]
                injected = AggregatePoint(
                    source=p.source,
                    scope_type=p.scope_type,
                    scope_key=p.scope_key,
                    syndrome=p.syndrome,
                    date=p.date,
                    count=max(p.count, 1) + int(p.count * magnitude),
                    scope_label=p.scope_label,
                    context=dict(p.context),
                )
                modified[id(p)] = injected
                injections.append(
                    {
                        "source": p.source,
                        "scope_key": p.scope_key,
                        "syndrome": p.syndrome,
                        "date": p.date,
                        "original": p.count,
                        "injected": injected.count,
                        "shape": shape,
                        "magnitude": magnitude,
                        "true_label": 1,
                    }
                )

        injected_points = list(modified.values())
        injected_points.sort(key=lambda p: (p.source, p.scope_key, p.syndrome, p.date))
        self.state["aggregates_for_detection"] = injected_points
        self.state["injection_manifest"] = {"enabled": True, "shape": shape, "magnitude": magnitude, "injections": injections}
        write_json(str(self.run_dir / "injection_manifest.json"), self.state["injection_manifest"])
        self._write_points_csv("aggregates_for_detection.csv", injected_points)
        return {"enabled": True, "injection_count": len(injections)}

    def _injection_positions(self, shape: str, mid: int, n: int) -> List[int]:
        if shape == "spike":
            return [mid]
        if shape == "cluster":
            return [i for i in (mid, mid + 1) if i < n]
        if shape == "gradual":
            return [i for i in (mid, mid + 1, mid + 2) if i < n]
        if shape == "multimodal":
            return [i for i in (max(0, mid - 3), min(n - 1, mid + 2))]
        return [mid]

    def _task_detect(self) -> Dict:
        points = self.state["aggregates_for_detection"] or self.state["aggregates"]
        detectors = build_detectors(self.cfg.get("detection", {}))
        min_history = self.cfg.get("detection", {}).get("min_history", 4)

        series_map = defaultdict(list)
        for p in points:
            series_map[(p.source, p.scope_type, p.scope_key, p.syndrome)].append(p)

        detector_points: List[DetectorPoint] = []
        for key, series in series_map.items():
            series = sorted(series, key=lambda x: x.date)
            values = [p.count for p in series]
            source, scope_type, scope_key, syndrome = key
            if self.model_selector is not None:
                active = set(
                    self.model_selector(
                        {"source": source, "scope_key": scope_key, "syndrome": syndrome, "values": values}
                    )
                )
            else:
                active = set(detectors.keys())
            for i in range(len(values)):
                history = values[:i]
                if len(history) < min_history:
                    continue
                current = values[i]
                for name, det in detectors.items():
                    if name not in active:
                        continue
                    score, expected, threshold, alarm = det.compute(history, current)
                    detector_points.append(
                        DetectorPoint(
                            source=source,
                            scope_type=scope_type,
                            scope_key=scope_key,
                            syndrome=syndrome,
                            date=series[i].date,
                            observed=float(current),
                            expected=expected,
                            score=score,
                            threshold=threshold,
                            detector=name,
                            alarm=alarm,
                            scope_label=series[i].scope_label,
                            context=dict(series[i].context),
                        )
                    )

        self.state["detector_points"] = detector_points
        self._write_points_csv("detector_points.csv", detector_points)
        return {"detector_points": len(detector_points)}

    def _task_fuse(self) -> Dict:
        merge_runs = self.cfg.get("detection", {}).get("merge_alarm_runs", True)
        watch_ratio = self.cfg.get("detection", {}).get("watch_ratio", 0.7)
        model_version = self.cfg.get("model_version", "1.0.0")

        series_map = defaultdict(list)
        for dp in self.state["detector_points"]:
            if dp.syndrome != "respiratory":
                continue
            series_map[(dp.source, dp.scope_type, dp.scope_key, dp.syndrome)].append(dp)

        signals: List[RiskSignal] = []
        for key, points in series_map.items():
            points.sort(key=lambda p: p.date)
            by_date = defaultdict(dict)
            for dp in points:
                by_date[dp.date][dp.detector] = {
                    "score": dp.score,
                    "expected": dp.expected,
                    "threshold": dp.threshold,
                    "alarm": dp.alarm,
                    "observed": dp.observed,
                    "scope_label": dp.scope_label,
                    "context": dp.context,
                }
            dates = sorted(by_date.keys())

            if not merge_runs:
                for d in dates:
                    sig = self._build_signal(key, by_date, [d], watch_ratio, model_version)
                    if sig is not None:
                        signals.append(sig)
                continue

            run_dates: List[str] = []
            for d in dates:
                if fuse_alarms(by_date[d], watch_ratio) == "normal":
                    if run_dates:
                        sig = self._build_signal(key, by_date, run_dates, watch_ratio, model_version)
                        if sig is not None:
                            signals.append(sig)
                        run_dates = []
                else:
                    run_dates.append(d)
            if run_dates:
                sig = self._build_signal(key, by_date, run_dates, watch_ratio, model_version)
                if sig is not None:
                    signals.append(sig)

        self.state["risk_signals"] = signals
        write_json(
            str(self.run_dir / "risk_signals.json"),
            [s.to_dict() for s in signals],
        )
        return {"risk_signals": len(signals)}

    def _build_signal(
        self,
        key: tuple,
        by_date: Dict,
        dates: List[str],
        watch_ratio: float,
        model_version: str,
    ) -> Optional[RiskSignal]:
        source, scope_type, scope_key, syndrome = key
        ranked = []
        for d in dates:
            level = fuse_alarms(by_date[d], watch_ratio)
            observed = next(iter(by_date[d].values()))["observed"]
            ranked.append((_LEVEL_RANK.get(level, 0), observed, d))
        _, _, rep_date = max(ranked)
        det_res = by_date[rep_date]
        level = fuse_alarms(det_res, watch_ratio)
        if level == "normal":
            return None
        observed = next(iter(det_res.values()))["observed"]
        expected = next(iter(det_res.values()))["expected"]
        evidence = RiskEvidence(
            signal_id=hash_id(f"{source}:{scope_key}:{syndrome}:{rep_date}", self.salt)[:16],
            source=source,
            scope_type=scope_type,
            scope_key=scope_key,
            syndrome=syndrome,
            date=rep_date,
            observed=observed,
            expected=expected,
            scores={k: v["score"] for k, v in det_res.items()},
            thresholds={k: v["threshold"] for k, v in det_res.items()},
            alarms={k: v["alarm"] for k, v in det_res.items()},
            model_version=model_version,
            scope_label=next((v.get("scope_label", "") for v in det_res.values() if v.get("scope_label")), ""),
            quality_limits=[],
            run_dates=sorted(dates),
            presentation=self._build_presentation(
                source=source,
                scope_type=scope_type,
                scope_key=scope_key,
                syndrome=syndrome,
                date_value=rep_date,
                dates=dates,
                observed=observed,
                expected=expected,
                detector_results=det_res,
                model_version=model_version,
                context=next((v.get("context", {}) for v in det_res.values() if v.get("context")), {}),
            ),
        )
        return RiskSignal(signal_id=evidence.signal_id, level=level, evidence=evidence)

    def _build_presentation(
        self,
        source: str,
        scope_type: str,
        scope_key: str,
        syndrome: str,
        date_value: str,
        dates: List[str],
        observed: float,
        expected: float,
        detector_results: Dict[str, Dict[str, Any]],
        model_version: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build the display fields agreed for focus-place warning signals."""
        from datetime import date, datetime

        yichang_setting = "养老机构" if context.get("care_resident_linked") else {
            "outpatient": "医疗机构",
            "inpatient": "医疗机构",
            "elderly": "养老机构",
            "school": "学校",
        }.get(context.get("setting"), "重点场所")
        setting_type = {
            "hospital": "医疗机构",
            "care_home": "养老机构",
            "school": "学校",
            "market": "农贸市场",
            "yichang_focus": yichang_setting,
        }.get(source, "重点场所")
        target = {
            "respiratory": "急性呼吸道症候群",
            "digestive": "消化道症候群",
            "fever": "发热症候群",
        }.get(syndrome, syndrome)
        if scope_type == "province":
            signal_code = "28"
        elif setting_type == "医疗机构":
            signal_code = "21"
        elif setting_type == "农贸市场":
            signal_code = "22"
        elif setting_type == "养老机构":
            signal_code = "24"
        elif setting_type == "学校" and scope_type == "class":
            signal_code = "26"
        elif setting_type == "学校":
            signal_code = "27"
        else:
            signal_code = "21"
        catalog = _SIGNAL_CATALOG[signal_code]
        signal_name = catalog["name"]
        ratio = observed / max(expected, 0.5)
        if scope_type == "ward":
            if len(dates) >= 2:
                signal_name = "医院病区急性呼吸道症候群持续异常升高"
            elif observed >= 3 and ratio >= 2:
                signal_name = "医院病区急性呼吸道病例短期聚集线索"
            else:
                signal_name = "医院病区急性呼吸道症候群异常升高"
        elif scope_type == "class":
            if len(dates) >= 2:
                signal_name = "班级急性呼吸道症候群连续集中出现"
            elif observed >= 3 and ratio >= 2:
                signal_name = "班级急性呼吸道症候群病例集中聚集线索"
            else:
                signal_name = "班级急性呼吸道症候群发病水平异常上升"
        elif source == "market":
            signal_name = (
                "农贸市场从业人员急性呼吸道症候群连续异常升高"
                if len(dates) >= 2
                else "农贸市场从业人员急性呼吸道症候群异常升高"
            )

        source_labels = {
            "hospital": "医疗机构诊疗监测数据",
            "care_home": "养老机构健康监测数据",
            "school": "学校晨午检与缺勤监测数据",
            "market": "农贸市场从业人员健康监测数据",
            "yichang_focus": "宜昌重点场所多来源监测数据",
        }
        related = {
            "24": ["25"], "25": ["24"], "26": ["27", "28"],
            "27": ["26", "28"], "28": ["26", "27"],
        }.get(signal_code, [])
        evidence_items = [
            {"name": "监测事件数", "value": round(observed, 4), "unit": "例", "role": "observed"},
            {"name": "模型预期值", "value": round(expected, 4), "unit": "例", "role": "expected"},
            {"name": "观察/预期比", "value": round(observed / max(expected, 0.5), 4), "unit": "倍", "role": "ratio"},
        ]
        for detector, result in sorted(detector_results.items()):
            evidence_items.append({
                "name": detector.upper(),
                "value": round(float(result.get("score", 0.0)), 4),
                "threshold": round(float(result.get("threshold", 0.0)), 4),
                "alarm": bool(result.get("alarm")),
                "role": "detector",
            })

        latest = str(context.get("latest_update_time") or context.get("latest_event_date") or date_value)
        update_date = None
        try:
            update_date = date.fromisoformat(latest[:10])
        except ValueError:
            try:
                year, week = latest.split("-W", 1)
                update_date = date.fromisocalendar(int(year), int(week), 7)
            except (ValueError, TypeError):
                pass
        expected_days = int(
            self.cfg.get("scenarios", {}).get(source, {}).get(
                "expected_update_days", 31 if source == "school" else 7 if source == "care_home" else 1
            )
        )
        delay_days = max(0, (date.today() - update_date).days - expected_days) if update_date else None
        delayed = delay_days is not None and delay_days > 0
        place_name = str(context.get("place_name") or "").strip()
        if not place_name:
            place_name = scope_key if scope_type == "org" else str(context.get("city") or context.get("province") or scope_key)

        return {
            "generated_at": self.state.get("started_at") or datetime.now().isoformat(timespec="seconds"),
            "province": context.get("province", ""),
            "city": context.get("city", ""),
            "district": context.get("district", ""),
            "setting_type": setting_type,
            "place_name": place_name,
            "location": context.get("location", ""),
            "address": context.get("address", context.get("location", "")),
            "area_code": context.get("area_code", ""),
            "analysis_unit": context.get("analysis_unit", ""),
            "place_code": context.get("place_code", ""),
            "is_regional_aggregate": scope_type == "province",
            "contributing_places": context.get("contributing_places", []),
            "contributing_place_count": context.get("contributing_place_count", 0),
            "signal_code": signal_code,
            "signal_catalog_name": catalog["name"],
            "catalog_setting_code": catalog["setting_code"],
            "catalog_type_code": catalog["type_code"],
            "catalog_boundary": catalog["boundary"],
            "warning_type": "风险预警" if catalog["type_code"] == "R" else "苗头预警",
            "warning_level_scheme": "模型提示分层，业务颜色阈值待协和核定",
            "signal_name": signal_name,
            "verification_status": "待核查",
            "verification_result": "",
            "record_status": "ACTIVE",
            "update_seq": 1,
            "monitored_target": target,
            "source_type": (
                "多源综合" if context.get("care_resident_linked")
                else "场所相关人群异常" if scope_type != "province"
                else "社会面疫情"
            ),
            "monitoring_window": f"{min(dates)} 至 {max(dates)}" if len(dates) > 1 else date_value,
            "window_start": min(dates),
            "window_end": max(dates),
            "window_basis": "自然日连续窗口" if source != "school" else "教学日窗口（休假日剔除）",
            "key_indicator": f"监测值 {observed:g} 例，模型预期 {expected:g} 例",
            "evidence_items": evidence_items,
            "source_details": source_labels.get(source, source),
            "rule_id": f"RULE-{signal_code}-ENSEMBLE",
            "rule_version": model_version,
            "rule_status": "待业务验证",
            "verification_hint": "请核对病例明细、统计时段、数据完整性及场所内时空聚集情况。系统信号不代表已确认聚集或暴发。",
            "comparison_policy": (
                "仅纳入教学日，周末、寒暑假和节假日不进入基线比较"
                if source == "school"
                else "按连续监测周期与历史基线比较"
            ),
            "identity_linkage": (
                "已通过不可逆脱敏身份键关联，医疗病例已归并至对应养老机构"
                if context.get("care_resident_linked")
                else "未发现可用于跨机构归并的共享不可逆脱敏身份键"
                if setting_type == "养老机构"
                else "不适用"
            ),
            "data_update_rule": (
                f"每日固定于上班时段 {self.cfg.get('scenarios', {}).get(source, {}).get('scheduled_update_time')} 更新"
                if source == "market"
                else f"预期每 {expected_days} 天至少更新一次"
            ),
            "data_updated_at": latest,
            "expected_update_interval_days": expected_days,
            "data_delay_days": delay_days,
            "data_status": "延迟" if delayed else "正常",
            "report_time": "",
            "related_signal_codes": related,
            "missing_fields": [
                name for name, value in {
                    "行政区划编码": context.get("area_code", ""),
                    "场所编号": context.get("place_code", ""),
                    "详细地址": context.get("address", context.get("location", "")),
                }.items() if not value
            ],
            "map_longitude": context.get("longitude", ""),
            "map_latitude": context.get("latitude", ""),
        }

    def _task_explain(self) -> Dict:
        started = time.monotonic()
        items = [(sig.evidence, sig.level) for sig in self.state["risk_signals"]]
        drafts = llm_explain_many(items)
        self.state["explanation_drafts"] = drafts
        write_json(str(self.run_dir / "explanation_drafts.json"), drafts)
        llm_generated = sum(1 for d in drafts if d.get("draft_source") == "llm")
        stats = {
            "llm_enabled": get_llm() is not None,
            "drafts": len(drafts),
            "llm_generated": llm_generated,
            "template_fallback": len(drafts) - llm_generated,
            "llm_parse_success_rate": round(llm_generated / len(drafts), 4) if drafts else 0.0,
            "wall_seconds": round(time.monotonic() - started, 3),
        }
        settings = get_llm_settings()
        if settings:
            stats["backend"] = settings.get("backend", "openai")
            stats["concurrency"] = settings.get("concurrency", 1)
        latencies = [d["latency_ms"] for d in drafts if d.get("latency_ms") is not None]
        if latencies:
            lat_sorted = sorted(latencies)
            p95 = lat_sorted[min(len(lat_sorted) - 1, int(0.95 * len(lat_sorted)))]
            stats["latency"] = {
                "calls": len(latencies),
                "avg_ms": round(sum(latencies) / len(latencies), 1),
                "min_ms": round(min(latencies), 1),
                "max_ms": round(max(latencies), 1),
                "p95_ms": round(p95, 1),
            }
        self.state["explanation_stats"] = stats
        return {"drafts": len(drafts), "stats": stats}

    def _task_audit(self) -> Dict:
        by_id = {sig.signal_id: sig for sig in self.state["risk_signals"]}
        drafts_by_id = {d.get("signal_id"): d for d in self.state["explanation_drafts"]}
        results = []
        rejected = []
        for signal_id, sig in by_id.items():
            draft = drafts_by_id.get(signal_id) or template_explain(sig.evidence, sig.level)
            ok, errors = validate_draft(draft, sig.evidence)
            text = draft.get("text", "")
            used_fallback = False
            explanation_source = draft.get("draft_source", "template")
            if not ok:
                rejected.append(signal_id)
                fallback = template_explain(sig.evidence, sig.level)
                ok2, _ = validate_draft(fallback, sig.evidence)
                if ok2:
                    text = fallback["text"]
                    ok = True
                    errors = []
                    used_fallback = True
                    explanation_source = "template_fallback"
                    rejected = [r for r in rejected if r != signal_id]
            results.append(
                {
                    "signal_id": signal_id,
                    "passed": ok,
                    "errors": errors,
                    "text": text,
                    "used_fallback": used_fallback,
                    "draft_source": draft.get("draft_source", ""),
                    "explanation_source": explanation_source,
                }
            )

        for sig in self.state["risk_signals"]:
            for r in results:
                if r["signal_id"] == sig.signal_id:
                    sig.explanation = r["text"] if r["passed"] else ""
                    sig.explanation_source = r["explanation_source"] if r["passed"] else "human_review"

        self.state["explanations"] = results
        write_json(str(self.run_dir / "explanations.json"), results)
        write_json(
            str(self.run_dir / "risk_signals.json"),
            [s.to_dict() for s in self.state["risk_signals"]],
        )
        return {"passed": sum(1 for r in results if r["passed"]), "rejected": rejected}

    def _task_revise(self) -> Dict:
        drafts = []
        for sig in self.state["risk_signals"]:
            draft = template_explain(sig.evidence, sig.level)
            ok, _ = validate_draft(draft, sig.evidence)
            sig.explanation = draft["text"] if ok else ""
            sig.explanation_source = "template_revision" if ok else "human_review"
            drafts.append(draft)
        self.state["explanation_drafts"] = drafts
        write_json(str(self.run_dir / "explanation_drafts.json"), drafts)
        write_json(
            str(self.run_dir / "risk_signals.json"),
            [s.to_dict() for s in self.state["risk_signals"]],
        )
        return {"revised": len(self.state["risk_signals"])}

    def _task_persist(self) -> Dict:
        self._build_summary()
        signals = self.state["risk_signals"]

        db_path = PROJECT_ROOT / "var" / "surveillance.db"
        storage = Storage(str(db_path))
        storage.save_run(
            self.run_id,
            self.state["started_at"],
            time.strftime("%Y-%m-%dT%H:%M:%S"),
            "end",
            self.autonomy_stage,
            self.use_langgraph,
            self.state["summary"],
        )
        storage.save_signals(self.run_id, [s.to_dict() for s in signals])
        storage.close()

        write_json(str(self.run_dir / "summary.json"), self.state["summary"])
        self._write_state()
        return {"persisted": True}

    def _build_summary(self) -> None:
        levels = Counter(s.level for s in self.state["risk_signals"])
        self.state["summary"] = {
            "run_id": self.run_id,
            "total_events": len(self.state["events"]),
            "aggregate_points": len(self.state["aggregates"]),
            "detector_points": len(self.state["detector_points"]),
            "risk_signals": len(self.state["risk_signals"]),
            "risk_levels": dict(levels),
            "autonomy_stage": self.autonomy_stage,
            "use_langgraph": self.use_langgraph,
            "quality": self.state["quality"].get("total_events", 0),
            "source_readiness": {
                source: detail.get("status", "unknown")
                for source, detail in self.state["quality"].get("per_source", {}).items()
            },
            "explanation": self.state.get("explanation_stats", {}),
            "node_times": self.state.get("node_times", {}),
        }

    def _write_state(self) -> None:
        state_out = {
            "run_id": self.run_id,
            "roles": self.roles,
            "summary": self.state["summary"],
            "quality": self.state["quality"],
            "injection_manifest": self.state["injection_manifest"],
            "node_times": self.state.get("node_times", {}),
        }
        write_json(str(self.run_dir / "state.json"), state_out)

    def _write_points_csv(self, fname: str, points: List) -> None:
        path = self.run_dir / fname
        if not points:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write("")
            return
        fieldnames = list(points[0].to_dict().keys())
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for p in points:
                writer.writerow(p.to_dict())

    # ---------------- main flow ----------------

    def _run_with_retry(self, action: str) -> Dict:
        attempts = 0
        while True:
            try:
                return self._execute(action)
            except Exception as exc:
                if (
                    self.autonomy_stage >= 3
                    and action in self.retryable_steps
                    and attempts < self.max_step_retries
                ):
                    attempts += 1
                    self._log_decision(action, "retry", "retry", f"step_error:{type(exc).__name__}:{exc}")
                    continue
                raise

    def _supervise_action(self, action: str, revision_rounds: int) -> int:
        if action in ("explain", "audit") and self.autonomy_stage >= 2 and not self.state["risk_signals"]:
            self._log_decision(action, "skip", "skip", "no_risk_signals")
            return revision_rounds
        if action == "inject" and not getattr(self, "inject_enabled", False):
            return revision_rounds

        self._log_decision(action, action, action, "baseline_order")
        result = self._run_with_retry(action)

        if action == "audit" and result.get("rejected"):
            if self.autonomy_stage >= 2 and revision_rounds < self.max_revision_rounds:
                revision_rounds += 1
                self._log_decision("revise", "revise", "revise", "audit_rejected")
                self._execute("revise")
                self._log_decision("audit", "audit", "audit", "re_audit_after_revise")
                self._execute("audit")
            else:
                for sig in self.state["risk_signals"]:
                    if sig.signal_id in result["rejected"]:
                        sig.requires_human_review = True
                        sig.explanation = ""
        return revision_rounds

    def run(self, inject: bool = False, shape: str = "gradual", magnitude: float = 10.0) -> Dict:
        self.inject_enabled = inject
        self.inject_shape = shape
        self.inject_magnitude = magnitude

        base = ["ingest", "aggregate"]
        if inject:
            base.append("inject")
        base += ["detect", "fuse", "explain", "audit", "persist"]

        idx = 0
        revision_rounds = 0
        while idx < len(base):
            action = base[idx]
            revision_rounds = self._supervise_action(action, revision_rounds)
            idx += 1

        if self.state["summary"] == {}:
            self._task_persist()

        return dict(self.state)


class PipelineRunner(MultiAgentCoordinator):
    pass
