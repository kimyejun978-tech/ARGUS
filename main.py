import asyncio
import time
from datetime import datetime
from pathlib import Path

from crawler import scan_page
from detectors.homoglyph import detect_homoglyph_candidates
from detectors.jamo import detect_jamo_candidates
from detectors.offscreen import detect_offscreen_candidates
from detectors.transparent import detect_transparent_candidates
from json_exporter import export_result_json


def normalize_target(target):
    if target.startswith(("http://", "https://", "file://")):
        return target

    path = Path(target)

    if path.exists():
        return path.resolve().as_uri()

    return "https://" + target


def print_candidates(title, candidates):
    for index, candidate in enumerate(candidates, start=1):
        print()
        print(f"[{title} 후보 {index}]")
        print("원문 :", candidate["evidence_text"])
        print("위치 :", candidate["location"])
        print("유형 :", candidate["technique"])
        print("근거 :", ", ".join(candidate["reason"]))

        if candidate.get("normalized_text") is not None:
            print("정규화 :", candidate["normalized_text"])

        if candidate.get("rect") is not None:
            print("좌표 :", candidate["rect"])

        if candidate.get("opacity_source"):
            print("숨김 적용 위치 :", candidate["opacity_source"])


async def main():
    print("==============================")
    print("            ARGUS")
    print("==============================")

    target = input("검사할 URL 또는 파일: ").strip()
    target = normalize_target(target)

    print("[ARGUS] 검사 대상 :", target)

    started = datetime.now().astimezone()
    start_timer = time.perf_counter()

    result = await scan_page(target)

    transparent_candidates = detect_transparent_candidates(result)
    offscreen_candidates = detect_offscreen_candidates(result)
    jamo_candidates = detect_jamo_candidates(result)
    homoglyph_candidates = detect_homoglyph_candidates(result)

    finished = datetime.now().astimezone()
    elapsed_sec = round(time.perf_counter() - start_timer, 3)

    result_path, result_json = export_result_json(
        entry_url=target,
        started_at=started.isoformat(timespec="seconds"),
        finished_at=finished.isoformat(timespec="seconds"),
        elapsed_sec=elapsed_sec,
        candidate_groups=[
            transparent_candidates,
            offscreen_candidates,
            jamo_candidates,
            homoglyph_candidates,
        ],
    )

    print()
    print("==============================")
    print("         분석 결과")
    print("==============================")
    print("페이지 제목 :", result["title"])
    print("텍스트 요소 :", len(result["elements"]))
    print("TRANSPARENT 후보 :", len(transparent_candidates))
    print("OFFSCREEN 후보   :", len(offscreen_candidates))
    print("JAMO 후보        :", len(jamo_candidates))
    print("HOMOGLYPH 후보   :", len(homoglyph_candidates))
    print("최종 findings    :", len(result_json["findings"]))
    print("result.json      :", result_path)
    print("탐지 시간        :", f"{elapsed_sec:.3f}초")

    print_candidates("TRANSPARENT", transparent_candidates)
    print_candidates("OFFSCREEN", offscreen_candidates)
    print_candidates("JAMO", jamo_candidates)
    print_candidates("HOMOGLYPH", homoglyph_candidates)


if __name__ == "__main__":
    asyncio.run(main())
