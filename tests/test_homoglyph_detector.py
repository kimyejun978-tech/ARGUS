import unittest

from detectors.homoglyph import analyze_homoglyph


class HomoglyphDetectorTests(unittest.TestCase):
    def test_short_internal_digit_word_is_detected(self):
        reasons = analyze_homoglyph("Q0ABC SAMPLE")
        self.assertIn(
            "단어 내부 숫자가 유사한 알파벳 문자 대신 사용됨",
            reasons,
        )

    def test_long_displayed_source_sample_does_not_trigger_digit_rule(self):
        text = (
            "<!-- Example API source code for documentation. --> "
            "const item1Code = document.getElementById('item1Code'); "
            "function load2List() { "
            "let page3Value = item1Code.value; "
            "return page3Value; "
            "} "
            "This example is provided for developers and may be adjusted "
            "for the local environment."
        )

        reasons = analyze_homoglyph(text)

        self.assertNotIn(
            "단어 내부 숫자가 유사한 알파벳 문자 대신 사용됨",
            reasons,
        )


if __name__ == "__main__":
    unittest.main()
