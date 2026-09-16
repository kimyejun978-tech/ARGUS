import re
import unicodedata


# 한글 호환 자모: ㄱ ~ ㆎ
COMPATIBILITY_JAMO_RE = re.compile(r"[\u3131-\u318E]")

# 유니코드 한글 자모 블록: ᄀ ~ ᇿ
HANGUL_JAMO_RE = re.compile(r"[\u1100-\u11FF]")

# 실제로 한 음절을 시작할 수 있는 '초성 + 중성' 조합만 후보로 본다.
# 이 조건으로 ㅜㅜ, ㅡㅡ, ㅣ 같은 이모티콘/구분문자를 제외한다.
COMPAT_SYLLABLE_START_RE = re.compile(
    r"[ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ][ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ]"
)
MODERN_SYLLABLE_START_RE = re.compile(r"[\u1100-\u1112][\u1161-\u1175]")


# 호환 자모를 실제 한글 음절로 조합하기 위한 인덱스 표.
# NFKC만 사용하면 'ㅋㅜㅍㅗㄴ' 같은 문자열의 마지막 받침이
# 완전히 합쳐지지 않는 경우가 있어 간단한 음절 조합기를 함께 사용한다.
CHOSEONG_INDEX = {
    "ㄱ": 0, "ㄲ": 1, "ㄴ": 2, "ㄷ": 3, "ㄸ": 4, "ㄹ": 5,
    "ㅁ": 6, "ㅂ": 7, "ㅃ": 8, "ㅅ": 9, "ㅆ": 10, "ㅇ": 11,
    "ㅈ": 12, "ㅉ": 13, "ㅊ": 14, "ㅋ": 15, "ㅌ": 16,
    "ㅍ": 17, "ㅎ": 18,
}

JUNGSEONG_INDEX = {
    "ㅏ": 0, "ㅐ": 1, "ㅑ": 2, "ㅒ": 3, "ㅓ": 4, "ㅔ": 5,
    "ㅕ": 6, "ㅖ": 7, "ㅗ": 8, "ㅘ": 9, "ㅙ": 10, "ㅚ": 11,
    "ㅛ": 12, "ㅜ": 13, "ㅝ": 14, "ㅞ": 15, "ㅟ": 16,
    "ㅠ": 17, "ㅡ": 18, "ㅢ": 19, "ㅣ": 20,
}

JONGSEONG_INDEX = {
    "ㄱ": 1, "ㄲ": 2, "ㄳ": 3, "ㄴ": 4, "ㄵ": 5, "ㄶ": 6,
    "ㄷ": 7, "ㄹ": 8, "ㄺ": 9, "ㄻ": 10, "ㄼ": 11, "ㄽ": 12,
    "ㄾ": 13, "ㄿ": 14, "ㅀ": 15, "ㅁ": 16, "ㅂ": 17,
    "ㅄ": 18, "ㅅ": 19, "ㅆ": 20, "ㅇ": 21, "ㅈ": 22,
    "ㅊ": 23, "ㅋ": 24, "ㅌ": 25, "ㅍ": 26, "ㅎ": 27,
}


def contains_jamo_obfuscation(text: str) -> bool:
    """분리 자모가 실제 음절을 구성하려는 형태인지 확인한다."""

    if not (
        COMPATIBILITY_JAMO_RE.search(text)
        or HANGUL_JAMO_RE.search(text)
    ):
        return False

    # 단순 감정 표현 'ㅜㅜ', 'ㅡㅡ', 장식용 'ㅣ' 등은 초성+중성
    # 조합이 없으므로 후보에서 제외한다.
    return bool(
        COMPAT_SYLLABLE_START_RE.search(text)
        or MODERN_SYLLABLE_START_RE.search(text)
    )


def _compose_compatibility_jamo(text: str) -> str:
    """ㄱ/ㅏ 형태의 호환 자모를 가능한 범위에서 완성형 한글로 조합한다."""

    result = []
    index = 0

    while index < len(text):
        current = text[index]

        if (
            current in CHOSEONG_INDEX
            and index + 1 < len(text)
            and text[index + 1] in JUNGSEONG_INDEX
        ):
            choseong = CHOSEONG_INDEX[current]
            jungseong = JUNGSEONG_INDEX[text[index + 1]]
            jongseong = 0
            consumed = 2

            if index + 2 < len(text) and text[index + 2] in JONGSEONG_INDEX:
                final_candidate = text[index + 2]

                # 뒤에 바로 모음이 오면 다음 음절의 초성으로 사용하는 것이 자연스럽다.
                can_start_next_syllable = (
                    final_candidate in CHOSEONG_INDEX
                    and index + 3 < len(text)
                    and text[index + 3] in JUNGSEONG_INDEX
                )

                if not can_start_next_syllable:
                    jongseong = JONGSEONG_INDEX[final_candidate]
                    consumed = 3

            codepoint = 0xAC00 + ((choseong * 21 + jungseong) * 28) + jongseong
            result.append(chr(codepoint))
            index += consumed
            continue

        result.append(current)
        index += 1

    return "".join(result)


def normalize_jamo(text: str) -> str:
    """호환 자모와 현대 한글 자모를 가능한 범위에서 완성형 음절로 합친다."""

    composed = _compose_compatibility_jamo(text)

    return unicodedata.normalize(
        "NFC",
        unicodedata.normalize("NFKC", composed),
    )


def detect_jamo_candidates(page_result):
    candidates = []

    for element in page_result["elements"]:
        text = element["text"]

        if not contains_jamo_obfuscation(text):
            continue

        normalized_text = normalize_jamo(text)

        candidates.append(
            {
                "url": page_result["url"],
                "location": element["selector"],
                "evidence_text": text,
                "technique": "JAMO",
                "normalized_text": normalized_text,
                "reason": [
                    "한글 음절을 우회하기 위한 초성·중성 분리 조합이 사용됨"
                ],
            }
        )

    return candidates
