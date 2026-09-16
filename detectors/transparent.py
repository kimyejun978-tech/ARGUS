def detect_transparent_candidates(page_result):

    candidates = []


    for element in page_result["elements"]:

        reasons = []


        # 자신 또는 부모의 opacity 때문에
        # 실제로 완전히 투명한 경우
        if element["effectiveOpacity"] <= 0.001:

            reasons.append(
                "opacity가 0인 요소 또는 부모 요소에 의해 숨겨짐"
            )


        # color: transparent
        if element["textColorAlpha"] <= 0.001:

            reasons.append(
                "텍스트 색상이 완전히 투명함"
            )


        # 글자색과 배경색이 동일
        if element["sameTextBackground"]:

            reasons.append(
                "텍스트 색상과 배경 색상이 동일함"
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
                "TRANSPARENT",

            "reason":
                reasons,

            "opacity_source":
                element["opacitySource"]
        }


        candidates.append(candidate)


    return candidates