import tempfile
import unittest
from pathlib import Path

from desktop_api import ArgusDesktopApi


class DesktopApiStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.api = ArgusDesktopApi(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_live_scan_lines_update_attempts_and_completed_pages(self):
        self.api._handle_line(
            "[ARGUS][W3] 페이지 정밀 탐색 17: https://example.test/page"
        )
        self.api._handle_line(
            "[ARGUS][W3] 완료 12: https://example.test/page"
        )

        state = self.api.get_state()
        self.assertEqual(state["attempted"], 17)
        self.assertEqual(state["completed"], 12)
        self.assertEqual(state["current_url"], "https://example.test/page")

    def test_summary_lines_update_desktop_metrics(self):
        for line in (
            "발견 고유 URL 수  : 1,244",
            "정밀검사 시도 수 : 1250",
            "분석 완료 페이지 : 1244",
            "CONFIRMED        : 2",
            "SUSPICIOUS       : 1",
            "BENIGN_LIKELY    : 323914",
            "최종 findings    : 3",
            "자동 다운로드 의심: 1",
            "탐지 시간        : 697.300초",
        ):
            self.api._handle_line(line)

        state = self.api.get_state()
        self.assertEqual(state["discovered"], 1244)
        self.assertEqual(state["attempted"], 1250)
        self.assertEqual(state["completed"], 1244)
        self.assertEqual(state["findings"], 3)
        self.assertEqual(state["aux_downloads"], 1)
        self.assertAlmostEqual(state["elapsed_sec"], 697.3)

    def test_blank_target_is_rejected_without_starting_process(self):
        result = self.api.start_scan("   ")
        self.assertFalse(result["ok"])
        self.assertEqual(self.api.get_state()["status"], "idle")


if __name__ == "__main__":
    unittest.main()
