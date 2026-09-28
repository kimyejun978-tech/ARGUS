import unittest

from phishing_analyzer import analyze_phishing_page


def page(url, *, text="", password=False, identifier=True, action=None):
    form = {
        "action": action or url,
        "method": "post",
        "hasPassword": password,
        "identifierCount": 1 if identifier else 0,
    }
    return {
        "url": url,
        "title": text,
        "security_states": [
            {
                "title": text,
                "visibleText": text,
                "headings": [text] if text else [],
                "labels": [],
                "imageAlts": [],
                "ariaLabels": [],
                "placeholders": [],
                "inputTypes": {"password": 1} if password else {"text": 1},
                "forms": [form],
                "iframeUrls": [],
            }
        ],
    }


class PhishingAnalyzerTests(unittest.TestCase):
    def test_official_login_page_is_not_flagged(self):
        finding = analyze_phishing_page(
            page(
                "https://facebook.com/login",
                text="Facebook login account password",
                password=True,
            )
        )
        self.assertIsNone(finding)

    def test_typo_domain_with_credentials_is_flagged(self):
        finding = analyze_phishing_page(
            page(
                "https://twtch-login.test/account",
                text="Twitch login account password",
                password=True,
            )
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "PHISHING_RISK")
        self.assertIn(finding["risk"], {"SUSPICIOUS", "HIGH_RISK"})
        self.assertTrue(any(s["name"] == "DOMAIN_IMPERSONATION" for s in finding["signals"]))

    def test_brand_mismatch_with_login_is_flagged(self):
        finding = analyze_phishing_page(
            page(
                "https://account-center.test/signin",
                text="PayPal sign in account password",
                password=True,
            )
        )
        self.assertIsNotNone(finding)
        self.assertTrue(any(s["name"] == "BRAND_DOMAIN_MISMATCH" for s in finding["signals"]))

    def test_generic_external_sso_without_brand_mismatch_is_not_flagged(self):
        finding = analyze_phishing_page(
            page(
                "https://school.example.test/login",
                text="Sign in to student portal",
                password=True,
                action="https://identity.example.test/session",
            )
        )
        self.assertIsNone(finding)

    def test_unrelated_page_is_not_flagged(self):
        self.assertIsNone(
            analyze_phishing_page(
                page(
                    "https://civic-service.test/news",
                    text="시민 소식 안내",
                    password=False,
                    identifier=False,
                )
            )
        )


    def test_ascii_brand_alias_requires_word_boundary(self):
        finding = analyze_phishing_page(
            page(
                "https://fruit.example.test/login",
                text="Pineapple account login",
                password=True,
            )
        )
        self.assertIsNone(finding)


if __name__ == "__main__":
    unittest.main()
