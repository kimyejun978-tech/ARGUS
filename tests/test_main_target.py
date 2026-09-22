import tempfile
import unittest
from pathlib import Path

from main import normalize_target


class NormalizeTargetTests(unittest.TestCase):
    def test_empty_target_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_target("")

    def test_whitespace_target_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_target("   ")

    def test_scheme_less_domain_defaults_to_https(self):
        self.assertEqual(
            normalize_target("example.com"),
            "https://example.com",
        )

    def test_existing_file_becomes_file_uri(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.html"
            path.write_text("<html></html>", encoding="utf-8")

            normalized = normalize_target(str(path))

            self.assertEqual(normalized, path.resolve().as_uri())


if __name__ == "__main__":
    unittest.main()
