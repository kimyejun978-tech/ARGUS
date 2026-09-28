import tempfile
import unittest
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

from desktop_api import ArgusDesktopApi


class DesktopApiStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.api = ArgusDesktopApi(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def _write_output_pair(self, official_findings=None, auxiliary_findings=None):
        official_path = Path(self.temp.name) / "result.json"
        extra_path = Path(self.temp.name) / "result_extra.json"
        official_path.write_text(
            json.dumps({"findings": official_findings or []}),
            encoding="utf-8",
        )
        extra_path.write_text(
            json.dumps(
                {
                    "meta": {"official_findings": False},
                    "auxiliary_findings": auxiliary_findings or [],
                }
            ),
            encoding="utf-8",
        )
        self.api._state["result_path"] = str(official_path)
        self.api._state["extra_result_path"] = str(extra_path)

    def _complete_with(self, official_findings=None, auxiliary_findings=None):
        self._write_output_pair(official_findings, auxiliary_findings)
        self.api._finish(0)
        return self.api.get_state()

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

    def test_live_discovery_line_updates_known_url_count(self):
        self.api._handle_line(
            "[ARGUS] 발견 URL 25: https://example.test/new-page"
        )

        self.assertEqual(self.api.get_state()["discovered"], 25)

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

    def test_start_is_rejected_while_worker_is_starting(self):
        self.api._state["status"] = "running"
        self.api._process = None

        result = self.api.start_scan("https://example.test")

        self.assertFalse(result["ok"])
        self.assertIn("이미", result["message"])

    def test_cancel_is_accepted_before_process_is_attached(self):
        self.api._state["status"] = "running"
        self.api._process = None

        result = self.api.cancel_scan()

        self.assertTrue(result["ok"])
        self.assertTrue(self.api._cancel_requested)
        self.assertEqual(self.api.get_state()["status_text"], "중지 중")

    def test_shutdown_terminates_running_process_tree(self):
        process = Mock(pid=4321)
        process.poll.return_value = None
        self.api._process = process
        self.api._state["status"] = "running"

        with patch.object(
            self.api,
            "_terminate_process",
            return_value=True,
        ) as terminate:
            result = self.api.shutdown()

        self.assertTrue(result)
        self.assertTrue(self.api._cancel_requested)
        terminate.assert_called_once_with(process)

    def test_load_outputs_keeps_official_and_auxiliary_results_separate(self):
        official_path = Path(self.temp.name) / "result.json"
        extra_path = Path(self.temp.name) / "result_extra.json"
        official_path.write_text(
            json.dumps(
                {
                    "meta": {},
                    "findings": [
                        {
                            "url": "https://example.test",
                            "location": "html > body > p",
                            "technique": "JAMO",
                            "evidence_text": "sample",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        extra_path.write_text(
            json.dumps(
                {
                    "meta": {"official_findings": False},
                    "auxiliary_findings": [
                        {
                            "type": "AUTO_DOWNLOAD_ATTEMPT",
                            "risk": "SUSPICIOUS",
                            "blocked": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.api._state["result_path"] = str(official_path)
        self.api._state["extra_result_path"] = str(extra_path)

        self.api._load_outputs()
        state = self.api.get_state()

        self.assertEqual(len(state["results"]), 1)
        self.assertEqual(state["results"][0]["technique"], "JAMO")
        self.assertEqual(len(state["aux_results"]), 1)
        self.assertEqual(state["aux_downloads"], 1)

    def test_load_outputs_surfaces_domain_impersonation_warning(self):
        official_path = Path(self.temp.name) / "result.json"
        extra_path = Path(self.temp.name) / "result_extra.json"
        official_path.write_text(
            json.dumps({"findings": []}),
            encoding="utf-8",
        )
        extra_path.write_text(
            json.dumps(
                {
                    "auxiliary_findings": [
                        {
                            "type": "DOMAIN_IMPERSONATION_RISK",
                            "risk": "SUSPICIOUS",
                            "page_url": "https://twtch-login.test/account",
                            "display_hostname": "twtch-login.test",
                            "brand": "Twitch",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.api._result_path = official_path
        self.api._extra_result_path = extra_path

        self.api._load_outputs()
        state = self.api.get_state()

        self.assertEqual(state["aux_downloads"], 1)
        self.assertIn("URL 사칭 위험", state["warning"])
        self.assertIn("twtch-login.test", state["warning"])

    def test_completion_without_findings_reports_no_special_issues(self):
        state = self._complete_with()

        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["status_text"], "특이사항 없음")
        self.assertEqual(state["findings"], 0)
        self.assertEqual(state["aux_downloads"], 0)

    def test_completion_with_official_finding_reports_detection(self):
        state = self._complete_with(
            official_findings=[{"technique": "JAMO", "evidence_text": "sample"}]
        )

        self.assertEqual(state["status_text"], "탐지 결과 있음")
        self.assertEqual(state["findings"], 1)
        self.assertEqual(state["aux_downloads"], 0)

    def test_completion_with_domain_risk_requires_review(self):
        state = self._complete_with(
            auxiliary_findings=[
                {
                    "type": "DOMAIN_IMPERSONATION_RISK",
                    "risk": "SUSPICIOUS",
                    "display_hostname": "twtch-login.test",
                    "brand": "Twitch",
                }
            ]
        )

        self.assertEqual(state["status_text"], "추가 확인 필요")
        self.assertEqual(state["findings"], 0)
        self.assertEqual(state["aux_downloads"], 1)
        self.assertIn("URL 사칭 위험", state["warning"])

    def test_completion_with_download_risk_requires_review(self):
        state = self._complete_with(
            auxiliary_findings=[
                {"type": "AUTO_DOWNLOAD_ATTEMPT", "risk": "SUSPICIOUS"}
            ]
        )

        self.assertEqual(state["status_text"], "추가 확인 필요")
        self.assertEqual(state["findings"], 0)
        self.assertEqual(state["aux_downloads"], 1)
        self.assertIn("보조 위험 진단", state["warning"])

    def test_completion_keeps_official_and_auxiliary_counts_separate(self):
        state = self._complete_with(
            official_findings=[{"technique": "OFFSCREEN"}],
            auxiliary_findings=[
                {"type": "AUTO_DOWNLOAD_ATTEMPT", "risk": "SUSPICIOUS"}
            ],
        )

        self.assertEqual(state["status_text"], "탐지 결과 있음")
        self.assertEqual(state["findings"], 1)
        self.assertEqual(state["aux_downloads"], 1)
        self.assertEqual(len(state["results"]), 1)
        self.assertEqual(len(state["aux_results"]), 1)

    def test_development_engine_command_uses_python_main(self):
        with patch.object(sys, "frozen", False, create=True):
            command = self.api._engine_command()

        self.assertEqual(command[0], sys.executable)
        self.assertIn("-u", command)
        self.assertEqual(Path(command[-1]), Path(self.temp.name) / "main.py")

    def test_frozen_engine_command_uses_sibling_executable(self):
        frozen_executable = Path(self.temp.name) / "ARGUS.exe"
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(frozen_executable)),
            patch("desktop_api.os.name", "nt"),
        ):
            command = self.api._engine_command()

        self.assertEqual(
            command,
            [str(frozen_executable.with_name("argus-engine.exe"))],
        )


if __name__ == "__main__":
    unittest.main()
