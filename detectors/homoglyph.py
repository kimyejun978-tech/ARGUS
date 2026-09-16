import re
import unicodedata


# 눈으로 봤을 때 라틴 문자와 매우 비슷한 키릴/그리스 문자 일부.
# 현재는 오탐을 줄이기 위해 자주 쓰이는 confusable만 보수적으로 매핑한다.
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

# 단어 중간 숫자를 문자처럼 사용하는 흔한 형태.
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
FULLWIDTH_ASCII_RE = re.compile(r"[\uFF01-\uFF5E]")
INTERNAL_DIGIT_RE = re.compile(r"(?<=[A-Za-z])[0134578](?=[A-Za-z])")


def normalize_homoglyph(text: str) -> str:
    """전각/혼동 문자를 사람이 기대하는 ASCII 형태로 최대한 복원한다."""

    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(CONFUSABLE_MAP.get(char, char) for char in normalized)

    chars = list(normalized)

    for index in range(1, len(chars) - 1):
        char = chars[index]

        if char not in DIGIT_CONFUSABLE_MAP:
            continue

        if chars[index - 1].isascii() and chars[index - 1].isalpha() \
                and chars[index + 1].isascii() and chars[index + 1].isalpha():
            chars[index] = DIGIT_CONFUSABLE_MAP[char]

    return "".join(chars)


def analyze_homoglyph(text: str):
    reasons = []

    # 전각 영문/숫자/기호: ＣＡＳＩＮＯ 같은 형태
    if FULLWIDTH_ASCII_RE.search(text):
        reasons.append("전각(Fullwidth) 문자가 ASCII 문자처럼 사용됨")

    # 라틴 문자 사이에 키릴/그리스 confusable이 섞여 있는지 확인.
    # 러시아어/그리스어 문장 자체를 무조건 잡는 오탐을 피하기 위한 조건이다.
    has_ascii_latin = bool(ASCII_LATIN_RE.search(text))
    has_confusable = any(char in CONFUSABLE_MAP for char in text)

    if has_ascii_latin and has_confusable:
        reasons.append("라틴 문자와 시각적으로 유사한 키릴/그리스 문자가 혼합됨")

    # CAS1NO처럼 문자 사이의 숫자를 글자 대용으로 사용한 경우
    if INTERNAL_DIGIT_RE.search(unicodedata.normalize("NFKC", text)):
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
