def _is_far_outside(rect, position):
    """일반적인 스크롤 영역은 제외하고 의도적으로 멀리 치운 요소만 판정한다."""

    if position not in {"absolute", "fixed"}:
        return False

    x = rect.get("x", 0)
    y = rect.get("y", 0)
    width = rect.get("width", 0)
    height = rect.get("height", 0)

    right = x + width
    bottom = y + height

    # 대표 예시인 left:-9999px 같은 강한 화면 밖 이동을 잡는다.
    # 단순히 아래쪽에 있어 아직 스크롤하지 않은 정상 콘텐츠는 잡지 않는다.
    return (
        right < -100
        or bottom < -100
        or x > 5000
        or y > 5000
    )


def detect_offscreen_candidates(page_result):
    candidates = []

    for element in page_result["elements"]:
        reasons = []
        style = element["style"]
        rect = element["rect"]

        display_source = element.get("displayNoneSource")

        # 본인 또는 상위 요소의 display:none
        if display_source:
            if display_source == element["selector"]:
                reasons.append("display:none으로 요소가 숨겨짐")
            else:
                reasons.append("상위 요소의 display:none으로 요소가 숨겨짐")

        # font-size 0~1px
        try:
            font_size = float(style["fontSize"].replace("px", ""))

            if font_size <= 1:
                reasons.append(
                    f"글자 크기가 {font_size}px로 매우 작음"
                )

        except (ValueError, AttributeError):
            pass

        # 화면 밖 은닉: 단순히 현재 viewport 밖이라는 이유만으로는 판정하지 않는다.
        # absolute/fixed 요소가 비정상적으로 먼 좌표로 이동한 경우에만 후보로 잡는다.
        if _is_far_outside(rect, style.get("position")):
            reasons.append("요소가 비정상적으로 먼 화면 밖 좌표에 배치됨")

        if not reasons:
            continue

        candidate = {
            "url": page_result["url"],
            "location": element["selector"],
            "evidence_text": element["text"],
            "technique": "OFFSCREEN",
            "reason": reasons,
            "rect": rect,
        }

        if display_source:
            candidate["display_source"] = display_source

        candidates.append(candidate)

    return candidates
