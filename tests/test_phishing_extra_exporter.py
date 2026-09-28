import unittest

from extra_exporter import build_auxiliary_findings


class PhishingExtraExporterTests(unittest.TestCase):
    def test_phishing_risk_is_kept_auxiliary(self):
        finding = {
            "type": "PHISHING_RISK",
            "risk": "HIGH_RISK",
            "page_url": "https://account-center.test/signin",
            "hostname": "account-center.test",
            "score": 0.83,
            "signals": [{"name": "BRAND_DOMAIN_MISMATCH", "weight": 0.32}],
            "reason": "브랜드/도메인 불일치",
            "blocked": False,
        }
        result = build_auxiliary_findings([], phishing_findings=[finding])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "PHISHING_RISK")
        self.assertEqual(result[0]["risk"], "HIGH_RISK")
        self.assertEqual(result[0]["score"], 0.83)
        self.assertTrue(result[0]["signals"])


if __name__ == "__main__":
    unittest.main()
