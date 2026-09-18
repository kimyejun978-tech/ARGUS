import argparse
import asyncio
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

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


def _collect_crawler_performance(pages):
    stage_totals = defaultdict(float)
    pass_stats = defaultdict(
        lambda: {
            "count": 0,
            "total": 0.0,
            "dom_scan": 0.0,
            "link_collect": 0.0,
            "observations": 0,
            "frames": 0,
        }
    )
    path_stats = defaultdict(
        lambda: {
            "count": 0,
            "total": 0.0,
            "max": 0.0,
            "navigation": 0.0,
            "scan": 0.0,
            "frames": 0,
            "observations": 0,
        }
    )
    slow_pages = []

    stage_keys = (
        "page_total",
        "navigation",
        "scan_total",
        "wait_dom_quiet",
        "auto_scroll",
        "pass_capture",
        "dom_scan",
        "link_collect",
        "viewport_setup",
        "title",
    )

    for page in pages:
        timings = page.get("timings") or {}

        for key in stage_keys:
            stage_totals[key] += float(timings.get(key, 0.0) or 0.0)

        for pass_name, values in (timings.get("passes") or {}).items():
            stat = pass_stats[pass_name]
            stat["count"] += 1
            stat["total"] += float(values.get("total", 0.0) or 0.0)
            stat["dom_scan"] += float(
                values.get("dom_scan", 0.0) or 0.0
            )
            stat["link_collect"] += float(
                values.get("link_collect", 0.0) or 0.0
            )
            stat["observations"] += int(
                values.get("observations", 0) or 0
            )
            stat["frames"] += int(values.get("frames", 0) or 0)

        page_total = float(timings.get("page_total", 0.0) or 0.0)
        navigation = float(timings.get("navigation", 0.0) or 0.0)
        scan_total = float(timings.get("scan_total", 0.0) or 0.0)
        page_url = page.get("url", "")
        frame_count = int(page.get("frame_count", 0) or 0)
        observations = int(page.get("observation_count", 0) or 0)

        if page_total > 0:
            slow_pages.append(
                {
                    "url": page_url,
                    "total": page_total,
                    "navigation": navigation,
                    "scan": scan_total,
                    "frames": frame_count,
                    "observations": observations,
                }
            )

        path = urlsplit(page_url).path or "/"
        path_stat = path_stats[path]
        path_stat["count"] += 1
        path_stat["total"] += page_total
        path_stat["max"] = max(path_stat["max"], page_total)
        path_stat["navigation"] += navigation
        path_stat["scan"] += scan_total
        path_stat["frames"] += frame_count
        path_stat["observations"] += observations

    slow_pages.sort(key=lambda item: item["total"], reverse=True)

    return stage_totals, pass_stats, path_stats, slow_pages


def _print_crawler_performance(pages):
    stage_totals, pass_stats, path_stats, slow_pages = (
        _collect_crawler_performance(pages)
    )

    if not slow_pages:
        return

    print("\n[크롤러 단계별 누적 worker 시간]")
    print("  ※ 병렬 worker의 페이지별 시간을 합산한 값이라 실제 벽시계 시간보다 큼")
    labels = (
        ("page_total", "페이지 전체"),
        ("navigation", "navigation"),
        ("scan_total", "5-pass scan"),
        ("wait_dom_quiet", "DOM 안정 대기"),
        ("auto_scroll", "자동 스크롤"),
        ("pass_capture", "pass capture"),
        ("dom_scan", "DOM evaluate"),
        ("link_collect", "링크 수집"),
        ("viewport_setup", "viewport 전환"),
        ("title", "title 조회"),
    )
    for key, label in labels:
        print(f"  {label:<16} {stage_totals[key]:>10.3f}초")

    print("\n[scan pass별 capture 성능]")
    for pass_name in (
        "desktop-initial",
        "desktop-settled",
        "desktop-scrolled",
        "mobile-settled",
        "mobile-scrolled",
    ):
        stat = pass_stats.get(pass_name)
        if not stat or not stat["count"]:
            continue
        count = stat["count"]
        print(
            f"  {pass_name:<18} "
            f"avg={stat['total']/count:>6.3f}s "
            f"dom={stat['dom_scan']/count:>6.3f}s "
            f"links={stat['link_collect']/count:>6.3f}s "
            f"obs={stat['observations']/count:>7.1f} "
            f"frames={stat['frames']/count:>5.1f}"
        )

    print("\n[느린 페이지 상위 15건]")
    for item in slow_pages[:15]:
        print(
            " -",
            f"total={item['total']:.3f}s",
            f"nav={item['navigation']:.3f}s",
            f"scan={item['scan']:.3f}s",
            f"frames={item['frames']}",
            f"obs={item['observations']}",
            "|",
            item["url"][:220],
        )

    ranked_paths = sorted(
        path_stats.items(),
        key=lambda item: item[1]["total"],
        reverse=True,
    )
    print("\n[경로별 누적 처리시간 상위 12개]")
    for path, stat in ranked_paths[:12]:
        count = stat["count"]
        avg = stat["total"] / count if count else 0.0
        avg_frames = stat["frames"] / count if count else 0.0
        avg_obs = stat["observations"] / count if count else 0.0
        print(
            f"  count={count:>4} "
            f"sum={stat['total']:>8.2f}s "
            f"avg={avg:>6.3f}s "
            f"max={stat['max']:>6.3f}s "
            f"frames={avg_frames:>5.1f} "
            f"obs={avg_obs:>8.1f} "
            f"| {path}"
        )


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
        f"downloads={crawl.get('browser_download_skip_count', 0)}",
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

    _print_crawler_performance(pages)

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
