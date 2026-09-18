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

    def test_stable_unknown_homoglyph_survives_open_set(self):
        # open-set의 사이트 희귀성 신뢰도는 8페이지부터 최대치가 된다.
        # 이 테스트는 안정적인 5-pass 관측이 감점되지 않는 회귀를 확인한다.
        urls = [f"https://example.com/page-{index}" for index in range(8)]
        target_url = urls[0]
        selector = "main > article > p.stable-hidden"
        passes = [
            "desktop-initial",
            "desktop-settled",
            "desktop-scrolled",
            "mobile-settled",
            "mobile-scrolled",
        ]
        candidates = [
            {
                "url": target_url,
                "location": selector,
                "evidence_text": "QОLOWE WJOGZ",
                "technique": "HOMOGLYPH",
                "normalized_text": "QOLOWE WJOGZ",
                "reason": [
                    "한 단어 안에 라틴 문자와 유사한 키릴/그리스 문자가 혼합됨"
                ],
                "scan_pass": pass_name,
            }
            for pass_name in passes
        ]
        pages = [
            {
                "url": url,
                "title": "Page",
                "elements": (
                    [{"selector": selector, "text": "QОLOWE WJOGZ"}]
                    if url == target_url
                    else [{"selector": "main > p", "text": "ordinary content"}]
                ),
            }
            for url in urls
        ]

        verified, rejected = verify_candidates([candidates], pages=pages)

        self.assertEqual(len(verified), 1)
        self.assertEqual(len(rejected), 0)
        self.assertEqual(verified[0]["verification_status"], "SUSPICIOUS")
        self.assertEqual(len(verified[0]["scan_passes"]), 5)
        self.assertGreaterEqual(verified[0]["open_set_score"], 0.60)

    def test_opacity_zero_with_zero_width_can_survive_open_set(self):
        urls = [f"https://example.com/page-{index}" for index in range(6)]
        target_url = urls[0]
        selector = "main > article > p.opacity-hidden"
        passes = [
            "desktop-initial",
            "desktop-settled",
            "desktop-scrolled",
            "mobile-settled",
            "mobile-scrolled",
        ]
        candidates = [
            {
                "url": target_url,
                "location": selector,
                "evidence_text": "MYOFB\u200b DQOJ 100",
                "technique": "TRANSPARENT",
                "reason": ["opacity가 0인 요소 또는 부모 요소에 의해 숨겨짐"],
                "opacity_source": selector,
                "scan_pass": pass_name,
            }
            for pass_name in passes
        ]
        pages = [
            {
                "url": url,
                "title": "Page",
                "elements": (
                    [{"selector": selector, "text": "MYOFB\u200b DQOJ 100"}]
                    if url == target_url
                    else [{"selector": "main > p", "text": "ordinary content"}]
                ),
            }
            for url in urls
        ]

        verified, rejected = verify_candidates([candidates], pages=pages)

        self.assertEqual(len(verified), 1)
        self.assertEqual(len(rejected), 0)
        self.assertEqual(verified[0]["verification_status"], "SUSPICIOUS")
        self.assertGreaterEqual(verified[0]["structure_score"], 0.60)
        self.assertGreaterEqual(verified[0]["open_set_score"], 0.66)

    def test_one_pass_css_hiding_is_treated_as_transient(self):
        urls = [f"https://example.com/page-{index}" for index in range(8)]
        target_url = urls[0]
        selector = "main > section > p.transient"
        candidate = {
            "url": target_url,
            "location": selector,
            "evidence_text": "ordinary transient panel text",
            "technique": "TRANSPARENT",
            "reason": ["opacity가 0인 요소 또는 부모 요소에 의해 숨겨짐"],
            "opacity_source": selector,
            "scan_pass": "desktop-initial",
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

        self.assertEqual(len(verified), 0)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["verification_status"], "BENIGN_LIKELY")
        self.assertLess(rejected[0]["open_set_score"], 0.66)

    def test_css_only_overlap_is_not_independent_multi_technique_evidence(self):
        urls = [f"https://example.com/page-{index}" for index in range(8)]
        target_url = urls[0]
        selector = "main > section > p.hidden"
        text = "ordinary panel label"
        transparent = {
            "url": target_url,
            "location": selector,
            "evidence_text": text,
            "technique": "TRANSPARENT",
            "reason": ["텍스트 색상과 배경 색상이 동일함"],
            "scan_pass": "desktop-initial",
        }
        offscreen = {
            "url": target_url,
            "location": selector,
            "evidence_text": text,
            "technique": "OFFSCREEN",
            "reason": ["display:none으로 요소가 숨겨짐"],
            "display_source": selector,
            "scan_pass": "desktop-initial",
        }
        pages = [
            {
                "url": url,
                "title": "Page",
                "elements": (
                    [{"selector": selector, "text": text}]
                    if url == target_url
                    else [{"selector": "main > p", "text": "ordinary content"}]
                ),
            }
            for url in urls
        ]

        verified, rejected = verify_candidates(
            [[transparent], [offscreen]],
            pages=pages,
        )

        self.assertEqual(len(verified), 0)
        self.assertEqual(len(rejected), 2)
        self.assertTrue(
            all(item["multi_technique_count"] == 2 for item in rejected)
        )
        self.assertTrue(
            all(item["independent_technique_count"] == 1 for item in rejected)
        )

    def test_generic_service_text_needs_semantic_support_to_confirm(self):
        url = "https://example.com/history/1"
        selector = "main > article > p.hidden"
        candidate = {
            "url": url,
            "location": selector,
            "evidence_text": "통계 서비스 개편 및 시각화 서비스 실시",
            "technique": "TRANSPARENT",
            "reason": ["opacity가 0인 요소 또는 부모 요소에 의해 숨겨짐"],
            "opacity_source": selector,
            "scan_pass": "desktop-initial",
        }
        pages = [
            {
                "url": url,
                "title": "서비스 연혁",
                "elements": [
                    {
                        "selector": selector,
                        "text": candidate["evidence_text"],
                    },
                    {
                        "selector": "main > article > h1",
                        "text": "서비스 연혁",
                    },
                ],
            }
        ]

        verified, rejected = verify_candidates([[candidate]], pages=pages)

        self.assertEqual(len(verified), 0)
        self.assertEqual(len(rejected), 1)
        self.assertFalse(rejected[0]["semantic_support_ok"])
        self.assertLess(
            max(
                rejected[0]["legacy_semantic_support"],
                rejected[0]["multilingual_support"],
            ),
            0.55,
        )

    def test_visible_equivalent_css_text_is_not_open_set_suspicious(self):
        urls = [f"https://example.com/page-{index}" for index in range(8)]
        target_url = urls[0]
        hidden_selector = "main > section > p.hidden-copy"
        visible_selector = "main > section > p.visible-copy"
        text = "ordinary duplicated slide text"
        passes = [
            "desktop-initial",
            "desktop-settled",
            "desktop-scrolled",
            "mobile-settled",
            "mobile-scrolled",
        ]
        candidates = [
            {
                "url": target_url,
                "location": hidden_selector,
                "evidence_text": text,
                "technique": "OFFSCREEN",
                "reason": ["요소가 비정상적으로 먼 화면 밖 좌표에 배치됨"],
                "rect": {"x": -9999, "y": 0, "width": 120, "height": 20},
                "scan_pass": pass_name,
            }
            for pass_name in passes
        ]
        pages = [
            {
                "url": url,
                "title": "Page",
                "elements": (
                    [
                        {
                            "selector": hidden_selector,
                            "text": text,
                            "style": {
                                "visibility": "visible",
                                "fontSize": "16px",
                            },
                            "effectiveOpacity": 1.0,
                            "textColorAlpha": 1.0,
                            "sameTextBackground": False,
                            "displayNoneSource": None,
                            "inViewport": False,
                        },
                        {
                            "selector": visible_selector,
                            "text": text,
                            "style": {
                                "visibility": "visible",
                                "fontSize": "16px",
                            },
                            "effectiveOpacity": 1.0,
                            "textColorAlpha": 1.0,
                            "sameTextBackground": False,
                            "displayNoneSource": None,
                            "inViewport": True,
                        },
                    ]
                    if url == target_url
                    else [
                        {
                            "selector": "main > p",
                            "text": "ordinary content",
                            "style": {
                                "visibility": "visible",
                                "fontSize": "16px",
                            },
                            "effectiveOpacity": 1.0,
                            "textColorAlpha": 1.0,
                            "sameTextBackground": False,
                            "displayNoneSource": None,
                            "inViewport": True,
                        }
                    ]
                ),
            }
            for url in urls
        ]

        verified, rejected = verify_candidates([candidates], pages=pages)

        self.assertEqual(len(verified), 0)
        self.assertEqual(len(rejected), 1)
        self.assertTrue(rejected[0]["visible_equivalent_present"])
        self.assertEqual(rejected[0]["visible_equivalent_count"], 1)
        self.assertEqual(rejected[0]["verification_status"], "BENIGN_LIKELY")

    def test_normal_hangul_latin_label_is_not_unicode_anomaly(self):
        urls = [f"https://example.com/page-{index}" for index in range(8)]
        target_url = urls[0]
        selector = "main > section > dl > dt"
        passes = [
            "desktop-initial",
            "desktop-settled",
            "desktop-scrolled",
            "mobile-settled",
            "mobile-scrolled",
        ]
        candidates = [
            {
                "url": target_url,
                "location": selector,
                "evidence_text": "우주인C",
                "technique": "OFFSCREEN",
                "reason": ["글자 크기가 0.0px로 매우 작음"],
                "scan_pass": pass_name,
            }
            for pass_name in passes
        ]
        pages = [
            {
                "url": url,
                "title": "Page",
                "elements": (
                    [{"selector": selector, "text": "우주인C"}]
                    if url == target_url
                    else [{"selector": "main > p", "text": "ordinary content"}]
                ),
            }
            for url in urls
        ]

        verified, rejected = verify_candidates([candidates], pages=pages)

        self.assertEqual(len(verified), 0)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["verification_status"], "BENIGN_LIKELY")
        self.assertLess(rejected[0]["open_set_score"], 0.66)

    def test_visible_equivalent_with_zero_width_obfuscation_stays_suspicious(self):
        urls = [f"https://example.com/page-{index}" for index in range(8)]
        target_url = urls[0]
        selector = "main > section > p.mobile-hidden"
        text = "ABCDE\u200b FGHI 101"
        candidates = [
            {
                "url": target_url,
                "location": selector,
                "evidence_text": text,
                "technique": "TRANSPARENT",
                "reason": ["opacity가 0인 요소 또는 부모 요소에 의해 숨겨짐"],
                "opacity_source": selector,
                "scan_pass": pass_name,
            }
            for pass_name in ("mobile-settled", "mobile-scrolled")
        ]
        pages = [
            {
                "url": url,
                "title": "Page",
                "elements": (
                    [
                        {
                            "selector": selector,
                            "text": text,
                            "style": {
                                "visibility": "visible",
                                "fontSize": "16px",
                            },
                            "effectiveOpacity": 0.0,
                            "textColorAlpha": 1.0,
                            "sameTextBackground": False,
                            "displayNoneSource": None,
                            "inViewport": False,
                        },
                        {
                            "selector": "main > section > p.desktop-visible",
                            "text": text,
                            "style": {
                                "visibility": "visible",
                                "fontSize": "16px",
                            },
                            "effectiveOpacity": 1.0,
                            "textColorAlpha": 1.0,
                            "sameTextBackground": False,
                            "displayNoneSource": None,
                            "inViewport": True,
                        },
                    ]
                    if url == target_url
                    else [
                        {
                            "selector": "main > p",
                            "text": "ordinary content",
                            "style": {
                                "visibility": "visible",
                                "fontSize": "16px",
                            },
                            "effectiveOpacity": 1.0,
                            "textColorAlpha": 1.0,
                            "sameTextBackground": False,
                            "displayNoneSource": None,
                            "inViewport": True,
                        }
                    ]
                ),
            }
            for url in urls
        ]

        verified, rejected = verify_candidates([candidates], pages=pages)

        self.assertEqual(len(verified), 1)
        self.assertEqual(len(rejected), 0)
        self.assertTrue(verified[0]["visible_equivalent_present"])
        self.assertTrue(verified[0]["strong_text_obfuscation"])
        self.assertEqual(verified[0]["verification_status"], "SUSPICIOUS")

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

    def test_localhost_sample_text_does_not_bypass_verifier(self):
        url = "http://127.0.0.1:8000/test.html"
        selector = "body > p"
        candidate = {
            "url": url,
            "location": selector,
            "evidence_text": "SAMPLE TEST",
            "technique": "TRANSPARENT",
            "reason": ["opacity가 0인 요소 또는 부모 요소에 의해 숨겨짐"],
            "opacity_source": selector,
            "scan_pass": "desktop-initial",
        }
        pages = [
            {
                "url": url,
                "title": "Local fixture",
                "elements": [
                    {"selector": selector, "text": "SAMPLE TEST"},
                    {"selector": "body > h1", "text": "Local fixture"},
                ],
            }
        ]

        verified, rejected = verify_candidates([[candidate]], pages=pages)

        self.assertEqual(len(verified), 0)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["verification_status"], "BENIGN_LIKELY")
        self.assertLess(rejected[0]["verification_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
