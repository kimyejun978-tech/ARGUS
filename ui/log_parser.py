import re


_SCAN_RE = re.compile(
    r"^\[ARGUS\]\[W(?P<worker>\d+)\] 페이지 정밀 탐색 "
    r"(?P<attempt>\d+): (?P<url>.+)$"
)
_COMPLETE_RE = re.compile(
    r"^\[ARGUS\]\[W(?P<worker>\d+)\] 완료 "
    r"(?P<completed>\d+): (?P<url>.+)$"
)
_SUMMARY_RE = re.compile(
    r"^\s*(?P<key>"
    r"브라우저 worker|discovery worker|발견 고유 URL 수|정밀검사 시도 수|"
    r"분석 완료 페이지|분석 frame 수|CONFIRMED|SUSPICIOUS|BENIGN_LIKELY|"
    r"최종 findings|result\.json|탐지 시간"
    r")\s*:\s*(?P<value>.+?)\s*$"
)
_AUTOTUNE_RE = re.compile(
    r"^\[ARGUS\] Auto-Tune\s*:\s*(?P<value>.+?)\s*$"
)


def parse_engine_line(line):
    """ARGUS CLI 한 줄을 GUI가 사용할 작은 이벤트로 변환한다."""

    text = (line or "").rstrip("\r\n")

    match = _SCAN_RE.match(text)
    if match:
        return {
            "type": "scan",
            "worker": int(match.group("worker")),
            "attempt": int(match.group("attempt")),
            "url": match.group("url"),
        }

    match = _COMPLETE_RE.match(text)
    if match:
        return {
            "type": "complete",
            "worker": int(match.group("worker")),
            "completed": int(match.group("completed")),
            "url": match.group("url"),
        }

    match = _AUTOTUNE_RE.match(text)
    if match:
        return {
            "type": "autotune",
            "value": match.group("value"),
        }

    match = _SUMMARY_RE.match(text)
    if match:
        return {
            "type": "summary",
            "key": match.group("key"),
            "value": match.group("value"),
        }

    if text.startswith("주의"):
        return {
            "type": "warning",
            "value": text,
        }

    return {
        "type": "log",
        "value": text,
    }
