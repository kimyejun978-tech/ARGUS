import unittest

from ui.log_parser import parse_engine_line


class GuiLogParserTests(unittest.TestCase):
    def test_scan_line(self):
        event = parse_engine_line(
            "[ARGUS][W3] 페이지 정밀 탐색 17: https://example.com/post/17"
        )
        self.assertEqual(event["type"], "scan")
        self.assertEqual(event["worker"], 3)
        self.assertEqual(event["attempt"], 17)
        self.assertEqual(event["url"], "https://example.com/post/17")

    def test_completed_line(self):
        event = parse_engine_line(
            "[ARGUS][W2] 완료 9: https://example.com/page"
        )
        self.assertEqual(event["type"], "complete")
        self.assertEqual(event["completed"], 9)

    def test_summary_line(self):
        event = parse_engine_line("최종 findings    : 20")
        self.assertEqual(
            event,
            {
                "type": "summary",
                "key": "최종 findings",
                "value": "20",
            },
        )

    def test_result_path_line(self):
        event = parse_engine_line(
            r"result.json      : C:\ARGUS\result.json"
        )
        self.assertEqual(event["type"], "summary")
        self.assertEqual(event["key"], "result.json")
        self.assertEqual(event["value"], r"C:\ARGUS\result.json")

    def test_auxiliary_download_summary(self):
        event = parse_engine_line("자동 다운로드 의심: 2")
        self.assertEqual(event["type"], "summary")
        self.assertEqual(event["key"], "자동 다운로드 의심")
        self.assertEqual(event["value"], "2")

    def test_extra_result_path_line(self):
        event = parse_engine_line(
            r"result_extra.json: C:\\ARGUS\\result_extra.json"
        )
        self.assertEqual(event["type"], "summary")
        self.assertEqual(event["key"], "result_extra.json")

    def test_autotune_line(self):
        event = parse_engine_line(
            "[ARGUS] Auto-Tune : 저장된 측정값 사용 / 8 worker"
        )
        self.assertEqual(event["type"], "autotune")
        self.assertEqual(
            event["value"],
            "저장된 측정값 사용 / 8 worker",
        )


if __name__ == "__main__":
    unittest.main()
