import json
import tempfile
import unittest
from pathlib import Path

from extra_exporter import build_auxiliary_findings, export_result_extra_json


class ExtraExporterTests(unittest.TestCase):
    def test_build_auxiliary_findings_deduplicates_events(self):
        event = {
            "type": "AUTO_DOWNLOAD_ATTEMPT",
            "risk": "SUSPICIOUS",
            "page_url": "https://example.test/page",
            "requested_url": "https://example.test/page",
            "download_url": "https://example.test/files/payload.bin",
            "suggested_filename": "payload.bin",
            "page_triggered": True,
            "blocked": True,
        }

        findings = build_auxiliary_findings([event, dict(event)])

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["risk"], "SUSPICIOUS")
        self.assertTrue(findings[0]["blocked"])

    def test_export_is_separate_from_official_findings(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "result_extra.json"
            path, data = export_result_extra_json(
                entry_url="https://example.test",
                download_events=[],
                output_path=output,
            )

            self.assertEqual(path, output.resolve())
            self.assertFalse(data["meta"]["official_findings"])
            self.assertEqual(data["auxiliary_findings"], [])

            loaded = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(loaded, data)


if __name__ == "__main__":
    unittest.main()
