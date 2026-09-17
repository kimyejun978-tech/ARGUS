import re


PX_VALUE_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)px\s*$", re.IGNORECASE)


def _parse_px(value):
    if not isinstance(value, str):
        return None

    match = PX_VALUE_RE.match(value)
    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def _is_far_outside(rect, style):
    """
    의도적인 화면 밖 배치를 판정한다.

    getBoundingClientRect()의 y는 viewport 기준이라 사용자가 아래로 스크롤하면
    정상적인 상단 요소도 -5000px처럼 보일 수 있다. 따라서 absolute/fixed 요소의
    CSS left/top 값을 우선 사용하고, 일반 absolute 요소의 음수 y만으로는 판정하지
    않는다.
    """

    position = style.get("position")

    if position not in {"absolute", "fixed"}:
        return False

    left = _parse_px(style.get("left"))
    top = _parse_px(style.get("top"))

    # 공모전 대표 예시인 left:-9999px / top:-9999px처럼 명시적으로
    # 매우 멀리 치운 CSS 위치값을 잡는다.
    if left is not None and (left < -100 or left > 5000):
        return True

    if top is not None and top < -100:
        return True

    # 수평 스크롤은 일반 사이트에서 드물고, transform 등에 의해 CSS left가 auto인
    # 경우도 있으므로 x축의 강한 이탈은 보조 신호로 유지한다.
    x = rect.get("x", 0)
    width = rect.get("width", 0)
    right = x + width

    if right < -100 or x > 5000:
        return True

    # fixed 요소는 viewport 자체에 고정되므로 y 좌표가 강하게 벗어나면 의미가 있다.
    # absolute 요소의 y는 페이지 스크롤만으로 크게 음수가 될 수 있어 사용하지 않는다.
    if position == "fixed":
        y = rect.get("y", 0)
        height = rect.get("height", 0)
        bottom = y + height

        if bottom < -100 or y > 5000:
            return True

    return False


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

        # 단순히 스크롤 때문에 viewport 위/아래로 벗어난 정상 콘텐츠는 제외한다.
        if _is_far_outside(rect, style):
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
            "scan_pass": element.get("scan_pass"),
        }

        if display_source:
            candidate["display_source"] = display_source

        candidates.append(candidate)

    return candidates
