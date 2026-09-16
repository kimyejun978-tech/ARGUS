import asyncio
import os
import time
from datetime import datetime
from pathlib import Path

from crawler_parallel import crawl_site
from detectors.homoglyph import detect_homoglyph_candidates
from detectors.jamo import detect_jamo_candidates
from detectors.offscreen import detect_offscreen_candidates
from detectors.transparent import detect_transparent_candidates
from json_exporter import export_result_json
from verifier.rule_based import verify_candidates


# 정밀 검사 우선 정책.
# 정상 종료 조건은 "발견한 URL 큐가 모두 비는 것"이다.
# 아래 시간은 목표 시간이 아니라 대회 30분 상한 전에 결과를 보존하기 위한 비상 watchdog이다.
MAX_CRAWL_PAGES = int(os.getenv("ARGUS_MAX_PAGES", "10000"))
MAX_CRAWL_SECONDS = float(os.getenv("ARGUS_MAX_SECONDS", "1620"))
CRAWL_WORKERS = max(1, int(os.getenv("ARGUS_WORKERS", "4")))


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
        print(f"[{title} {index}]")
        print("원문 :", candidate["evidence_text"])
        print("페이지 :", candidate["url"])
        print("위치 :", candidate["location"])
        print("유형 :", candidate["technique"])
        print("근거 :", ", ".join(candidate["reason"]))

        if candidate.get("normalized_text") is not None:
            print("정규화 :", candidate["normalized_text"])

        if candidate.get("rect") is not None:
            print("좌표 :", candidate["rect"])

        if candidate.get("opacity_source"):
            print("숨김 적용 위치 :", candidate["opacity_source"])

        if candidate.get("observation_count", 1) > 1:
            print("다중 관측 :", f"{candidate['observation_count']}회")

        if candidate.get("verification_reason"):
            print("검증 :", candidate["verification_reason"])


async def main():
    print("==============================")
    print("            ARGUS")
    print("==============================")

    target = input("검사할 URL 또는 파일: ").strip()
    target = normalize_target(target)

    print("[ARGUS] 진입 URL :", target)
    print(
        f"[ARGUS] 비상 watchdog : {MAX_CRAWL_SECONDS:.0f}초 / "
        f"하드 최대 {MAX_CRAWL_PAGES}페이지"
    )
    print(
        f"[ARGUS] 병렬 검사 : {CRAWL_WORKERS} worker / "
        "각 페이지 5-pass 정밀 검사"
    )
    print(
        "[ARGUS] 다중 검사 : 데스크톱 즉시·안정·스크롤 + "
        "모바일 안정·스크롤"
    )

    started = datetime.now().astimezone()
    start_timer = time.perf_counter()

    crawl_result = await crawl_site(
        target,
        max_pages=MAX_CRAWL_PAGES,
        max_seconds=MAX_CRAWL_SECONDS,
        worker_count=CRAWL_WORKERS,
    )

    transparent_candidates = []
    offscreen_candidates = []
    jamo_candidates = []
    homoglyph_candidates = []

    for page_result in crawl_result["pages"]:
        transparent_candidates.extend(
            detect_transparent_candidates(page_result)
        )
        offscreen_candidates.extend(
            detect_offscreen_candidates(page_result)
        )
        jamo_candidates.extend(
            detect_jamo_candidates(page_result)
        )
        homoglyph_candidates.extend(
            detect_homoglyph_candidates(page_result)
        )

    candidate_groups = [
        transparent_candidates,
        offscreen_candidates,
        jamo_candidates,
        homoglyph_candidates,
    ]

    verified_candidates, rejected_candidates = verify_candidates(
        candidate_groups
    )

    finished = datetime.now().astimezone()
    elapsed_sec = round(time.perf_counter() - start_timer, 3)

    result_path, result_json = export_result_json(
        entry_url=crawl_result["entry_url"],
        started_at=started.isoformat(timespec="seconds"),
        finished_at=finished.isoformat(timespec="seconds"),
        elapsed_sec=elapsed_sec,
        candidate_groups=[verified_candidates],
    )

    raw_candidate_count = sum(len(group) for group in candidate_groups)

    print()
    print("==============================")
    print("         분석 결과")
    print("==============================")
    print("병렬 worker 수   :", crawl_result.get("worker_count", CRAWL_WORKERS))
    print("분석 페이지 수   :", crawl_result["page_count"])
    print("분석 frame 수    :", crawl_result["frame_count"])
    print("고유 텍스트 요소 :", crawl_result["element_count"])
    print("다중 관측 요소   :", crawl_result.get("observation_count", 0))
    print("검사 패스 합계   :", crawl_result.get("scan_pass_count", 0))
    print("TRANSPARENT 후보 :", len(transparent_candidates))
    print("OFFSCREEN 후보   :", len(offscreen_candidates))
    print("JAMO 후보        :", len(jamo_candidates))
    print("HOMOGLYPH 후보   :", len(homoglyph_candidates))
    print("구조 후보 관측합 :", raw_candidate_count)
    print("1차 검증 통과    :", len(verified_candidates))
    print("1차 검증 보류    :", len(rejected_candidates))
    print("최종 findings    :", len(result_json["findings"]))
    print("result.json      :", result_path)
    print("탐지 시간        :", f"{elapsed_sec:.3f}초")

    if crawl_result.get("time_limit_reached"):
        print(
            f"주의              : 비상 watchdog "
            f"{MAX_CRAWL_SECONDS:.0f}초에 도달했습니다. "
            f"미완료 URL 약 {crawl_result.get('pending_count', 0)}개"
        )
    elif crawl_result.get("page_limit_reached"):
        print(
            f"주의              : 하드 페이지 안전장치 "
            f"{MAX_CRAWL_PAGES}개에 도달했습니다."
        )

    if crawl_result["errors"]:
        print("접속/검사 실패   :", len(crawl_result["errors"]))

    if verified_candidates:
        print()
        print("==============================")
        print("       1차 검증 통과 후보")
        print("==============================")
        print_candidates("검증 통과 후보", verified_candidates)

    if rejected_candidates:
        print()
        print(
            f"[ARGUS] 기법은 감지됐지만 불법광고 내용 신호가 부족한 "
            f"후보 {len(rejected_candidates)}건은 result.json에서 제외했습니다."
        )


if __name__ == "__main__":
    asyncio.run(main())
