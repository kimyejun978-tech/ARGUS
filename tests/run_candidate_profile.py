import argparse
import asyncio
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler_parallel import crawl_site
from detectors.homoglyph import detect_homoglyph_candidates
from detectors.jamo import detect_jamo_candidates
from detectors.offscreen import detect_offscreen_candidates
from detectors.transparent import detect_transparent_candidates
from verifier.contextual import verify_candidates


TECHNIQUES = ("TRANSPARENT", "OFFSCREEN", "JAMO", "HOMOGLYPH")


def _reason_key(reason):
    text = str(reason or "").strip()
    if not text:
        return "(reason 없음)"
    return text


def _candidate_key(candidate):
    return (
        candidate.get("url", ""),
        candidate.get("location", ""),
        candidate.get("technique", ""),
    )


def _collect_groups(pages):
    groups = {
        "TRANSPARENT": [],
        "OFFSCREEN": [],
        "JAMO": [],
        "HOMOGLYPH": [],
    }

    for page in pages:
        groups["TRANSPARENT"].extend(detect_transparent_candidates(page))
        groups["OFFSCREEN"].extend(detect_offscreen_candidates(page))
        groups["JAMO"].extend(detect_jamo_candidates(page))
        groups["HOMOGLYPH"].extend(detect_homoglyph_candidates(page))

    return groups


def _print_counter(title, counter, limit=20):
    print(f"\n[{title}]")
    if not counter:
        print("  (없음)")
        return

    for name, count in counter.most_common(limit):
        print(f"  {count:>6}  {name}")


async def run(url, max_pages, max_seconds, workers, discovery_workers):
    started = time.perf_counter()

    crawl_started = time.perf_counter()
    crawl = await crawl_site(
        url,
        max_pages=max_pages,
        max_seconds=max_seconds,
        worker_count=workers,
        discovery_worker_count=discovery_workers,
    )
    crawl_elapsed = time.perf_counter() - crawl_started

    pages = crawl.get("pages", [])

    detection_started = time.perf_counter()
    groups = _collect_groups(pages)

    raw = [
        candidate
        for technique in TECHNIQUES
        for candidate in groups[technique]
    ]

    detection_elapsed = time.perf_counter() - detection_started

    verifier_started = time.perf_counter()
    verified, rejected = verify_candidates(
        [groups[technique] for technique in TECHNIQUES],
        pages=pages,
    )
    verifier_elapsed = time.perf_counter() - verifier_started

    raw_by_technique = Counter(candidate.get("technique", "UNKNOWN") for candidate in raw)
    unique_by_technique = defaultdict(set)
    reason_counts = Counter()
    pass_counts = Counter()
    pass_combo_counts = Counter()

    for candidate in raw:
        technique = candidate.get("technique", "UNKNOWN")
        unique_by_technique[technique].add(_candidate_key(candidate))

        reasons = candidate.get("reason", [])
        if not reasons:
            reason_counts[f"{technique} :: (reason 없음)"] += 1
        else:
            for reason in reasons:
                reason_counts[f"{technique} :: {_reason_key(reason)}"] += 1

        scan_pass = candidate.get("scan_pass")
        if scan_pass:
            pass_counts[str(scan_pass)] += 1

    merged = {}
    for candidate in [*verified, *rejected]:
        merged[_candidate_key(candidate)] = candidate

    for candidate in merged.values():
        passes = tuple(sorted(set(candidate.get("scan_passes") or [])))
        pass_combo_counts[f"{candidate.get('technique','UNKNOWN')} :: {len(passes)} pass"] += 1

    status_counts = Counter(
        candidate.get("verification_status", "UNKNOWN")
        for candidate in [*verified, *rejected]
    )
    verified_pass_counts = Counter(
        f"{candidate.get('technique','UNKNOWN')} :: "
        f"{len(set(candidate.get('scan_passes') or []))} pass"
        for candidate in verified
    )

    verified_by_technique = Counter(
        candidate.get("technique", "UNKNOWN")
        for candidate in verified
    )

    print("===================================")
    print("       ARGUS CANDIDATE PROFILE")
    print("===================================")
    print("URL                 :", url)
    print("브라우저 worker      :", crawl.get("worker_count", workers))
    print("완료 페이지          :", crawl.get("page_count", len(pages)))
    print("frame 수            :", crawl.get("frame_count", 0))
    print("raw 관측 합          :", len(raw))
    print("dedup 후보 합        :", len(merged))
    print("최종 유지 후보       :", len(verified))
    total_elapsed = time.perf_counter() - started

    print("검증 제외 후보       :", len(rejected))
    print("크롤링 시간          :", f"{crawl_elapsed:.3f}초")
    print("Detector 시간        :", f"{detection_elapsed:.3f}초")
    print("Verifier 시간        :", f"{verifier_elapsed:.3f}초")
    print("전체 프로파일 시간   :", f"{total_elapsed:.3f}초")
    print(
        "크롤러 진단          :",
        f"known={crawl.get('known_page_count', 0)}",
        f"attempted={crawl.get('attempted_count', 0)}",
        f"pending={crawl.get('pending_count', 0)}",
        f"discovery_pending={crawl.get('discovery_pending_count', 0)}",
        f"errors={len(crawl.get('errors', []))}",
        f"browser_retries={crawl.get('browser_retry_count', 0)}",
        f"page_limit={crawl.get('page_limit_reached', False)}",
        f"time_limit={crawl.get('time_limit_reached', False)}",
    )

    if crawl.get("errors"):
        print("\n[크롤러 오류 상위 5건]")
        for error in crawl["errors"][:5]:
            print(
                " -",
                error.get("url", ""),
                "|",
                str(error.get("error", ""))[:220],
            )

    if crawl.get("discovery_error_count", 0):
        print(
            "\nHTTP discovery 실패:",
            crawl.get("discovery_error_count", 0),
        )

    print("\n[기법별 raw / unique / final]")
    for technique in TECHNIQUES:
        raw_count = raw_by_technique.get(technique, 0)
        unique_count = len(unique_by_technique.get(technique, set()))
        final_count = verified_by_technique.get(technique, 0)
        print(
            f"  {technique:<11} "
            f"raw={raw_count:>6} "
            f"unique={unique_count:>5} "
            f"final={final_count:>4}"
        )

    print("\n[Verifier status]")
    for status in ("CONFIRMED", "SUSPICIOUS", "BENIGN_LIKELY", "UNKNOWN"):
        count = status_counts.get(status, 0)
        if count:
            print(f"  {status:<14} {count:>6}")

    _print_counter("구조 후보 reason 상위", reason_counts)
    _print_counter("scan pass별 raw 관측", pass_counts)
    _print_counter("dedup 후보 pass 개수", pass_combo_counts)
    _print_counter("최종 유지 후보 pass 개수", verified_pass_counts)

    if verified:
        print("\n[최종 유지 후보 상위 20건]")
        for candidate in verified[:20]:
            print(
                " -",
                candidate.get("verification_status"),
                candidate.get("technique"),
                candidate.get("url"),
                "|",
                candidate.get("evidence_text", "")[:120],
                "|",
                "open=" + str(candidate.get("open_set_score")),
                "known=" + str(candidate.get("known_score")),
                "passes=" + str(len(candidate.get("scan_passes") or [])),
                "legacy_sup=" + str(candidate.get("legacy_semantic_support")),
                "multi_sup=" + str(candidate.get("multilingual_support")),
                "visible_eq=" + str(candidate.get("visible_equivalent_count")),
                "multi=" + str(candidate.get("multi_technique_count")),
                "independent=" + str(candidate.get("independent_technique_count")),
                "| selector=" + str(candidate.get("location", ""))[:180],
                "| reasons=" + "; ".join(candidate.get("reason", [])),
            )

    return {
        "pages": crawl.get("page_count", len(pages)),
        "raw": len(raw),
        "unique": len(merged),
        "verified": len(verified),
        "crawl_elapsed": crawl_elapsed,
        "detection_elapsed": detection_elapsed,
        "verifier_elapsed": verifier_elapsed,
        "elapsed": total_elapsed,
    }


def main():
    parser = argparse.ArgumentParser(
        description="ARGUS 정상 사이트 후보량/오탐 진단 프로파일러"
    )
    parser.add_argument("url", help="진단할 정상 공개 웹사이트 URL")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--max-seconds", type=float, default=180.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--discovery-workers", type=int, default=8)
    args = parser.parse_args()

    if args.max_pages < 1:
        parser.error("--max-pages는 1 이상이어야 합니다")

    asyncio.run(
        run(
            args.url,
            args.max_pages,
            args.max_seconds,
            args.workers,
            args.discovery_workers,
        )
    )


if __name__ == "__main__":
    main()
