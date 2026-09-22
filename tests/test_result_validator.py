import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from json_exporter import export_result_json
from result_validator import (
    ResultValidationError,
    main,
    validate_result_file,
)


def _valid_result():
    return {
        "meta": {
            "topic": "TOPIC",
            "entry_url": "https://example.com/",
            "started_at": "2026-09-22T10:00:00+09:00",
            "finished_at": "2026-09-22T10:00:01+09:00",
            "elapsed_sec": 1.0,
            "tool_version": "0.1.0",
        },
        "findings": [
            {
                "id": "f_001",
                "url": "https://example.com/post",
                "is_violation": True,
                "location": "html > body > p:nth-of-type(1)",
                "evidence_text": "sample",
                "technique": "TRANSPARENT",
            }
        ],
    }


class ResultValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def _write(self, result, name="result.json"):
        path = self.root / name
        path.write_text(
            json.dumps(result, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def _assert_invalid(self, result, message):
        with self.assertRaisesRegex(ResultValidationError, message):
            validate_result_file(self._write(result))

    def test_valid_result(self):
        result = validate_result_file(self._write(_valid_result()))
        self.assertEqual(len(result["findings"]), 1)

    def test_empty_findings_are_allowed(self):
        result = _valid_result()
        result["findings"] = []
        self.assertEqual(
            validate_result_file(self._write(result))["findings"],
            [],
        )

    def test_missing_meta(self):
        result = _valid_result()
        del result["meta"]
        self._assert_invalid(result, "missing required field: meta")

    def test_missing_findings(self):
        result = _valid_result()
        del result["findings"]
        self._assert_invalid(result, "missing required field: findings")

    def test_findings_must_be_a_list(self):
        result = _valid_result()
        result["findings"] = {}
        self._assert_invalid(result, "findings must be a list")

    def test_disallowed_technique(self):
        result = _valid_result()
        result["findings"][0]["technique"] = "UNKNOWN"
        self._assert_invalid(result, "technique must be one of")

    def test_missing_finding_required_field(self):
        result = _valid_result()
        del result["findings"][0]["url"]
        self._assert_invalid(result, "missing required field: url")

    def test_empty_url(self):
        result = _valid_result()
        result["findings"][0]["url"] = "  "
        self._assert_invalid(result, "url must be a non-empty string")

    def test_empty_location(self):
        result = _valid_result()
        result["findings"][0]["location"] = ""
        self._assert_invalid(result, "location must be a non-empty string")

    def test_duplicate_triplet(self):
        result = _valid_result()
        result["findings"].append(dict(result["findings"][0]))
        self._assert_invalid(result, "duplicates")

    def test_utf8_bom_is_rejected(self):
        path = self.root / "bom.json"
        path.write_bytes(
            b"\xef\xbb\xbf"
            + json.dumps(_valid_result()).encode("utf-8")
        )
        with self.assertRaisesRegex(ResultValidationError, "BOM"):
            validate_result_file(path)

    def test_malformed_json_has_clear_error_and_nonzero_exit(self):
        path = self.root / "malformed.json"
        path.write_text('{"meta": ', encoding="utf-8")
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            exit_code = main([str(path)])

        self.assertNotEqual(exit_code, 0)
        self.assertIn("FAIL: malformed JSON", stderr.getvalue())

    def test_negative_elapsed_sec(self):
        result = _valid_result()
        result["meta"]["elapsed_sec"] = -0.1
        self._assert_invalid(result, "greater than or equal to 0")

    def test_production_exporter_output_passes_validator(self):
        output_path = self.root / "exported-result.json"
        candidate = {
            "url": "https://example.com/post",
            "location": "html > body > p:nth-of-type(1)",
            "evidence_text": "sample",
            "technique": "HOMOGLYPH",
            "is_violation": True,
        }

        exported_path, exported = export_result_json(
            entry_url="https://example.com/",
            started_at="2026-09-22T10:00:00+09:00",
            finished_at="2026-09-22T10:00:01+09:00",
            elapsed_sec=1.0,
            candidate_groups=[[candidate]],
            output_path=output_path,
        )

        validated = validate_result_file(exported_path)
        self.assertEqual(validated, exported)
        self.assertFalse(Path(exported_path).read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_success_cli_prints_pass_and_returns_zero(self):
        path = self._write(_valid_result())
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = main([str(path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("PASS:", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
