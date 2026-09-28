import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "webui" / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    def test_indeterminate_progress_does_not_claim_percentage(self):
        self.assertIn('role="progressbar"', self.html)
        self.assertNotIn("aria-valuenow", self.html)
        self.assertIn('aria-busy="false"', self.html)

    def test_tabs_and_modal_have_accessible_relationships(self):
        self.assertIn('role="tablist"', self.html)
        self.assertIn('aria-controls="officialPanel"', self.html)
        self.assertIn('role="tabpanel"', self.html)
        self.assertIn('aria-labelledby="detailTitle"', self.html)

    def test_polling_is_guarded_against_overlapping_calls(self):
        self.assertIn("let pollInFlight = false", self.js)
        self.assertIn("if (!apiReady || pollInFlight) return", self.js)
        self.assertIn("pollInFlight = false", self.js)

    def test_result_rows_support_keyboard_detail_opening(self):
        self.assertIn('tabindex="0" role="button"', self.js)
        self.assertIn("['Enter', ' ']", self.js)

    def test_auxiliary_table_uses_generic_columns_and_type_rendering(self):
        for heading in ("유형", "대상", "상세", "위험도"):
            self.assertIn(f'<th scope="col">{heading}</th>', self.html)
        self.assertIn('item.type === "DOMAIN_IMPERSONATION_RISK"', self.js)
        self.assertIn('"URL 사칭 위험"', self.js)
        self.assertIn('"자동 다운로드"', self.js)


if __name__ == "__main__":
    unittest.main()
