from detectors.offscreen import detect_offscreen_candidates
import asyncio
from pathlib import Path

from crawler import scan_page
from detectors.transparent import detect_transparent_candidates


def normalize_target(target):
    # 이미 정상적인 URL이면 그대로 사용
    if target.startswith(("http://", "https://", "file://")):
        return target

    # 로컬 파일인지 확인
    path = Path(target)

    if path.exists():
        return path.resolve().as_uri()

    # URL인데 https://를 생략한 경우
    return "https://" + target


async def main():

    print("==============================")
    print("            ARGUS")
    print("==============================")

    target = input(
        "검사할 URL 또는 파일: "
    ).strip()

    target = normalize_target(target)

    print("[ARGUS] 검사 대상 :", target)

    result = await scan_page(target)

    candidates = detect_transparent_candidates(
        result
    )
    offscreen_candidates = (
        detect_offscreen_candidates(
            result
    )
)

    print()
    print("==============================")
    print("         분석 결과")
    print("==============================")

    print(
        "페이지 제목 :",
        result["title"]
    )

    print(
        "텍스트 요소 :",
        len(result["elements"])
    )

    print(
        "TRANSPARENT 후보 :",
        len(candidates)
    )

    print(
        "OFFSCREEN 후보   :",
        len(offscreen_candidates)
    )

    for index, candidate in enumerate(
        offscreen_candidates,
        start=1
    ):

        print()
        print(
            f"[OFFSCREEN 후보 {index}]"
        )

        print(
            "원문 :",
            candidate["evidence_text"]
        )

        print(
            "위치 :",
            candidate["location"]
        )

        print(
            "유형 :",
            candidate["technique"]
        )

        print(
            "근거 :",
            ", ".join(
                candidate["reason"]
            )
        )

        print(
            "좌표 :",
            candidate["rect"]
        )


if __name__ == "__main__":
    asyncio.run(main())