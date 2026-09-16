from collections import defaultdict
from urllib.parse import urlsplit


# 구조적 은닉/위장과 '불법광고 내용'을 분리하기 위한 1차 의미 신호.
# 규칙 기반 단계이므로 보수적으로 운용하고, 이후 문맥 분류기로 확장한다.
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
    "출금",
    "충전",
    "사설",
    "놀이터",
    "배당",
    "가입코드",
    "텔레그램",
    "telegram",
    "casino",
    "betting",
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
    if candidate.get("technique") != "OFFSCREEN":
        return False

    reasons = candidate.get("reason", [])

    if not reasons:
        return False

    return all("display:none" in reason for reason in reasons)


def _dedupe_candidates(candidates):
    """
    다중 검사 패스에서 같은 요소가 여러 번 관측되어도
    result.json의 1건 단위인 (url + location + technique) 기준으로 먼저 합친다.

    서로 다른 패스에서 다른 근거가 발견되면 reason은 합집합으로 보존한다.
    """

    merged = {}
    order = []

    for candidate in candidates:
        key = (
            candidate.get("url"),
            candidate.get("location"),
            candidate.get("technique"),
        )

        if key not in merged:
            item = dict(candidate)
            item["observation_count"] = 1
            merged[key] = item
            order.append(key)
            continue

        item = merged[key]
        item["observation_count"] += 1

        old_reasons = item.get("reason", [])
        new_reasons = candidate.get("reason", [])
        item["reason"] = list(dict.fromkeys([*old_reasons, *new_reasons]))

        old_text = item.get("evidence_text") or ""
        new_text = candidate.get("evidence_text") or ""

        if len(new_text) > len(old_text):
            item["evidence_text"] = new_text

        if candidate.get("normalized_text") and not item.get("normalized_text"):
            item["normalized_text"] = candidate["normalized_text"]

        # 더 많은 근거를 가진 관측의 좌표/은닉 출처를 우선 보존한다.
        if len(new_reasons) >= len(old_reasons):
            if candidate.get("rect") is not None:
                item["rect"] = candidate["rect"]
            if candidate.get("opacity_source"):
                item["opacity_source"] = candidate["opacity_source"]
            if candidate.get("display_source"):
                item["display_source"] = candidate["display_source"]

    return [merged[key] for key in order]


def verify_candidates(candidate_groups):
    """
    구조 탐지 후보를 1차 의미 검증한다.

    핵심 원칙:
    - CSS/Unicode 기법이 발견됐다는 사실만으로 불법광고라고 확정하지 않는다.
    - 정규화된 텍스트에서 불법광고 내용 신호가 함께 확인될 때만 통과한다.
    - localhost/file 기반 모의 테스트의 SAMPLE/TEST 항목은 회귀 테스트를 위해 통과한다.
    - 다중 검사에서 같은 요소가 반복 관측된 것은 하나로 합친 뒤 검증한다.
    """

    raw_candidates = [
        candidate
        for group in candidate_groups
        for candidate in group
    ]

    candidates = _dedupe_candidates(raw_candidates)

    repeated_pages = defaultdict(set)

    for candidate in candidates:
        key = (
            candidate.get("technique"),
            candidate.get("location"),
            candidate.get("evidence_text"),
        )
        repeated_pages[key].add(candidate.get("url"))

    verified = []
    rejected = []

    for candidate in candidates:
        item = dict(candidate)

        key = (
            candidate.get("technique"),
            candidate.get("location"),
            candidate.get("evidence_text"),
        )
        repeat_count = len(repeated_pages[key])

        if _is_local_test_candidate(candidate):
            item["verification_reason"] = "로컬 회귀 테스트 표식이 확인됨"
            verified.append(item)
            continue

        if _has_risk_signal(candidate):
            item["verification_reason"] = (
                "은닉/변조 기법과 불법광고 내용 신호가 함께 확인됨"
            )
            verified.append(item)
            continue

        if _is_display_none_only(candidate):
            reason = "display:none만으로 숨겨진 정상 UI 가능성이 높음"
        else:
            reason = (
                "은닉/변조 기법은 확인됐지만 불법광고 내용 신호가 없어 1차 보류"
            )

        if repeat_count >= 3:
            reason += (
                f"; 동일 요소가 {repeat_count}개 페이지에서 반복되어 공통 UI/템플릿 가능성이 큼"
            )

        item["verification_reason"] = reason
        item["is_violation"] = False
        rejected.append(item)

    return verified, rejected
