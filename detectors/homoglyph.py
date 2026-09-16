import re
import unicodedata


# 눈으로 봤을 때 라틴 문자와 매우 비슷한 키릴/그리스 문자 일부.
CONFUSABLE_MAP = {
    # Cyrillic
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "Х": "X", "а": "a", "е": "e", "о": "o", "р": "p",
    "с": "c", "х": "x", "у": "y",

    # Greek
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H",
    "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    "ο": "o", "ρ": "p",
}

DIGIT_CONFUSABLE_MAP = {
    "0": "O",
    "1": "I",
    "3": "E",
    "4": "A",
    "5": "S",
    "7": "T",
    "8": "B",
}

ASCII_LATIN_RE = re.compile(r"[A-Za-z]")

# 전각 구두점까지 전부 HOMOGLYPH로 잡으면 일본어 괄호/따옴표 같은 정상 표기가
# 대량 오탐된다. 실제 문자 위장에 가까운 영문/숫자만 본다.
FULLWIDTH_ALNUM_RE = re.compile(r"[\uFF10-\uFF19\uFF21-\uFF3A\uFF41-\uFF5A]")

# 같은 토큰 안에서만 문자 체계 혼합 여부를 판단한다.
SCRIPT_TOKEN_RE = re.compile(r"[A-Za-z\u0370-\u03FF\u0400-\u04FF]+")
ASCII_WORD_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
INTERNAL_DIGIT_RE = re.compile(r"(?<=[A-Za-z])[0134578](?=[A-Za-z])")
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
LONG_MACHINE_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{16,}\b")


def _contains_mixed_script_token(text: str) -> bool:
    for token in SCRIPT_TOKEN_RE.findall(text):
        if not ASCII_LATIN_RE.search(token):
            continue

        if any(char in CONFUSABLE_MAP for char in token):
            return True

    return False


def _digit_obfuscation_text(text: str) -> str:
    """URL/해시/주소처럼 숫자가 정상적으로 섞이는 기계 문자열을 검사에서 제외한다."""

    text = URL_RE.sub(" ", text)
    return LONG_MACHINE_TOKEN_RE.sub(" ", text)


def _normalize_ascii_token(token: str) -> str:
    if len(token) >= 16:
        return token

    chars = list(token)

    for index in range(1, len(chars) - 1):
        char = chars[index]

        if char not in DIGIT_CONFUSABLE_MAP:
            continue

        if chars[index - 1].isalpha() and chars[index + 1].isalpha():
            chars[index] = DIGIT_CONFUSABLE_MAP[char]

    return "".join(chars)


def _normalize_non_url_segment(text: str) -> str:
    return ASCII_WORD_TOKEN_RE.sub(
        lambda match: _normalize_ascii_token(match.group(0)),
        text,
    )


def normalize_homoglyph(text: str) -> str:
    """전각/혼동 문자를 복원하되 URL·긴 식별자의 숫자는 보존한다."""

    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(CONFUSABLE_MAP.get(char, char) for char in normalized)

    parts = []
    cursor = 0

    for match in URL_RE.finditer(normalized):
        parts.append(_normalize_non_url_segment(normalized[cursor:match.start()]))
        parts.append(match.group(0))
        cursor = match.end()

    parts.append(_normalize_non_url_segment(normalized[cursor:]))
    return "".join(parts)


def analyze_homoglyph(text: str):
    reasons = []

    # 전각 영문/숫자: ＣＡＳＩＮＯ, ＣＡＳ１ＮＯ 같은 형태.
    # 전각 따옴표/괄호/기호만 있는 경우는 제외한다.
    if FULLWIDTH_ALNUM_RE.search(text):
        reasons.append("전각(Fullwidth) 영문·숫자가 ASCII 문자처럼 사용됨")

    # 서로 다른 단어가 각각 라틴/키릴 문자인 정상 다국어 문장은 제외하고,
    # cаsino처럼 같은 토큰 내부에서 문자 체계가 섞인 경우만 잡는다.
    if _contains_mixed_script_token(text):
        reasons.append("한 단어 안에 라틴 문자와 유사한 키릴/그리스 문자가 혼합됨")

    normalized = unicodedata.normalize("NFKC", text)
    digit_target = _digit_obfuscation_text(normalized)

    # URL, 긴 해시/식별자 안의 숫자는 제외한다.
    if INTERNAL_DIGIT_RE.search(digit_target):
        reasons.append("단어 내부 숫자가 유사한 알파벳 문자 대신 사용됨")

    return reasons


def detect_homoglyph_candidates(page_result):
    candidates = []

    for element in page_result["elements"]:
        text = element["text"]
        reasons = analyze_homoglyph(text)

        if not reasons:
            continue

        candidates.append(
            {
                "url": page_result["url"],
                "location": element["selector"],
                "evidence_text": text,
                "technique": "HOMOGLYPH",
                "normalized_text": normalize_homoglyph(text),
                "reason": reasons,
            }
        )

    return candidates
