import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from surveillance_agent.api.school_governance import _build_payload


class SchoolGovernanceSummaryTests(unittest.TestCase):
    def test_builds_privacy_preserving_fast_pipeline_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root / "school_model"
            model.mkdir()
            with pd.ExcelWriter(model / "01_import_audit.xlsx") as writer:
                pd.DataFrame([{"dataset": "records", "rows": 3, "columns": 8, "duplicate_rows": 0}]).to_excel(
                    writer, sheet_name="00_file_summary", index=False
                )
                pd.DataFrame([{"severity": "info", "issue": "测试数据", "n": 3}]).to_excel(
                    writer, sheet_name="01_issues", index=False
                )
                pd.DataFrame([{"dataset": "records", "column": "症状", "rows": 3, "missing_n": 0, "missing_pct": 0}]).to_excel(
                    writer, sheet_name="03_missing", index=False
                )
            with pd.ExcelWriter(model / "02_clean_records.xlsx") as writer:
                pd.DataFrame([{"student_id": "secret", "valid_for_model": 1}]).to_excel(writer, sheet_name="cleaned_records", index=False)
                pd.DataFrame().to_excel(writer, sheet_name="rejected_records", index=False)
                pd.DataFrame().to_excel(writer, sheet_name="duplicate_records", index=False)
            episodes = pd.DataFrame(
                [
                    {
                        "episode_id": "episode-1", "student_id": "secret", "onset_date": "2026-10-01",
                        "first_report_date": "2026-10-02", "school_code": "SCH01", "grade": "3",
                        "class_id": "SCH01-3-1", "broad_ari": 1, "fever_ari": 1, "ili_like": 0,
                        "respiratory_absence": 1, "respiratory_visit": 0,
                    }
                ]
            )
            with pd.ExcelWriter(model / "04_syndromic_episodes.xlsx") as writer:
                episodes.to_excel(writer, sheet_name="episodes", index=False)
            for filename, frame in (
                ("05-1_realtime_summary.xlsx", pd.DataFrame([{"date": "2026-10-01", "new_known_primary": 1}])),
                ("05-3_grade_daily.xlsx", pd.DataFrame([{"date": "2026-10-01", "school_code": "SCH01", "grade": "3", "grade_cases": 1, "affected_classes": 1}])),
                ("05-4_school_daily.xlsx", pd.DataFrame([{"date": "2026-10-01", "school_code": "SCH01", "school_cases": 1, "affected_classes": 1}])),
            ):
                with pd.ExcelWriter(model / filename) as writer:
                    frame.to_excel(writer, sheet_name="data", index=False)
            manifest = root / "governance_manifest.json"
            manifest.write_text(json.dumps({"completed_at": "2026-10-02T08:00:00", "input_mode": "private_raw_workbooks", "school": {"modules_completed": 5, "prototype_only": True}}), encoding="utf-8")

            payload = _build_payload(model, manifest)

            self.assertTrue(payload["available"])
            self.assertEqual(payload["pipeline"]["modules_completed"], 5)
            self.assertEqual(payload["overview"]["broad_ari_episodes"], 1)
            self.assertEqual(payload["class_activity"][0]["event_count"], 1)
            self.assertNotIn("student_id", json.dumps(payload, ensure_ascii=False))
            self.assertFalse(payload["model"]["grading"]["available"])


if __name__ == "__main__":
    unittest.main()
