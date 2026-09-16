def detect_offscreen_candidates(page_result):

    candidates = []


    for element in page_result["elements"]:

        reasons = []

        style = element["style"]

        rect = element["rect"]


        # display:none
        if style["display"] == "none":

            reasons.append(
                "display:none으로 요소가 숨겨짐"
            )


        # font-size 0~1px
        try:

            font_size = float(
                style["fontSize"]
                .replace("px", "")
            )

            if font_size <= 1:

                reasons.append(
                    f"글자 크기가 {font_size}px로 매우 작음"
                )

        except (ValueError, AttributeError):

            pass


        # 화면 밖에 위치한 요소
        if (
            not element["inViewport"]
            and style["display"] != "none"
            and rect["width"] > 0
            and rect["height"] > 0
        ):

            reasons.append(
                "요소가 브라우저 화면 영역 밖에 위치함"
            )


        if not reasons:
            continue


        candidate = {

            "url":
                page_result["url"],

            "location":
                element["selector"],

            "evidence_text":
                element["text"],

            "technique":
                "OFFSCREEN",

            "reason":
                reasons,

            "rect":
                rect
        }


        candidates.append(
            candidate
        )


    return candidates