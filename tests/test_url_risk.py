import unittest

from url_risk import analyze_url_risk


class UrlRiskTests(unittest.TestCase):
    def test_official_brand_domains_are_not_flagged(self):
        self.assertEqual(analyze_url_risk("https://facebook.com"), [])
        self.assertEqual(analyze_url_risk("https://help.twitch.tv"), [])

    def test_ascii_typo_domain_is_flagged(self):
        findings = analyze_url_risk("https://twtch-login.test/account")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["brand"], "Twitch")
        self.assertEqual(findings[0]["signal"], "DOMAIN_TYPOSQUAT")

    def test_brand_idn_on_unofficial_domain_is_flagged(self):
        findings = analyze_url_risk("https://페이스북.test")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["brand"], "Facebook")
        self.assertEqual(findings[0]["signal"], "BRAND_ALIAS")

    def test_punycode_brand_idn_is_decoded_before_analysis(self):
        hostname = "페이스북.test".encode("idna").decode("ascii")
        findings = analyze_url_risk(f"https://{hostname}")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["display_hostname"], "페이스북.test")

    def test_generic_idn_is_not_flagged_only_for_being_unicode(self):
        self.assertEqual(analyze_url_risk("https://예시.test"), [])

    def test_unrelated_domain_is_not_flagged(self):
        self.assertEqual(analyze_url_risk("https://civic-service.test"), [])

    def test_brand_name_in_deceptive_subdomain_is_flagged(self):
        findings = analyze_url_risk("https://facebook.login-example.test")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["brand"], "Facebook")


if __name__ == "__main__":
    unittest.main()
