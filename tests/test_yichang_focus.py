from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook

from surveillance_agent.adapters.yichang_focus import FILES, ingest_yichang_focus_bundle


def write_xlsx(path: Path, headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


class TestYichangFocusBundle(unittest.TestCase):
    def test_exact_deidentified_link_creates_care_institution_event(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            write_xlsx(
                root / FILES["care_roster"],
                ["local_id_hash", "org_code", "org_name", "org_district", "leave_time"],
                [["person-a", "org-1", "示例养老机构", "西陵区", ""]],
            )
            write_xlsx(
                root / FILES["outpatient_record"],
                ["md5(`t`.`Local_ID`)", "menzhenliushuihao", "jiuzhenriqi", "zhusu", "xianbingshi"],
                [["person-a", "visit-1", "20260812103000", "发热", "咳嗽"]],
            )
            write_xlsx(
                root / FILES["outpatient_diagnosis"],
                ["md5(`t`.`Local_ID`)", "menzhenliushuihao", "jbzdbm", "jbzdmc", "zhenduanriqi", "yiliaojigoudaima"],
                [["person-a", "visit-1", "J18.900", "肺炎", "", "hospital-1"]],
            )

            events, report = ingest_yichang_focus_bundle(
                str(root), "test-salt", ["local_id_hash"]
            )

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_date, "2026-08-12")
            self.assertEqual(events[0].fields["place_type"], "care_institution")
            self.assertEqual(events[0].fields["org_name"], "示例养老机构")
            self.assertTrue(events[0].fields["care_resident_linked"])
            self.assertEqual(report["linkage"]["clinical_to_roster_exact_matches"], 1)
            self.assertEqual(report["status"], "ok")

    def test_missing_shared_key_never_guesses_care_institution(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            write_xlsx(
                root / FILES["care_roster"],
                ["id", "org_code", "org_name"],
                [["1", "org-1", "示例养老机构"]],
            )
            write_xlsx(
                root / FILES["outpatient_diagnosis"],
                ["md5(`t`.`Local_ID`)", "menzhenliushuihao", "jbzdmc", "zhenduanriqi", "yiliaojigoudaima"],
                [["unrelated", "visit-1", "肺炎", "20200000000000", "hospital-1"]],
            )

            events, report = ingest_yichang_focus_bundle(
                str(root), "test-salt", ["local_id_hash"]
            )

            self.assertEqual(events, [])
            self.assertEqual(report["linkage"]["usable_roster_person_keys"], 0)
            self.assertIn("care_roster_missing_shared_deidentified_person_key", report["limitations"])
            self.assertIn("diagnosis_dates_invalid_or_masked", report["limitations"])


if __name__ == "__main__":
    unittest.main()
