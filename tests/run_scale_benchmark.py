import argparse
import asyncio
import html
import json
import tempfile
import threading
import time
import unicodedata
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler_parallel import crawl_site
from detectors.homoglyph import detect_homoglyph_candidates
from detectors.jamo import detect_jamo_candidates
from detectors.offscreen import detect_offscreen_candidates
from detectors.transparent import detect_transparent_candidates
from verifier.contextual import verify_candidates


TECHNIQUES = ("TRANSPARENT", "OFFSCREEN", "JAMO", "HOMOGLYPH")
ZERO_WIDTH = "\u200b"
CYRILLIC_O = "\u041e"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


def _normalize_text(text):
    value = unicodedata.normalize("NFKC", text or "").lower()
    return " ".join(value.split())


def _normalized_route(url):
    parsed = urlsplit(url)
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return parsed.path, query


def _record_key(record):
    return (
        record["path"],
        record.get("query", ""),
        record["technique"],
        _normalize_text(record["evidence_text"]),
    )


def _candidate_key(candidate):
    path, query = _normalized_route(candidate.get("url", ""))
    return (
        path,
        query,
        candidate.get("technique", ""),
        # Ground truth는 실제 DOM에 심은 원문 evidence를 기준으로 비교한다.
        # normalized_text는 detector 내부 의미 정규화용이라 HOMOGLYPH의
        # 키릴/그리스 confusable을 ASCII로 바꿔 false miss/FP를 만들 수 있다.
        _normalize_text(candidate.get("evidence_text") or ""),
    )


def _page_url(index):
    path = f"/page-{index:04d}.html"

    if index % 10 == 0:
        return f"{path}?mode=full&n={index:04d}"

    return path


def _positive_case(index):
    technique = TECHNIQUES[((index // 8) - 1) % len(TECHNIQUES)]
    variant = (index // 8) % 3
    marker = f"SCALE-{index:04d}"
    element_id = f"case-{index:04d}"
    script = ""
    style = ""
    class_name = ""

    if technique == "TRANSPARENT":
        text = f"{marker}{ZERO_WIDTH}-T"

        if variant == 0:
            style = "opacity:0"
        elif variant == 1:
            class_name = "mobile-transparent"
        else:
            slot_id = "slot-" + element_id
            markup = f'<div id="{slot_id}"></div>'
            script = (
                "setTimeout(()=>{"
                "const e=document.createElement('span');"
                f"e.id={json.dumps(element_id)};"
                "e.style.opacity='0';"
                f"e.textContent={json.dumps(text)};"
                f"document.getElementById({json.dumps(slot_id)}).appendChild(e);"
                "},180);"
            )
            return technique, text, markup, script

    elif technique == "OFFSCREEN":
        text = f"{marker}{ZERO_WIDTH}-O"

        if variant == 0:
            style = "position:absolute;left:-9999px;top:10px"
        elif variant == 1:
            class_name = "mobile-offscreen"
        else:
            slot_id = "slot-" + element_id
            markup = f'<div id="{slot_id}"></div>'
            script = (
                "setTimeout(()=>{"
                "const e=document.createElement('span');"
                f"e.id={json.dumps(element_id)};"
                "e.style.position='absolute';"
                "e.style.left='-9999px';"
                "e.style.top='10px';"
                f"e.textContent={json.dumps(text)};"
                f"document.getElementById({json.dumps(slot_id)}).appendChild(e);"
                "},180);"
            )
            return technique, text, markup, script

    elif technique == "JAMO":
        text = f"ㅌㅔㅅㅡㅌㅡ {marker}-J"

        if variant == 2:
            slot_id = "slot-" + element_id
            markup = f'<div id="{slot_id}"></div>'
            script = (
                "setTimeout(()=>{"
                "const e=document.createElement('p');"
                f"e.id={json.dumps(element_id)};"
                f"e.textContent={json.dumps(text)};"
                f"document.getElementById({json.dumps(slot_id)}).appendChild(e);"
                "},180);"
            )
            return technique, text, markup, script

    else:
        mixed = "SC" + CYRILLIC_O + "PE"
        text = f"{mixed}-{marker}-H"

    attributes = []
    if style:
        attributes.append(f'style="{style}"')
    if class_name:
        attributes.append(f'class="{class_name}"')

    attr_blob = (" " + " ".join(attributes)) if attributes else ""
    markup = (
        f'<span id="{element_id}"{attr_blob}>'
        f'{html.escape(text)}</span>'
    )
    return technique, text, markup, script

def _control_markup(index):
    return (
        f'<div id="site-menu-{index:04d}" style="display:none">'
        "보조 메뉴"
        "</div>"
        f'<a id="skip-{index:04d}" href="#content" '
        'style="position:absolute;left:-9999px;top:0">'
        "본문 바로가기"
        "</a>"
    )


def _heavy_markup(index, rows):
    if index % 20 != 0:
        return ""

    cells = []
    for row in range(rows):
        cells.append(
            "<div class=\"scale-row\">"
            f"<span>행 {row:04d}</span>"
            f"<span>값 {index * 1000 + row}</span>"
            "</div>"
        )
    return '<section class="large-grid">' + "".join(cells) + "</section>"


def _frame_markup(index):
    if index % 15 != 0:
        return ""
    return (
        f'<iframe src="frame-{index:04d}.html" '
        f'title="보조 프레임 {index}"></iframe>'
    )


def build_site(root, page_count, heavy_rows):
    positives = []
    controls = []
    page_urls = [_page_url(index) for index in range(1, page_count + 1)]
    sitemap_only = {
        index
        for index in range(1, page_count + 1)
        if index % 11 == 0
    }
    navigable = [
        index
        for index in range(1, page_count + 1)
        if index not in sitemap_only
    ]
    next_by_index = {}

    for offset, index in enumerate(navigable):
        if offset + 1 < len(navigable):
            next_by_index[index] = navigable[offset + 1]

    for index in range(1, page_count + 1):
        technique = None
        positive_text = None
        positive_markup = ""
        script = ""

        if index % 8 == 0:
            (
                technique,
                positive_text,
                positive_markup,
                script,
            ) = _positive_case(index)
            path, query = _normalized_route(_page_url(index))
            positives.append(
                {
                    "path": path,
                    "query": query,
                    "technique": technique,
                    "evidence_text": positive_text,
                    "page_index": index,
                }
            )

        control = _control_markup(index)
        path, query = _normalized_route(_page_url(index))
        controls.extend(
            [
                {
                    "path": path,
                    "query": query,
                    "technique": "OFFSCREEN",
                    "evidence_text": "보조 메뉴",
                },
                {
                    "path": path,
                    "query": query,
                    "technique": "OFFSCREEN",
                    "evidence_text": "본문 바로가기",
                },
            ]
        )

        nav_links = ['<a href="/index.html">홈</a>']
        next_index = next_by_index.get(index)
        if next_index is not None:
            nav_links.append(
                f'<a href="{html.escape(_page_url(next_index))}">다음 문서</a>'
            )

        document = f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ARGUS Scale Page {index}</title>
<style>
body {{ font-family: Arial, sans-serif; }}
main {{ max-width: 1080px; margin: auto; padding: 20px; position: relative; }}
.mobile-transparent {{ color: inherit; }}
.mobile-offscreen {{ position: static; }}
.scale-row {{ display: flex; gap: 16px; }}
@media (max-width: 500px) {{
  .mobile-transparent {{ color: transparent; }}
  .mobile-offscreen {{ position: absolute; left: -9999px; top: 40px; }}
}}
</style>
</head>
<body>
<main id="content">
<h1>합성 문서 {index}</h1>
<p>ARGUS 대규모 크롤링 회귀 테스트용 중립 문서입니다.</p>
<div class="controls">{control}</div>
<div class="case">{positive_markup}</div>
{_heavy_markup(index, heavy_rows)}
{_frame_markup(index)}
<nav>{' '.join(nav_links)}</nav>
</main>
<script>{script}</script>
</body>
</html>'''

        (root / f"page-{index:04d}.html").write_text(
            document,
            encoding="utf-8",
        )

        if index % 15 == 0:
            frame_positive = ""
            if index % 30 == 0:
                frame_positive = (
                    f'<span style="position:absolute;left:-9999px;top:8px">'
                    f'FRAME-{index:04d}{ZERO_WIDTH}-O</span>'
                )
                positives.append(
                    {
                        "path": path,
                        "query": query,
                        "technique": "OFFSCREEN",
                        "evidence_text": f"FRAME-{index:04d}{ZERO_WIDTH}-O",
                        "page_index": index,
                    }
                )

            frame_doc = f'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><title>Frame {index}</title></head>
<body><p>프레임 안내 {index}</p>{frame_positive}</body></html>'''
            (root / f"frame-{index:04d}.html").write_text(
                frame_doc,
                encoding="utf-8",
            )

    first_link = _page_url(navigable[0]) if navigable else "/"
    index_doc = f'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><title>ARGUS Scale</title></head>
<body><h1>ARGUS Deterministic Scale Benchmark</h1>
<p>총 {page_count}개 합성 문서를 탐색합니다.</p>
<a href="{html.escape(first_link)}">탐색 시작</a>
</body></html>'''
    (root / "index.html").write_text(index_doc, encoding="utf-8")

    return {
        "page_urls": page_urls,
        "positives": positives,
        "controls": controls,
        "sitemap_only_count": len(sitemap_only),
        "expected_pages": page_count + 1,
    }


def start_server(root, page_urls):
    handler = partial(QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"

    sitemap_entries = "".join(
        f"<url><loc>{origin}{html.escape(url)}</loc></url>"
        for url in page_urls
    )
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + sitemap_entries
        + "</urlset>"
    )
    (root / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (root / "robots.txt").write_text(
        f"Sitemap: {origin}/sitemap.xml\n",
        encoding="utf-8",
    )

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, origin


def _pct(value):
    return f"{value * 100:.1f}%"


async def run(page_count, workers, discovery_workers, max_seconds, heavy_rows):
    with tempfile.TemporaryDirectory(prefix="argus_scale_") as temp:
        root = Path(temp)
        truth = build_site(root, page_count, heavy_rows)
        server, thread, origin = start_server(root, truth["page_urls"])

        try:
            entry = origin + "/index.html"
            print("===================================")
            print("      ARGUS DETERMINISTIC SCALE")
            print("===================================")
            print("content pages       :", page_count)
            print("expected crawl pages:", truth["expected_pages"])
            print("sitemap-only pages  :", truth["sitemap_only_count"])
            print("positives           :", len(truth["positives"]))
            print("controls            :", len(truth["controls"]))
            print("browser workers     :", workers)
            print("discovery workers   :", discovery_workers)
            print("heavy rows          :", heavy_rows)
            print()

            started = time.perf_counter()
            crawl = await crawl_site(
                entry,
                max_pages=truth["expected_pages"] + 4,
                max_seconds=max_seconds,
                worker_count=workers,
                discovery_worker_count=discovery_workers,
            )
            crawl_elapsed = time.perf_counter() - started

            groups = {technique: [] for technique in TECHNIQUES}
            for page in crawl.get("pages", []):
                groups["TRANSPARENT"].extend(
                    detect_transparent_candidates(page)
                )
                groups["OFFSCREEN"].extend(
                    detect_offscreen_candidates(page)
                )
                groups["JAMO"].extend(
                    detect_jamo_candidates(page)
                )
                groups["HOMOGLYPH"].extend(
                    detect_homoglyph_candidates(page)
                )

            raw = [
                candidate
                for technique in TECHNIQUES
                for candidate in groups[technique]
            ]

            verifier_started = time.perf_counter()
            verified, rejected = verify_candidates(
                [groups[technique] for technique in TECHNIQUES],
                pages=crawl.get("pages", []),
            )
            verifier_elapsed = time.perf_counter() - verifier_started

            expected = {
                _record_key(record): record
                for record in truth["positives"]
            }
            controls = {
                _record_key(record): record
                for record in truth["controls"]
            }
            detector_keys = {
                _candidate_key(candidate)
                for candidate in raw
            }
            verified_keys = {
                _candidate_key(candidate)
                for candidate in verified
            }

            detector_hits = set(expected) & detector_keys
            verifier_hits = set(expected) & verified_keys
            control_leaks = set(controls) & verified_keys
            unexpected = {
                key
                for key in verified_keys
                if key not in expected
                and key not in controls
            }

            detector_recall = (
                len(detector_hits) / len(expected)
                if expected else 1.0
            )
            required_recall = (
                len(verifier_hits) / len(expected)
                if expected else 1.0
            )
            false_positive_count = len(unexpected) + len(control_leaks)
            precision = (
                len(verifier_hits)
                / max(1, len(verifier_hits) + false_positive_count)
            )
            page_total = crawl.get("page_count", 0)
            pages_per_second = page_total / max(crawl_elapsed, 0.001)

            print("==============================")
            print("          결과 요약")
            print("==============================")
            print(
                "완료 페이지        :",
                page_total,
                f"/ {truth['expected_pages']}",
            )
            print("frame 수           :", crawl.get("frame_count", 0))
            print("raw 후보 관측      :", len(raw))
            print("dedup 검증 후보    :", len(verified) + len(rejected))
            print("최종 유지 후보     :", len(verified))
            print("크롤링 시간        :", f"{crawl_elapsed:.3f}초")
            print("Verifier 시간      :", f"{verifier_elapsed:.3f}초")
            print("처리량             :", f"{pages_per_second:.2f} pages/s")
            print(
                "크롤러 진단        :",
                f"known={crawl.get('known_page_count', 0)}",
                f"attempted={crawl.get('attempted_count', 0)}",
                f"pending={crawl.get('pending_count', 0)}",
                f"errors={len(crawl.get('errors', []))}",
                f"retries={crawl.get('browser_retry_count', 0)}",
                f"timeout_retries={crawl.get('browser_timeout_retry_count', 0)}",
                f"partial={crawl.get('browser_partial_recovery_count', 0)}",
                f"forced_cleanup={crawl.get('forced_cleanup', False)}",
                f"overrun={crawl.get('watchdog_overrun_seconds', 0.0):.3f}s",
                f"limit={crawl.get('limit_reached', False)}",
            )
            print()
            print(
                "Detector recall     :",
                _pct(detector_recall),
                f"({len(detector_hits)}/{len(expected)})",
            )
            print(
                "Required recall     :",
                _pct(required_recall),
                f"({len(verifier_hits)}/{len(expected)})",
            )
            print(
                "Verifier precision  :",
                _pct(precision),
                f"({len(verifier_hits)}/{len(verifier_hits) + false_positive_count})",
            )
            print(
                "Control leakage     :",
                len(control_leaks),
                "/",
                len(controls),
            )
            print("Unexpected FP       :", len(unexpected))

            if crawl.get("errors"):
                print("\n[크롤러 오류 상위 10건]")
                for error in crawl["errors"][:10]:
                    print(
                        " -",
                        error.get("url", ""),
                        "|",
                        str(error.get("error", ""))[:180],
                    )

            missed_detector = [
                expected[key]
                for key in expected
                if key not in detector_keys
            ]
            missed_verifier = [
                expected[key]
                for key in expected
                if key in detector_keys and key not in verified_keys
            ]

            if missed_detector:
                print("\n[Detector 누락 상위 20건]")
                for record in missed_detector[:20]:
                    print(
                        " -",
                        record["page_index"],
                        record["technique"],
                        record["path"],
                        "|",
                        record["evidence_text"],
                    )

            if missed_verifier:
                print("\n[Verifier 제외 정답 상위 20건]")
                for record in missed_verifier[:20]:
                    print(
                        " -",
                        record["page_index"],
                        record["technique"],
                        record["path"],
                        "|",
                        record["evidence_text"],
                    )

            return {
                "page_count": page_total,
                "expected_pages": truth["expected_pages"],
                "errors": len(crawl.get("errors", [])),
                "limit_reached": crawl.get("limit_reached", False),
                "detector_recall": detector_recall,
                "required_recall": required_recall,
                "precision": precision,
                "control_leakage": len(control_leaks),
                "unexpected_fp": len(unexpected),
                "crawl_elapsed": crawl_elapsed,
                "verifier_elapsed": verifier_elapsed,
                "pages_per_second": pages_per_second,
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(
        description="ARGUS deterministic 100/250/500/1000-page scale benchmark"
    )
    parser.add_argument("--pages", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--discovery-workers", type=int, default=8)
    parser.add_argument("--max-seconds", type=float, default=600.0)
    parser.add_argument(
        "--heavy-rows",
        type=int,
        default=300,
        help="20번째 페이지마다 추가할 대형 DOM 행 수",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="ARGUS 내부 회귀 기준 미달 시 exit code 1",
    )
    args = parser.parse_args()

    if args.pages < 20:
        parser.error("--pages는 20 이상이어야 합니다")
    if args.workers < 1:
        parser.error("--workers는 1 이상이어야 합니다")
    if args.discovery_workers < 0:
        parser.error("--discovery-workers는 0 이상이어야 합니다")
    if args.heavy_rows < 0:
        parser.error("--heavy-rows는 0 이상이어야 합니다")

    result = asyncio.run(
        run(
            args.pages,
            args.workers,
            args.discovery_workers,
            args.max_seconds,
            args.heavy_rows,
        )
    )

    # 공모전 공식 점수가 아니라 ARGUS 자체 대규모 회귀 기준.
    if args.strict and (
        result["page_count"] != result["expected_pages"]
        or result["errors"] > 0
        or result["limit_reached"]
        or result["detector_recall"] < 1.0
        or result["required_recall"] < 1.0
        or result["precision"] < 0.98
        or result["control_leakage"] > 0
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
