import re
import unicodedata


# 한글 호환 자모: ㄱ ~ ㆎ
COMPATIBILITY_JAMO_RE = re.compile(r"[\u3131-\u318E]")

# 유니코드 한글 자모 블록: ᄀ ~ ᇿ
HANGUL_JAMO_RE = re.compile(r"[\u1100-\u11FF]")

# 모음이 하나도 없는 'ㅋㅋㅋ', 'ㅎㅎ' 같은 표현은
# 현재 단계에서는 JAMO 후보에서 제외한다.
JAMO_VOWEL_RE = re.compile(r"[\u314F-\u3163\u1161-\u1175]")


def contains_jamo_obfuscation(text: str) -> bool:
    """분리된 한글 자모가 실제 단어를 만들 가능성이 있는지 확인한다."""

    has_jamo = bool(
        COMPATIBILITY_JAMO_RE.search(text)
        or HANGUL_JAMO_RE.search(text)
    )

    if not has_jamo:
        return False

    # 모음이 있어야 '분리된 음절'로 볼 수 있다.
    # 단순 채팅 표현(ㅋㅋㅋ, ㅎㅎ 등)의 오탐을 조금 줄이기 위한 조건이다.
    return bool(JAMO_VOWEL_RE.search(text))


def normalize_jamo(text: str) -> str:
    """Unicode NFKC 정규화로 분리 자모를 가능한 범위에서 음절로 합친다."""

    return unicodedata.normalize("NFKC", text)


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
                    "한글 음절 대신 분리된 자모와 모음이 함께 사용됨"
                ],
            }
        )

    return candidates
