import unittest

from run_scale_benchmark import _candidate_key, _record_key


class ScaleBenchmarkKeyTests(unittest.TestCase):
    def test_homoglyph_ground_truth_matches_raw_evidence(self):
        mixed = "SC\u041ePE-SCALE-0032-H"
        record = {
            "path": "/page-0032.html",
            "query": "",
            "technique": "HOMOGLYPH",
            "evidence_text": mixed,
        }
        candidate = {
            "url": "http://127.0.0.1:12345/page-0032.html",
            "technique": "HOMOGLYPH",
            "evidence_text": mixed,
            "normalized_text": "SCOPE-SCALE-0032-H",
        }

        self.assertEqual(_record_key(record), _candidate_key(candidate))


if __name__ == "__main__":
    unittest.main()
