from __future__ import annotations

import unittest

from surveillance_agent.adapters import detect_adapter_from_file
from surveillance_agent.adapters.care_home import CareHomeAdapter, HospitalAdapter
from surveillance_agent.adapters.syndromes import map_syndromes
from surveillance_agent.agent import MultiAgentCoordinator
from surveillance_agent.agent.explanation import template_explain, validate_draft
from surveillance_agent.config import load_config, resolve_source_file
from surveillance_agent.domain import RiskEvidence
from surveillance_agent.models import build_detectors, fuse_alarms
from surveillance_agent.utils import get_salt


class TestAdapters(unittest.TestCase):
    def test_detect_hospital_schema(self):
        cfg = load_config()
        path = resolve_source_file(cfg, "hospital")
        self.assertIsNotNone(detect_adapter_from_file(str(path)))
        self.assertIs(detect_adapter_from_file(str(path)), HospitalAdapter)

    def test_detect_care_home_schema(self):
        cfg = load_config()
        path = resolve_source_file(cfg, "care_home")
        self.assertIs(detect_adapter_from_file(str(path)), CareHomeAdapter)

    def test_syndrome_mapping(self):
        self.assertIn("respiratory", map_syndromes("流行性感冒"))
        self.assertIn("respiratory", map_syndromes("支气管炎"))
        self.assertIn("digestive", map_syndromes("慢性胃炎"))
        self.assertEqual(map_syndromes("糖尿病"), ["other"])

    def test_syndrome_mapping_exclusive(self):
        self.assertEqual(map_syndromes("发热 咳嗽"), ["respiratory"])
        self.assertEqual(map_syndromes("高热 腹痛 腹泻"), ["digestive"])
        self.assertEqual(map_syndromes("高血压 伴发热"), ["fever"])
        self.assertEqual(map_syndromes("发热待查"), ["fever"])

    def test_aggregate_excludes_other(self):
        from surveillance_agent.aggregation import aggregate
        from surveillance_agent.domain import SurveillanceEvent

        events = [
            SurveillanceEvent(
                event_id=f"e{i}", source="hospital", org_id="h1", province="P",
                city="", district="", event_date="2022-01-03",
                diagnosis="糖尿病", symptoms="", fields={},
            )
            for i in range(3)
        ]
        scenarios = {"hospital": {"scope_type": "province", "freq": "week"}}
        points = aggregate(events, scenarios, include_other=False)
        self.assertTrue(all(p.syndrome != "other" for p in points))
        points2 = aggregate(events, scenarios, include_other=True)
        self.assertTrue(any(p.syndrome == "other" for p in points2))

    def test_events_generated_and_unique(self):
        cfg = load_config()
        salt = get_salt(cfg["privacy"]["default_salt"])
        events = []
        for source in ("care_home", "hospital"):
            path = resolve_source_file(cfg, source)
            adapter_cls = detect_adapter_from_file(str(path))
            adapter = adapter_cls()
            from surveillance_agent.adapters.base import read_rows
            for row in read_rows(str(path)):
                ev = adapter.parse(row, salt)
                if ev is not None:
                    events.append(ev)
        self.assertEqual(len(events), 2644)
        ids = [e.event_id for e in events]
        self.assertEqual(len(ids), len(set(ids)))

    def test_required_field_missing_rejected(self):
        from surveillance_agent.agent.schema_mapping import validate_mapping

        ok, errors = validate_mapping("hospital", {"就诊日期": "就诊日期"})
        self.assertFalse(ok)
        self.assertTrue(any("missing_required" in e for e in errors))

        ok2, errors2 = validate_mapping(
            "hospital", {"门诊流水号": "门诊流水号", "西医诊断名称": "西医诊断名称", "就诊日期": "就诊日期"}
        )
        self.assertTrue(ok2, errors2)


class TestModels(unittest.TestCase):
    def test_detectors_flag_anomaly(self):
        cfg = load_config()
        detectors = build_detectors(cfg["detection"])
        history = [5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        for name, det in detectors.items():
            score, _, _, alarm = det.compute(history, 50.0)
            self.assertTrue(alarm, f"{name} should flag anomaly")

    def test_fusion_levels(self):
        det_res = {
            "ewma": {"score": 5.0, "threshold": 3.0, "alarm": True},
            "cusum": {"score": 6.0, "threshold": 4.0, "alarm": True},
            "shewhart": {"score": 4.0, "threshold": 3.0, "alarm": True},
        }
        self.assertEqual(fuse_alarms(det_res), "high")
        det_res["cusum"]["alarm"] = False
        det_res["cusum"]["score"] = 1.0
        det_res["shewhart"]["alarm"] = False
        det_res["shewhart"]["score"] = 1.0
        self.assertEqual(fuse_alarms(det_res), "medium")

    def test_injection_manifest_auditable(self):
        from surveillance_agent.domain import AggregatePoint
        from surveillance_agent.research.injection import inject_anomalies

        points = [
            AggregatePoint(
                source="hospital", scope_type="province", scope_key="湖北省",
                syndrome="respiratory", date=f"2022-W{w:02d}", count=5,
            )
            for w in range(1, 21)
        ]
        injected, manifest = inject_anomalies(points, shape="spike", magnitude=10.0, num_series=1)
        self.assertTrue(manifest["enabled"])
        self.assertGreater(len(manifest["injections"]), 0)
        for inj in manifest["injections"]:
            self.assertEqual(inj["true_label"], 1)
            self.assertIn("original", inj)
            self.assertIn("injected", inj)
            self.assertGreater(inj["injected"], inj["original"])


class TestExplanation(unittest.TestCase):
    def _evidence(self):
        return RiskEvidence(
            signal_id="s1",
            source="hospital",
            scope_type="province",
            scope_key="湖北省",
            syndrome="respiratory",
            date="2026-W01",
            observed=12.0,
            expected=5.0,
            scores={"ewma": 4.0, "cusum": 5.0, "shewhart": 3.5},
            thresholds={"ewma": 3.0, "cusum": 4.0, "shewhart": 3.0},
            alarms={"ewma": True, "cusum": True, "shewhart": True},
            model_version="1.0.0",
        )

    def test_template_passes(self):
        ev = self._evidence()
        draft = template_explain(ev)
        ok, errors = validate_draft(draft, ev)
        self.assertTrue(ok, errors)

    def test_draft_source_tagged(self):
        from surveillance_agent.agent.explanation import llm_explain

        ev = self._evidence()
        draft = template_explain(ev)
        self.assertEqual(draft["draft_source"], "template")
        draft2 = llm_explain(ev)
        self.assertEqual(draft2["draft_source"], "template")

    def test_llm_explain_records_latency(self):
        import surveillance_agent.agent.explanation as explanation_mod

        def fake_llm(prompt):
            return '{"text": "解释", "claims": [{"field": "observed", "value": 12.0}]}'

        original = explanation_mod.get_llm
        explanation_mod.get_llm = lambda: fake_llm
        try:
            draft = explanation_mod.llm_explain(self._evidence())
        finally:
            explanation_mod.get_llm = original
        self.assertEqual(draft["draft_source"], "llm")
        self.assertIn("latency_ms", draft)
        self.assertGreaterEqual(draft["latency_ms"], 0)

    def test_llm_explain_rebuilds_claims_from_evidence(self):
        import surveillance_agent.agent.explanation as explanation_mod

        def fake_llm(prompt):
            return '{"text": "监测数据出现变化，建议继续观察。", "claims": []}'

        original = explanation_mod.get_llm
        explanation_mod.get_llm = lambda: fake_llm
        try:
            draft = explanation_mod.llm_explain(self._evidence())
        finally:
            explanation_mod.get_llm = original
        self.assertEqual(draft["draft_source"], "llm")
        self.assertEqual([c["field"] for c in draft["claims"]], ["observed", "expected", "syndrome", "date"])
        ok, errors = validate_draft(draft, self._evidence())
        self.assertTrue(ok, errors)

    def test_llm_prompt_contains_real_values_not_placeholders(self):
        import surveillance_agent.agent.explanation as explanation_mod

        captured = {}

        def fake_llm(prompt):
            captured["prompt"] = prompt
            return '{"text": "监测值高于预期，建议继续观察。"}'

        original = explanation_mod.get_llm
        explanation_mod.get_llm = lambda: fake_llm
        try:
            draft = explanation_mod.llm_explain(self._evidence())
        finally:
            explanation_mod.get_llm = original
        self.assertEqual(draft["draft_source"], "llm")
        self.assertNotIn('"value": 数字', captured["prompt"])
        self.assertIn('"value": 12.0', captured["prompt"])

    def test_forged_number_rejected(self):
        ev = self._evidence()
        draft = template_explain(ev)
        for c in draft["claims"]:
            if c["field"] == "observed":
                c["value"] = 999.0
        ok, errors = validate_draft(draft, ev)
        self.assertFalse(ok)
        self.assertTrue(any("mismatch" in e for e in errors))

    def test_audit_rejects_forged_and_revise(self):
        ev = self._evidence()
        draft = template_explain(ev)
        for c in draft["claims"]:
            if c["field"] == "observed":
                c["value"] = 999.0
        ok, errors = validate_draft(draft, ev)
        self.assertFalse(ok)
        self.assertTrue(any("mismatch" in e for e in errors))
        redone = template_explain(ev)
        ok2, _ = validate_draft(redone, ev)
        self.assertTrue(ok2)


class TestEndToEnd(unittest.TestCase):
    def test_full_pipeline(self):
        cfg = load_config()
        coord = MultiAgentCoordinator(cfg=cfg, autonomy_stage=1)
        result = coord.run(inject=True, shape="gradual", magnitude=10.0)
        self.assertEqual(result["summary"]["total_events"], 2644)
        self.assertGreater(result["summary"]["risk_signals"], 0)
        self.assertTrue(result["summary"]["use_langgraph"] is False)

    def test_messages_correlated(self):
        from surveillance_agent.utils import read_jsonl
        cfg = load_config()
        coord = MultiAgentCoordinator(cfg=cfg, autonomy_stage=1)
        coord.run(inject=False)
        msgs = read_jsonl(str(coord.msg_log))
        self.assertGreater(len(msgs), 0)
        cids = {m["correlation_id"] for m in msgs}
        kinds = {m["payload"].get("kind") for m in msgs}
        self.assertIn("request", kinds)
        self.assertIn("response", kinds)

    def test_stage1_records_baseline_only(self):
        from surveillance_agent.utils import read_jsonl
        cfg = load_config()
        coord = MultiAgentCoordinator(cfg=cfg, autonomy_stage=1)
        coord.run(inject=False)
        decisions = read_jsonl(str(coord.decision_log))
        self.assertGreater(len(decisions), 0)
        for d in decisions:
            self.assertEqual(d["actual"], d["baseline"])

    def test_stage2_end_to_end(self):
        cfg = load_config()
        coord = MultiAgentCoordinator(cfg=cfg, autonomy_stage=2)
        result = coord.run(inject=True, shape="gradual", magnitude=10.0)
        self.assertEqual(result["summary"]["total_events"], 2644)
        self.assertGreater(result["summary"]["risk_signals"], 0)
        self.assertEqual(result["summary"]["autonomy_stage"], 2)


class TestImprovements(unittest.TestCase):
    def test_cli_formats_total_elapsed_time(self):
        from surveillance_agent.cli import _format_elapsed

        self.assertEqual(_format_elapsed(0), "00:00:00.0 (0.0 秒)")
        self.assertEqual(_format_elapsed(3661.25), "01:01:01.2 (3661.2 秒)")

    def test_cusum_resets_after_alarm(self):
        from surveillance_agent.models.detectors import CUSUM

        det = CUSUM({"k": 0.5, "h": 4.0})
        values = list(range(5, 35))
        alarms = []
        for i in range(len(values)):
            _, _, _, alarm = det.compute(values[:i], values[i])
            alarms.append(alarm)
        first = next((i for i, a in enumerate(alarms) if a), None)
        self.assertIsNotNone(first, "CUSUM should alarm on an upward drift")
        self.assertFalse(all(alarms[first:]), "CUSUM must reset after alarm, not persist on every later point")

    def test_fusion_merges_alarm_runs(self):
        from surveillance_agent.domain import DetectorPoint

        cfg = load_config()
        coord = MultiAgentCoordinator(cfg=cfg, autonomy_stage=0)
        points = [
            DetectorPoint(
                source="hospital", scope_type="province", scope_key="X", syndrome="respiratory",
                date=f"2026-W0{i}", observed=20.0, expected=5.0,
                score=5.0, threshold=3.0, detector="shewhart", alarm=True,
            )
            for i in range(1, 4)
        ]
        points.append(
            DetectorPoint(
                source="hospital", scope_type="province", scope_key="X", syndrome="respiratory",
                date="2026-W04", observed=1.0, expected=5.0,
                score=0.2, threshold=3.0, detector="shewhart", alarm=False,
            )
        )
        coord.state["detector_points"] = points
        coord._task_fuse()
        sigs = coord.state["risk_signals"]
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].evidence.run_dates, ["2026-W01", "2026-W02", "2026-W03"])

    def test_audit_fallback_writeback(self):
        cfg = load_config()
        coord = MultiAgentCoordinator(cfg=cfg, autonomy_stage=0)
        coord.run(inject=True, shape="spike", magnitude=10.0)
        self.assertGreater(len(coord.state["risk_signals"]), 0)
        for d in coord.state["explanation_drafts"]:
            for c in d.get("claims", []):
                if c["field"] == "observed":
                    c["value"] = 999.0
        result = coord._task_audit()
        self.assertEqual(result["rejected"], [])
        for sig in coord.state["risk_signals"]:
            self.assertTrue(sig.explanation, "fallback explanation should be written back")

    def test_adaptive_model_selection(self):
        from surveillance_agent.agent.model_policy import select_models

        self.assertEqual(select_models({"values": [1, 1, 1, 1]}), ["shewhart"])
        self.assertEqual(select_models({"values": [10] * 15}), ["ewma", "cusum", "shewhart"])
        self.assertEqual(select_models({"values": [1] * 8 + [100]}), ["ewma", "shewhart"])

    def test_static_path_traversal_rejected(self):
        from surveillance_agent.api.fallback_server import Handler

        handler = Handler()
        res = handler.dispatch("GET", "/static/../../../requirements.txt", b"")
        self.assertEqual(res[0], 404)
        res2 = handler.dispatch("GET", "/static/index.html", b"")
        self.assertEqual(res2[0], 200)

    def test_extract_json_from_llm_output(self):
        from surveillance_agent.agent.llm import extract_json

        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('前缀文本 {"a": 1, "b": "x"} 后缀文本'), {"a": 1, "b": "x"})
        self.assertIsNone(extract_json("没有 json"))
        self.assertIsNone(extract_json(""))

    def test_extract_json_lenient(self):
        from surveillance_agent.agent.llm import extract_json

        self.assertEqual(extract_json("{'a': 1, 'b': 'x'}"), {"a": 1, "b": "x"})
        self.assertEqual(extract_json('{"a": 1, "b": [1, 2,],}'), {"a": 1, "b": [1, 2]})
        self.assertEqual(extract_json('好的，这是结果：{"a": None, "b": True}'), {"a": None, "b": True})
        self.assertEqual(
            extract_json('{"text": "解释", "claims": [{"field": "observed", "value": 5.0"}]}'),
            {"text": "解释", "claims": [{"field": "observed", "value": 5.0}]},
        )


if __name__ == "__main__":
    unittest.main()
