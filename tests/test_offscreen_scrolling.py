import unittest

from detectors.offscreen import detect_offscreen_candidates


class OffscreenScrollRegressionTests(unittest.TestCase):
    def test_scrolled_above_absolute_element_is_not_offscreen(self):
        page_result = {
            "url": "https://example.com/page",
            "elements": [
                {
                    "selector": "body > a",
                    "text": "normal link",
                    "style": {
                        "display": "block",
                        "fontSize": "16px",
                        "position": "absolute",
                        "left": "0px",
                        "top": "0px",
                    },
                    "rect": {
                        "x": 0,
                        "y": -5000,
                        "width": 120,
                        "height": 30,
                    },
                    "displayNoneSource": None,
                    "scan_pass": "desktop-scrolled",
                }
            ],
        }

        candidates = detect_offscreen_candidates(page_result)
        self.assertEqual(candidates, [])

    def test_explicit_large_negative_left_is_offscreen(self):
        page_result = {
            "url": "https://example.com/page",
            "elements": [
                {
                    "selector": "body > span",
                    "text": "hidden text",
                    "style": {
                        "display": "block",
                        "fontSize": "16px",
                        "position": "absolute",
                        "left": "-9999px",
                        "top": "0px",
                    },
                    "rect": {
                        "x": -9999,
                        "y": 0,
                        "width": 100,
                        "height": 20,
                    },
                    "displayNoneSource": None,
                    "scan_pass": "desktop-initial",
                }
            ],
        }

        candidates = detect_offscreen_candidates(page_result)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["technique"], "OFFSCREEN")


if __name__ == "__main__":
    unittest.main()
