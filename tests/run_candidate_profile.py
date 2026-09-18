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

    crawl = await crawl_site(
        url,
        max_pages=max_pages,
        max_seconds=max_seconds,
        worker_count=workers,
        discovery_worker_count=discovery_workers,
    )

    elapsed = time.perf_counter() - started
    pages = crawl.get("pages", [])
    groups = _collect_groups(pages)

    raw = [
        candidate
        for technique in TECHNIQUES
        for candidate in groups[technique]
    ]

    verified, rejected = verify_candidates(
        [groups[technique] for technique in TECHNIQUES],
        pages=pages,
    )

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
    print("완료 페이지          :", crawl.get("page_count", len(pages)))
    print("frame 수            :", crawl.get("frame_count", 0))
    print("raw 관측 합          :", len(raw))
    print("dedup 후보 합        :", len(merged))
    print("최종 유지 후보       :", len(verified))
    print("검증 제외 후보       :", len(rejected))
    print("경과 시간            :", f"{elapsed:.3f}초")

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
                "multi=" + str(candidate.get("multi_technique_count")),
                "independent=" + str(candidate.get("independent_technique_count")),
            )

    return {
        "pages": crawl.get("page_count", len(pages)),
        "raw": len(raw),
        "unique": len(merged),
        "verified": len(verified),
        "elapsed": elapsed,
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
