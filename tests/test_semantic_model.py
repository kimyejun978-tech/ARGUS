import unittest

from verifier.semantic_model import CharNgramNaiveBayes


class SemanticModelTests(unittest.TestCase):
    def test_unseen_text_stays_near_uncertain(self):
        model = CharNgramNaiveBayes(
            positive_examples=[
                "hidden promotion join bonus",
                "불법 광고 신규 회원 혜택",
            ],
            negative_examples=[
                "privacy policy",
                "공식 앱 다운로드",
            ],
        )

        probability, support = model.predict_details("QZXV NRMK portal")

        self.assertLess(support, 0.35)
        self.assertGreater(probability, 0.30)
        self.assertLess(probability, 0.70)

    def test_known_positive_keeps_high_confidence(self):
        model = CharNgramNaiveBayes(
            positive_examples=[
                "hidden promotion join bonus",
                "불법 광고 신규 회원 혜택",
            ],
            negative_examples=[
                "privacy policy",
                "공식 앱 다운로드",
            ],
        )

        probability, support = model.predict_details(
            "hidden promotion join bonus"
        )

        self.assertGreaterEqual(support, 0.90)
        self.assertGreater(probability, 0.70)


if __name__ == "__main__":
    unittest.main()
