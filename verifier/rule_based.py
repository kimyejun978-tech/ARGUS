from collections import Counter
from urllib.parse import urlsplit


# 1차 검증용 최소 위험 키워드.
# 구조 탐지 결과를 곧바로 위반으로 확정하지 않기 위한 보조 신호이며,
# 최종적으로는 더 정교한 콘텐츠 분류기/AI 검증기로 교체할 수 있다.
RISK_KEYWORDS = {
    "카지노",
    "토토",
    "슬롯",
    "바카라",
    "베팅",
    "배팅",
    "먹튀",
    "첫충",
    "환전",
    "보너스",
    "텔레그램",
    "telegram",
    "casino",
    "betting",
    "bet",
    "slot",
    "adult",
    "성인",
    "19금",
}


def _candidate_text(candidate):
    return (
        candidate.get("normalized_text")
        or candidate.get("evidence_text")
        or ""
    ).lower()


def _has_risk_signal(candidate):
    text = _candidate_text(candidate)
    return any(keyword in text for keyword in RISK_KEYWORDS)


def _is_local_test_candidate(candidate):
    """로컬 모의 사이트의 SAMPLE/TEST 표시는 테스트 정답으로 취급한다."""

    url = candidate.get("url", "")
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    text = _candidate_text(candidate)

    is_local = (
        parsed.scheme == "file"
        or host in {"localhost", "127.0.0.1", "::1"}
    )

    return is_local and ("sample" in text or "test" in text)


def _is_display_none_only(candidate):
    """
    OFFSCREEN 후보 중 display:none 계열 근거만 있는 경우인지 확인한다.

    display:none은 정상 메뉴/모달/반응형 UI에서도 매우 흔하므로,
    이것만으로는 위반으로 확정하지 않는다.
    """

    if candidate.get("technique") != "OFFSCREEN":
        return False

    reasons = candidate.get("reason", [])

    if not reasons:
        return False

    return all("display:none" in reason for reason in reasons)


def verify_candidates(candidate_groups):
    """
    구조 탐지 후보를 1차 검증한다.

    현재 정책:
    - JAMO/HOMOGLYPH/TRANSPARENT 및 강한 OFFSCREEN 신호는 통과
    - display:none만 근거인 OFFSCREEN은 오탐 가능성이 높아 보수적으로 보류
    - 단, 위험 키워드가 있거나 로컬 테스트 표식이면 통과
    - 여러 페이지에 똑같이 반복되는 약한 display:none 후보는 공통 UI 가능성을 기록

    반환값: (verified, rejected)
    """

    candidates = [
        candidate
        for group in candidate_groups
        for candidate in group
    ]

    repeated_counter = Counter(
        (
            candidate.get("technique"),
            candidate.get("location"),
            candidate.get("evidence_text"),
        )
        for candidate in candidates
    )

    verified = []
    rejected = []

    for candidate in candidates:
        item = dict(candidate)

        key = (
            candidate.get("technique"),
            candidate.get("location"),
            candidate.get("evidence_text"),
        )
        repeat_count = repeated_counter[key]

        if _is_display_none_only(candidate):
            if _has_risk_signal(candidate) or _is_local_test_candidate(candidate):
                item["verification_reason"] = (
                    "display:none 단독 후보이지만 콘텐츠 위험 신호가 확인됨"
                )
                verified.append(item)
                continue

            item["verification_reason"] = (
                "display:none만으로 숨겨진 요소는 정상 UI일 가능성이 높아 1차 보류"
            )

            if repeat_count >= 3:
                item["verification_reason"] += (
                    f"; 동일 요소가 {repeat_count}개 페이지에서 반복되어 공통 UI/푸터 가능성이 큼"
                )

            item["is_violation"] = False
            rejected.append(item)
            continue

        item["verification_reason"] = "강한 은닉/변조 기법 신호가 확인됨"
        verified.append(item)

    return verified, rejected
