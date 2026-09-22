import re
import unicodedata
from urllib.parse import urlsplit

from detectors.homoglyph import CONFUSABLE_MAP


UI_HINTS = (
    "dialog",
    "modal",
    "nav",
    "header",
    "footer",
    "menu",
    "cookie",
    "tooltip",
    "drawer",
)

UI_TEXT_LABEL_RE = re.compile(
    r"^(?:menu|navigation|breadcrumb|pagination|메뉴|내비게이션)"
    r"(?:\s+(?:guide|label|안내))?$",
    re.IGNORECASE,
)

VERSION_LABEL_RE = re.compile(
    r"^(?:version|ver\.?|버전)\s*[v.]?\s*\d+(?:\.\d+)*$",
    re.IGNORECASE,
)

BIDI_OR_ZERO_WIDTH = {
    "\u200b",
    "\u200c",
    "\u200d",
    "\u2060",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
}


def _script_bucket(char):
    if not char.isalpha():
        return None

    name = unicodedata.name(char, "")

    for script in (
        "LATIN",
        "CYRILLIC",
        "GREEK",
        "HANGUL",
        "HIRAGANA",
        "KATAKANA",
        "CJK",
        "ARABIC",
        "HEBREW",
        "THAI",
        "DEVANAGARI",
    ):
        if script in name:
            return script

    return "OTHER"


def _unicode_anomaly(text):
    text = text or ""
    letters = [char for char in text if char.isalpha()]
    scripts = {
        bucket
        for char in letters
        if (bucket := _script_bucket(char)) is not None
    }

    score = 0.0
    reasons = []

    if any(char in BIDI_OR_ZERO_WIDTH for char in text):
        score += 0.20
        reasons.append("zero-width/bidi 제어문자 포함")

    # 단순한 다국어 혼합은 이상 신호가 아니다.
    # 예: "우주인C", "GPS기반", "BOD_약간", "22μg" 같은 정상 표기.
    # 실제 HOMOGLYPH detector와 동일하게 ASCII Latin + 시각적으로 혼동 가능한
    # 키릴/그리스 문자 조합일 때만 open-set 가산점을 준다.
    tokens = re.findall(r"\w+", text, flags=re.UNICODE)
    confusable_mixed_token = False

    for token in tokens:
        has_ascii_latin = bool(re.search(r"[A-Za-z]", token))
        has_confusable = any(char in CONFUSABLE_MAP for char in token)

        if has_ascii_latin and has_confusable:
            confusable_mixed_token = True
            break

    if confusable_mixed_token:
        score += 0.12
        reasons.append("단일 토큰 내 Latin/유사 키릴·그리스 문자 혼합")

    return min(0.25, score), reasons


def _ui_context_penalty(candidate):
    blob = " ".join(
        str(candidate.get(field, ""))
        for field in (
            "location",
            "opacity_source",
            "display_source",
        )
    ).lower()

    if any(hint in blob for hint in UI_HINTS):
        return 0.16, ["dialog/nav/header/footer 등 공통 UI 문맥"]

    normalized_text = unicodedata.normalize(
        "NFKC",
        candidate.get("normalized_text")
        or candidate.get("evidence_text")
        or "",
    ).strip().lower()

    # 짧은 UI 라벨과 버전 표기는 전각 문자나 자모 분리로 작성되는 경우가
    # 실제 사이트에도 있다. 위치 selector가 일반 div/p여도 이런 텍스트 자체는
    # 광고성 open-set 근거가 아니므로 기존 UI 문맥 패널티를 동일하게 적용한다.
    if len(normalized_text) <= 48 and (
        UI_TEXT_LABEL_RE.fullmatch(normalized_text)
        or VERSION_LABEL_RE.fullmatch(normalized_text)
    ):
        return 0.16, ["짧은 메뉴/탐색 라벨 또는 버전 메타데이터"]

    return 0.0, []


def _pass_selectivity(candidate):
    passes = candidate.get("scan_passes") or []
    count = len(set(passes))
    technique = candidate.get("technique")

    if count == 0:
        return 0.0, []

    if count == 1:
        # CSS 은닉은 로딩/탭/캐러셀 전환 중 한 패스에서만 잠깐 관측되는
        # 정상 UI가 매우 많다. 반면 JAMO/HOMOGLYPH는 렌더링 상태 자체보다
        # 텍스트 변조가 핵심 증거이므로 기존 희귀 상태 가산점을 유지한다.
        if technique in {"TRANSPARENT", "OFFSCREEN"}:
            return -0.04, ["CSS 은닉이 1개 렌더링 상태에서만 관측되어 일시 상태 가능성"]
        return 0.10, ["특정 1개 렌더링 상태에서만 관측"]

    if count == 2:
        return 0.06, ["일부 렌더링 상태에서만 관측"]

    if count >= 5:
        # 여러 패스에서 안정적으로 반복되는 은닉은 일시적인 로딩/애니메이션보다
        # 의도된 구조일 가능성이 높다.
        return 0.03, ["모든 렌더링 상태에서 안정적으로 반복 관측"]

    return 0.0, []


def open_set_anomaly_score(
    candidate,
    *,
    structure_score,
    repeat_count,
    repeat_ratio,
    multi_technique_count,
    total_pages,
):
    """
    의미 모델이 모르는 신유형을 놓치지 않기 위한 open-set 점수.

    텍스트가 어떤 범죄 유형인지 맞히지 않고, 현재 사이트 안에서
    구조적으로 얼마나 희귀하고 의도적으로 은닉됐는지를 본다.
    반환값: (0~1 score, reasons)
    """

    score = 0.0
    reasons = []

    score += 0.50 * max(0.0, min(1.0, structure_score))
    reasons.append(f"은닉 구조 강도 {structure_score:.2f}")

    # 사이트 내 희귀성. 페이지가 충분히 많은데 한두 번만 나오면 가산한다.
    if repeat_count <= 1:
        rarity = 1.0
    elif repeat_count == 2:
        rarity = 0.72
    elif repeat_count == 3:
        rarity = 0.45
    else:
        rarity = max(0.0, 1.0 - repeat_ratio * 2.2)

    # 표본이 1~2페이지만 있으면 희귀성에 과신하지 않는다.
    sample_confidence = min(1.0, max(0.35, total_pages / 8.0))
    score += 0.22 * rarity * sample_confidence

    if rarity >= 0.7 and total_pages >= 4:
        reasons.append("사이트 내부에서 드문 요소")

    if multi_technique_count >= 2:
        multi_bonus = min(0.16, 0.08 * (multi_technique_count - 1))
        score += multi_bonus
        reasons.append(f"동일 요소에 {multi_technique_count}개 탐지 기법 중첩")

    unicode_bonus, unicode_reasons = _unicode_anomaly(
        candidate.get("normalized_text")
        or candidate.get("evidence_text")
        or ""
    )
    score += unicode_bonus
    reasons.extend(unicode_reasons)

    pass_bonus, pass_reasons = _pass_selectivity(candidate)
    score += pass_bonus
    reasons.extend(pass_reasons)

    ui_penalty, ui_reasons = _ui_context_penalty(candidate)
    score -= ui_penalty
    reasons.extend(ui_reasons)

    # 많은 페이지에서 같은 위치가 반복되면 사이트 템플릿일 가능성이 높다.
    if repeat_count >= 3:
        template_penalty = min(
            0.32,
            0.07 * (repeat_count - 2) + repeat_ratio * 0.35,
        )
        score -= template_penalty
        reasons.append(f"{repeat_count}개 페이지 반복으로 템플릿 패널티")

    # display:none만 있는 경우 정상 UI가 매우 흔하므로 추가 보수화한다.
    reasons_blob = " ".join(candidate.get("reason", [])).lower()
    if (
        candidate.get("technique") == "OFFSCREEN"
        and reasons_blob
        and "display:none" in reasons_blob
        and "글자 크기" not in reasons_blob
        and "화면 밖 좌표" not in reasons_blob
    ):
        score -= 0.16
        reasons.append("display:none 단독 후보 보수화")

    return max(0.0, min(1.0, score)), reasons
