import re
import unicodedata


CONFUSABLE_MAP = {
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "Х": "X", "а": "a", "е": "e", "о": "o", "р": "p",
    "с": "c", "х": "x", "у": "y",
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
FULLWIDTH_ALNUM_RE = re.compile(r"[\uFF10-\uFF19\uFF21-\uFF3A\uFF41-\uFF5A]")
SCRIPT_TOKEN_RE = re.compile(r"[A-Za-z\u0370-\u03FF\u0400-\u04FF]+")
ASCII_WORD_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
INTERNAL_DIGIT_RE = re.compile(r"(?<=[A-Za-z])[0134578](?=[A-Za-z])")
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
LONG_MACHINE_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{16,}\b")

SOURCE_SAMPLE_MARKERS = (
    "<!--",
    "-->",
    "</",
    "<script",
    "function ",
    "var ",
    "let ",
    "const ",
    "document.",
    "getelementbyid",
    "=>",
    "{",
    "}",
    ";",
)


def _contains_mixed_script_token(text: str) -> bool:
    for token in SCRIPT_TOKEN_RE.findall(text):
        if not ASCII_LATIN_RE.search(token):
            continue

        if any(char in CONFUSABLE_MAP for char in token):
            return True

    return False


def _looks_like_source_sample(text: str) -> bool:
    """
    길게 표시된 HTML/JavaScript 예제 소스는 식별자 내부 숫자가 흔하다.
    예: item1Code, api2List. 이런 텍스트의 숫자를 HOMOGLYPH로 해석하면
    정상 개발자 문서/예제 페이지에서 오탐이 커진다.

    이 억제는 'digit-internal' 규칙에만 적용한다. 전각 문자나 실제
    Latin+키릴/그리스 혼합은 소스 예제 안에서도 별도로 계속 탐지한다.
    """

    text = text or ""
    if len(text) < 120:
        return False

    lowered = text.lower()
    marker_hits = sum(
        1
        for marker in SOURCE_SAMPLE_MARKERS
        if marker in lowered
    )

    # HTML comment로 시작하는 긴 코드 예제는 marker가 적더라도 소스 블록일
    # 가능성이 높다. 일반 장문은 여러 코드 문법 표지가 함께 있어야 억제한다.
    return (
        ("<!--" in lowered and marker_hits >= 2)
        or marker_hits >= 3
    )


def _digit_obfuscation_text(text: str) -> str:
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

    if FULLWIDTH_ALNUM_RE.search(text):
        reasons.append("전각(Fullwidth) 영문·숫자가 ASCII 문자처럼 사용됨")

    if _contains_mixed_script_token(text):
        reasons.append("한 단어 안에 라틴 문자와 유사한 키릴/그리스 문자가 혼합됨")

    normalized = unicodedata.normalize("NFKC", text)
    digit_target = _digit_obfuscation_text(normalized)

    if (
        INTERNAL_DIGIT_RE.search(digit_target)
        and not _looks_like_source_sample(text)
    ):
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
                "scan_pass": element.get("scan_pass"),
            }
        )

    return candidates
