import copy
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from ui.log_parser import parse_engine_line


ROOT = Path(__file__).resolve().parent
MAX_LOG_LINES = 600


class ArgusDesktopApi:
    """Thread-safe bridge between the desktop web UI and the ARGUS CLI engine."""

    def __init__(self, root=ROOT):
        self.root = Path(root)
        self._lock = threading.RLock()
        self._process = None
        self._worker = None
        self._started_monotonic = None
        self._cancel_requested = False
        self._state = self._fresh_state()

    def _fresh_state(self):
        return {
            "status": "idle",
            "status_text": "대기",
            "target": "",
            "current_url": "",
            "attempted": 0,
            "completed": 0,
            "discovered": 0,
            "findings": 0,
            "confirmed": 0,
            "suspicious": 0,
            "benign": 0,
            "aux_downloads": 0,
            "autotune": "Auto-Tune 대기",
            "elapsed_sec": 0.0,
            "warning": "",
            "error": "",
            "result_path": "",
            "extra_result_path": "",
            "results": [],
            "aux_results": [],
            "logs": [],
        }

    def get_state(self):
        with self._lock:
            state = copy.deepcopy(self._state)
            if (
                state["status"] == "running"
                and self._started_monotonic is not None
            ):
                state["elapsed_sec"] = round(
                    time.monotonic() - self._started_monotonic,
                    1,
                )
            return state

    def start_scan(self, target):
        target = str(target or "").strip()

        if not target or target == "https://":
            return {
                "ok": False,
                "message": "점검할 URL 또는 파일을 입력해 주세요.",
            }

        with self._lock:
            if self._process is not None:
                return {
                    "ok": False,
                    "message": "이미 점검이 진행 중입니다.",
                }

            self._cancel_requested = False
            self._started_monotonic = time.monotonic()
            self._state = self._fresh_state()
            self._state.update(
                {
                    "status": "running",
                    "status_text": "점검 중",
                    "target": target,
                    "current_url": "탐지 엔진을 시작하고 있습니다.",
                }
            )

        self._worker = threading.Thread(
            target=self._run_engine,
            args=(target,),
            name="argus-desktop-engine",
            daemon=True,
        )
        self._worker.start()

        return {"ok": True}

    def cancel_scan(self):
        with self._lock:
            process = self._process
            if process is None:
                return {"ok": False, "message": "진행 중인 점검이 없습니다."}

            self._cancel_requested = True
            self._state["status_text"] = "중지 중"
            self._state["current_url"] = "실행 중인 점검 작업을 종료하고 있습니다."

        try:
            if os.name == "nt":
                subprocess.run(
                    [
                        "taskkill",
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                process.terminate()
            return {"ok": True}
        except Exception as exc:
            with self._lock:
                self._state["error"] = str(exc)
            return {"ok": False, "message": str(exc)}

    def open_result_folder(self):
        with self._lock:
            raw_path = self._state.get("result_path") or str(
                self.root / "result.json"
            )

        path = Path(raw_path)
        if not path.is_absolute():
            path = self.root / path
        folder = path.parent

        try:
            if os.name == "nt":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def _run_engine(self, target):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            )

        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    str(self.root / "main.py"),
                ],
                cwd=str(self.root),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )

            with self._lock:
                self._process = process

            if process.stdin is not None:
                process.stdin.write(target + "\n")
                process.stdin.flush()
                process.stdin.close()

            if process.stdout is not None:
                for line in process.stdout:
                    self._handle_line(line.rstrip("\r\n"))

            return_code = process.wait()
            self._finish(return_code)
        except Exception as exc:
            with self._lock:
                self._state["status"] = "error"
                self._state["status_text"] = "오류"
                self._state["error"] = str(exc)
                self._state["current_url"] = str(exc)
        finally:
            with self._lock:
                self._process = None

    def _append_log(self, line):
        logs = self._state["logs"]
        logs.append(line)
        if len(logs) > MAX_LOG_LINES:
            del logs[: len(logs) - MAX_LOG_LINES]

    @staticmethod
    def _parse_int(value):
        try:
            return int(str(value).strip().replace(",", ""))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _parse_elapsed(value):
        text = str(value or "").strip()
        if text.endswith("초"):
            text = text[:-1]
        try:
            return float(text)
        except ValueError:
            return 0.0

    def _handle_line(self, line):
        event = parse_engine_line(line)

        with self._lock:
            self._append_log(line)
            event_type = event.get("type")

            if event_type == "scan":
                self._state["attempted"] = event["attempt"]
                self._state["current_url"] = event["url"]
                return

            if event_type == "complete":
                self._state["completed"] = event["completed"]
                self._state["current_url"] = event["url"]
                return

            if event_type == "autotune":
                self._state["autotune"] = event["value"]
                return

            if event_type == "warning":
                self._state["warning"] = event["value"]
                return

            if event_type != "summary":
                return

            key = event["key"]
            value = event["value"]

            if key == "발견 고유 URL 수":
                self._state["discovered"] = self._parse_int(value)
            elif key == "정밀검사 시도 수":
                self._state["attempted"] = self._parse_int(value)
            elif key == "분석 완료 페이지":
                self._state["completed"] = self._parse_int(value)
            elif key == "CONFIRMED":
                self._state["confirmed"] = self._parse_int(value)
            elif key == "SUSPICIOUS":
                self._state["suspicious"] = self._parse_int(value)
            elif key == "BENIGN_LIKELY":
                self._state["benign"] = self._parse_int(value)
            elif key == "최종 findings":
                self._state["findings"] = self._parse_int(value)
            elif key == "자동 다운로드 의심":
                self._state["aux_downloads"] = self._parse_int(value)
            elif key == "result.json":
                self._state["result_path"] = value.strip()
            elif key == "result_extra.json":
                self._state["extra_result_path"] = value.strip()
            elif key == "탐지 시간":
                self._state["elapsed_sec"] = self._parse_elapsed(value)

    def _finish(self, return_code):
        with self._lock:
            cancelled = self._cancel_requested

        if cancelled:
            with self._lock:
                self._state["status"] = "cancelled"
                self._state["status_text"] = "중지됨"
                self._state["current_url"] = "사용자가 점검을 중지했습니다."
            return

        if return_code != 0:
            with self._lock:
                self._state["status"] = "error"
                self._state["status_text"] = "오류"
                self._state["error"] = (
                    f"탐지 엔진이 종료 코드 {return_code}로 종료되었습니다."
                )
                self._state["current_url"] = self._state["error"]
            return

        self._load_outputs()

        with self._lock:
            self._state["status"] = "complete"
            self._state["status_text"] = "완료"
            self._state["current_url"] = "점검이 완료되었습니다."
            if self._started_monotonic is not None and not self._state["elapsed_sec"]:
                self._state["elapsed_sec"] = round(
                    time.monotonic() - self._started_monotonic,
                    1,
                )

    def _load_outputs(self):
        with self._lock:
            result_path = self._state.get("result_path")
            extra_path = self._state.get("extra_result_path")

        if not result_path:
            result_path = str(self.root / "result.json")
        if not extra_path:
            extra_path = str(self.root / "result_extra.json")

        official = self._read_json(result_path)
        extra = self._read_json(extra_path)

        with self._lock:
            if official is not None:
                self._state["results"] = official.get("findings", [])
                self._state["findings"] = len(self._state["results"])

            if extra is not None:
                aux = extra.get("auxiliary_findings", [])
                self._state["aux_results"] = aux
                self._state["aux_downloads"] = sum(
                    1
                    for item in aux
                    if item.get("risk") == "SUSPICIOUS"
                )

    def _read_json(self, raw_path):
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.root / path
        if not path.exists():
            return None

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            with self._lock:
                self._append_log(f"[DESKTOP] 결과 파일 읽기 실패: {exc}")
            return None
