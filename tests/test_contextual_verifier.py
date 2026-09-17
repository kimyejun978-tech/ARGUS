import unittest

from verifier.contextual import verify_candidates


class ContextualVerifierTests(unittest.TestCase):
    def test_repeated_normal_dialog_text_is_rejected(self):
        urls = [f"https://example.com/page-{index}" for index in range(4)]
        selector = "section#social-apps-modal > div > ul > li > p"

        candidates = []
        pages = []

        for url in urls:
            candidates.append(
                {
                    "url": url,
                    "location": selector,
                    "evidence_text": "Telegram",
                    "technique": "TRANSPARENT",
                    "reason": [
                        "opacity가 0인 요소 또는 부모 요소에 의해 숨겨짐"
                    ],
                    "opacity_source": "dialog#apps",
                    "scan_pass": "desktop-initial",
                }
            )
            pages.append(
                {
                    "url": url,
                    "title": "Popular social apps",
                    "elements": [
                        {"selector": selector, "text": "Telegram"},
                        {
                            "selector": "section#social-apps-modal > div > ul > li:nth-of-type(2) > p",
                            "text": "Instagram",
                        },
                        {
                            "selector": "section#social-apps-modal > div > ul > li:nth-of-type(3) > p",
                            "text": "WhatsApp",
                        },
                    ],
                }
            )

        verified, rejected = verify_candidates([candidates], pages=pages)

        self.assertEqual(len(verified), 0)
        self.assertEqual(len(rejected), 4)
        self.assertTrue(all(item["is_violation"] is False for item in rejected))
        self.assertTrue(
            all(item["verification_status"] == "BENIGN_LIKELY" for item in rejected)
        )

    def test_one_off_hidden_known_context_can_pass(self):
        url = "https://example.com/notice/1"
        selector = "main > article > p.hidden"
        candidate = {
            "url": url,
            "location": selector,
            "evidence_text": "카지노 이벤트 가입 후 혜택 지급",
            "technique": "TRANSPARENT",
            "reason": ["텍스트 색상이 완전히 투명함"],
            "opacity_source": selector,
            "scan_pass": "desktop-initial",
        }
        pages = [
            {
                "url": url,
                "title": "게시글",
                "elements": [
                    {"selector": selector, "text": candidate["evidence_text"]},
                    {
                        "selector": "main > article > h1",
                        "text": "이벤트 안내",
                    },
                ],
            }
        ]

        verified, rejected = verify_candidates([[candidate]], pages=pages)

        self.assertEqual(len(verified), 1)
        self.assertEqual(len(rejected), 0)
        self.assertTrue(verified[0]["is_violation"])
        self.assertEqual(verified[0]["verification_status"], "CONFIRMED")

    def test_english_known_context_uses_multilingual_branch(self):
        url = "https://example.com/news/7"
        selector = "main > article > span.hidden"
        candidate = {
            "url": url,
            "location": selector,
            "evidence_text": "hidden promotion join now claim bonus",
            "technique": "TRANSPARENT",
            "reason": ["텍스트 색상이 완전히 투명함"],
            "opacity_source": selector,
            "scan_pass": "desktop-initial",
        }
        pages = [
            {
                "url": url,
                "title": "News",
                "elements": [
                    {"selector": selector, "text": candidate["evidence_text"]},
                ],
            }
        ]

        verified, rejected = verify_candidates([[candidate]], pages=pages)

        self.assertEqual(len(verified), 1)
        self.assertEqual(len(rejected), 0)
        self.assertEqual(verified[0]["verification_status"], "CONFIRMED")
        self.assertIn(
            verified[0]["semantic_backend"],
            {"char-ngram-multilingual", "local-sentence-transformer"},
        )

    def test_unknown_text_can_survive_via_open_set(self):
        urls = [f"https://example.com/page-{index}" for index in range(6)]
        target_url = urls[0]
        selector = "main > article > span.x"
        candidate = {
            "url": target_url,
            "location": selector,
            "evidence_text": "QZXV NRMK portal",
            "technique": "HOMOGLYPH",
            "reason": ["한 단어 안에 라틴 문자와 유사한 키릴/그리스 문자가 혼합됨"],
            "scan_pass": "mobile-scrolled",
        }
        pages = [
            {
                "url": url,
                "title": "Page",
                "elements": (
                    [{"selector": selector, "text": candidate["evidence_text"]}]
                    if url == target_url
                    else [{"selector": "main > p", "text": "ordinary content"}]
                ),
            }
            for url in urls
        ]

        verified, rejected = verify_candidates([[candidate]], pages=pages)

        self.assertEqual(len(verified), 1)
        self.assertEqual(len(rejected), 0)
        self.assertEqual(verified[0]["verification_status"], "SUSPICIOUS")
        self.assertGreaterEqual(verified[0]["open_set_score"], 0.56)

    def test_normal_navigation_text_is_not_confirmed_by_one_semantic_branch(self):
        url = "https://example.com/place/1"
        candidate = {
            "url": url,
            "location": "div#app > div > a:nth-of-type(1)",
            "evidence_text": "본문 바로가기",
            "technique": "OFFSCREEN",
            "reason": ["요소가 비정상적으로 먼 화면 밖 좌표에 배치됨"],
            "rect": {"x": 0, "y": -5000, "width": 108, "height": 31},
            "scan_pass": "desktop-scrolled",
        }
        pages = [
            {
                "url": url,
                "title": "장소 정보",
                "elements": [
                    {
                        "selector": candidate["location"],
                        "text": candidate["evidence_text"],
                    },
                    {"selector": "div#app > main > h1", "text": "장소 정보"},
                ],
            }
        ]

        verified, rejected = verify_candidates([[candidate]], pages=pages)

        self.assertEqual(len(verified), 0)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["verification_status"], "BENIGN_LIKELY")
        self.assertFalse(rejected[0]["is_violation"])

    def test_local_sample_marker_still_passes_regression_fixture(self):
        candidate = {
            "url": "http://127.0.0.1:8000/test.html",
            "location": "body > p",
            "evidence_text": "SAMPLE TEST",
            "technique": "JAMO",
            "reason": ["회귀 테스트"],
            "scan_pass": "desktop-initial",
        }

        verified, rejected = verify_candidates([[candidate]], pages=[])

        self.assertEqual(len(verified), 1)
        self.assertEqual(len(rejected), 0)
        self.assertEqual(verified[0]["verification_score"], 1.0)
        self.assertEqual(verified[0]["verification_status"], "CONFIRMED")


if __name__ == "__main__":
    unittest.main()
