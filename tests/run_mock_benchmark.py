import argparse
import asyncio
import json
import sys
import threading
from collections import Counter, defaultdict
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "tests" / "mock_site"
BENCHMARK_ROOT = SITE_ROOT / "benchmark"
GROUND_TRUTH_PATH = BENCHMARK_ROOT / "ground_truth.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler_parallel import crawl_site
from detectors.homoglyph import detect_homoglyph_candidates
from detectors.jamo import detect_jamo_candidates
from detectors.offscreen import detect_offscreen_candidates
from detectors.transparent import detect_transparent_candidates
from verifier.contextual import verify_candidates


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


def _record_key(record):
    return (
        record["page"].lstrip("/"),
        record["technique"],
        record["evidence_text"],
    )


def _candidate_key(candidate):
    path = urlsplit(candidate.get("url", "")).path.lstrip("/")
    return (
        path,
        candidate.get("technique", ""),
        candidate.get("evidence_text", ""),
    )


def _pct(value):
    return f"{value * 100:.1f}%"


def _safe_div(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def _format_case(record):
    return (
        f"{record['id']} | {record['technique']} | "
        f"{record['page']} | {record['evidence_text']}"
    )


def _load_ground_truth():
    with GROUND_TRUTH_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def _start_server():
    handler = partial(QuietHandler, directory=str(SITE_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


async def _run_benchmark(max_seconds):
    truth = _load_ground_truth()
    server, thread = _start_server()
    port = server.server_address[1]
    entry_url = f"http://127.0.0.1:{port}/{truth['entry']}"

    try:
        print("==============================")
        print("      ARGUS MOCK BENCHMARK")
        print("==============================")
        print("entry :", entry_url)
        print("정답 positive :", len(truth["positives"]))
        print("정상 control   :", len(truth["benign_controls"]))
        print()

        crawl_result = await crawl_site(
            entry_url,
            max_pages=50,
            max_seconds=max_seconds,
            worker_count=4,
            discovery_worker_count=4,
        )

        transparent = []
        offscreen = []
        jamo = []
        homoglyph = []

        for page_result in crawl_result["pages"]:
            transparent.extend(detect_transparent_candidates(page_result))
            offscreen.extend(detect_offscreen_candidates(page_result))
            jamo.extend(detect_jamo_candidates(page_result))
            homoglyph.extend(detect_homoglyph_candidates(page_result))

        groups = [transparent, offscreen, jamo, homoglyph]
        raw_candidates = [candidate for group in groups for candidate in group]
        verified, rejected = verify_candidates(
            groups,
            pages=crawl_result["pages"],
        )

        positive_by_key = {
            _record_key(record): record
            for record in truth["positives"]
        }
        control_by_key = {
            _record_key(record): record
            for record in truth["benign_controls"]
        }

        detector_keys = {_candidate_key(candidate) for candidate in raw_candidates}
        verified_by_key = {
            _candidate_key(candidate): candidate
            for candidate in verified
        }

        detector_hits = {
            key for key in positive_by_key if key in detector_keys
        }
        verifier_hits = {
            key for key in positive_by_key if key in verified_by_key
        }
        missing_detector = [
            positive_by_key[key]
            for key in positive_by_key
            if key not in detector_keys
        ]
        missing_verifier = [
            positive_by_key[key]
            for key in positive_by_key
            if key not in verified_by_key
        ]

        unexpected_verified = [
            candidate
            for key, candidate in verified_by_key.items()
            if key not in positive_by_key
        ]
        verified_controls = [
            control_by_key[key]
            for key in control_by_key
            if key in verified_by_key
        ]

        tp = len(verifier_hits)
        fp = len(unexpected_verified)
        fn = len(positive_by_key) - tp
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        detector_recall = _safe_div(len(detector_hits), len(positive_by_key))

        status_counts = Counter(
            candidate.get("verification_status", "UNKNOWN")
            for candidate in verified
            if _candidate_key(candidate) in positive_by_key
        )

        per_technique = defaultdict(lambda: {"expected": 0, "detected": 0, "verified": 0})
        for key, record in positive_by_key.items():
            technique = record["technique"]
            per_technique[technique]["expected"] += 1
            if key in detector_keys:
                per_technique[technique]["detected"] += 1
            if key in verified_by_key:
                per_technique[technique]["verified"] += 1

        print("==============================")
        print("          결과 요약")
        print("==============================")
        print("분석 완료 페이지 :", crawl_result.get("page_count", 0))
        print("분석 frame 수     :", crawl_result.get("frame_count", 0))
        print("구조 후보 관측합  :", len(raw_candidates))
        print("검증 유지 후보    :", len(verified))
        print("검증 제외 후보    :", len(rejected))
        print()
        print("Detector recall   :", _pct(detector_recall), f"({len(detector_hits)}/{len(positive_by_key)})")
        print("Verifier precision:", _pct(precision), f"({tp}/{tp + fp})" if tp + fp else "(0/0)")
        print("Verifier recall   :", _pct(recall), f"({tp}/{len(positive_by_key)})")
        print("Verifier F1       :", _pct(f1))
        print("CONFIRMED         :", status_counts.get("CONFIRMED", 0))
        print("SUSPICIOUS        :", status_counts.get("SUSPICIOUS", 0))
        print("Unexpected FP     :", fp)
        print("Control leakage   :", len(verified_controls), "/", len(control_by_key))
        print()

        print("기법별 정답 / detector / verifier")
        for technique in ("TRANSPARENT", "OFFSCREEN", "JAMO", "HOMOGLYPH"):
            row = per_technique[technique]
            print(
                f"  {technique:<11} "
                f"{row['expected']:>2} / {row['detected']:>2} / {row['verified']:>2}"
            )

        if missing_detector:
            print("\n[Detector 누락]")
            for record in missing_detector:
                print(" -", _format_case(record))

        if missing_verifier:
            print("\n[Verifier 누락]")
            for record in missing_verifier:
                print(" -", _format_case(record))

        if unexpected_verified:
            print("\n[예상하지 않은 최종 유지 후보]")
            for candidate in unexpected_verified:
                print(
                    " -",
                    candidate.get("verification_status"),
                    candidate.get("technique"),
                    urlsplit(candidate.get("url", "")).path,
                    "|",
                    candidate.get("evidence_text", ""),
                )

        return {
            "detector_recall": detector_recall,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "false_positives": fp,
            "missing_detector": len(missing_detector),
            "missing_verifier": len(missing_verifier),
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(
        description="ARGUS 로컬 모의 사이트 end-to-end benchmark"
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=120.0,
        help="benchmark crawler watchdog (default: 120)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="precision/recall이 100%%가 아니면 exit code 1",
    )
    args = parser.parse_args()

    result = asyncio.run(_run_benchmark(args.max_seconds))

    if args.strict and (
        result["precision"] < 1.0
        or result["recall"] < 1.0
        or result["detector_recall"] < 1.0
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
