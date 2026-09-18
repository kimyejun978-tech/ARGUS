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
from verifier.contextual import verify_candidates


MAX_CRAWL_PAGES = int(os.getenv("ARGUS_MAX_PAGES", "10000"))
MAX_CRAWL_SECONDS = float(os.getenv("ARGUS_MAX_SECONDS", "1620"))

# 심사 PC 사양을 미리 알 수 없으므로 8 worker를 무조건 강제하지 않는다.
# 논리 CPU 수를 기준으로 4~8 사이에서 자동 선택하고, ARGUS_WORKERS 환경변수로
# 언제든 명시적으로 덮어쓸 수 있게 한다.
DEFAULT_CRAWL_WORKERS = min(8, max(4, os.cpu_count() or 4))
CRAWL_WORKERS = max(
    1,
    int(os.getenv("ARGUS_WORKERS", str(DEFAULT_CRAWL_WORKERS))),
)
DISCOVERY_WORKERS = max(0, int(os.getenv("ARGUS_DISCOVERY_WORKERS", "8")))


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

        if candidate.get("scan_passes"):
            print("관측 상태 :", ", ".join(candidate["scan_passes"]))

        if candidate.get("verification_status"):
            print("판정 상태 :", candidate["verification_status"])

        if candidate.get("semantic_score") is not None:
            print("known 의미 점수 :", f"{candidate['semantic_score']:.3f}")

        if candidate.get("multilingual_score") is not None:
            print("다국어 의미 점수 :", f"{candidate['multilingual_score']:.3f}")

        if candidate.get("semantic_backend"):
            print("다국어 backend :", candidate["semantic_backend"])

        if candidate.get("structure_score") is not None:
            print("구조 점수 :", f"{candidate['structure_score']:.3f}")

        if candidate.get("known_score") is not None:
            print("known 결합 점수 :", f"{candidate['known_score']:.3f}")

        if candidate.get("open_set_score") is not None:
            print("open-set 점수 :", f"{candidate['open_set_score']:.3f}")

        if candidate.get("verification_score") is not None:
            print("최종 결합 점수 :", f"{candidate['verification_score']:.3f}")

        if candidate.get("template_repeat_count", 1) > 1:
            print(
                "템플릿 반복 :",
                f"{candidate['template_repeat_count']}페이지",
            )

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
        f"하드 최대 {MAX_CRAWL_PAGES} 완료 페이지"
    )
    print(
        f"[ARGUS] 브라우저 정밀 검사 : {CRAWL_WORKERS} worker / "
        "각 페이지 5-pass"
    )
    print(
        f"[ARGUS] HTTP 고속 discovery : {DISCOVERY_WORKERS} worker / "
        "HTML + robots + sitemap"
    )
    print(
        "[ARGUS] 다중 검사 : 데스크톱 즉시·안정·스크롤 + "
        "모바일 안정·스크롤"
    )
    print(
        "[ARGUS] 검증기 v3 : known 의미 모델 + 다국어 의미 분기 + "
        "open-set 구조 이상 탐지"
    )

    started = datetime.now().astimezone()
    start_timer = time.perf_counter()

    crawl_result = await crawl_site(
        target,
        max_pages=MAX_CRAWL_PAGES,
        max_seconds=MAX_CRAWL_SECONDS,
        worker_count=CRAWL_WORKERS,
        discovery_worker_count=DISCOVERY_WORKERS,
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
        candidate_groups,
        pages=crawl_result["pages"],
    )

    confirmed_candidates = [
        item
        for item in verified_candidates
        if item.get("verification_status") == "CONFIRMED"
    ]
    suspicious_candidates = [
        item
        for item in verified_candidates
        if item.get("verification_status") == "SUSPICIOUS"
    ]

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
    print("브라우저 worker   :", crawl_result.get("worker_count", CRAWL_WORKERS))
    print(
        "discovery worker  :",
        crawl_result.get("discovery_worker_count", DISCOVERY_WORKERS),
    )
    print("발견 고유 URL 수  :", crawl_result.get("known_page_count", 0))
    print("정밀검사 시도 수 :", crawl_result.get("attempted_count", 0))
    print("브라우저 재시도   :", crawl_result.get("browser_retry_count", 0))
    print("다운로드 skip     :", crawl_result.get("browser_download_skip_count", 0))
    print("HTTP fetch 수     :", crawl_result.get("discovery_fetch_count", 0))
    print("HTTP HTML 분석 수 :", crawl_result.get("discovery_html_count", 0))
    print("robots 분석 수    :", crawl_result.get("discovery_robots_count", 0))
    print("sitemap 분석 수   :", crawl_result.get("discovery_sitemap_count", 0))
    print("분석 완료 페이지 :", crawl_result["page_count"])
    print("분석 frame 수    :", crawl_result["frame_count"])
    print("고유 텍스트 요소 :", crawl_result["element_count"])
    print("다중 관측 요소   :", crawl_result.get("observation_count", 0))
    print("검사 패스 합계   :", crawl_result.get("scan_pass_count", 0))
    print("TRANSPARENT 후보 :", len(transparent_candidates))
    print("OFFSCREEN 후보   :", len(offscreen_candidates))
    print("JAMO 후보        :", len(jamo_candidates))
    print("HOMOGLYPH 후보   :", len(homoglyph_candidates))
    print("구조 후보 관측합 :", raw_candidate_count)
    print("CONFIRMED        :", len(confirmed_candidates))
    print("SUSPICIOUS       :", len(suspicious_candidates))
    print("BENIGN_LIKELY    :", len(rejected_candidates))
    print("최종 findings    :", len(result_json["findings"]))
    print("result.json      :", result_path)
    print("탐지 시간        :", f"{elapsed_sec:.3f}초")

    if crawl_result.get("time_limit_reached"):
        print(
            f"주의              : 비상 watchdog "
            f"{MAX_CRAWL_SECONDS:.0f}초에 도달했습니다. "
            f"브라우저 대기 URL 약 {crawl_result.get('pending_count', 0)}개 / "
            f"discovery 대기 약 {crawl_result.get('discovery_pending_count', 0)}개"
        )
    elif crawl_result.get("page_limit_reached"):
        print(
            f"주의              : 완료 페이지 안전장치 "
            f"{MAX_CRAWL_PAGES}개에 도달했습니다."
        )

    if crawl_result["errors"]:
        print("접속/검사 실패   :", len(crawl_result["errors"]))

    if crawl_result.get("discovery_error_count", 0):
        print(
            "HTTP discovery 실패:",
            crawl_result.get("discovery_error_count", 0),
        )

    if verified_candidates:
        print()
        print("==============================")
        print("     최종 유지 후보")
        print("==============================")
        print_candidates("유지 후보", verified_candidates)

    if rejected_candidates:
        print()
        print(
            f"[ARGUS] 구조 탐지 후보 {len(rejected_candidates)}건은 "
            "known 의미·다국어·open-set 결합 검증에서 정상 UI 가능성이 "
            "더 높아 result.json에서 제외했습니다."
        )


if __name__ == "__main__":
    asyncio.run(main())
