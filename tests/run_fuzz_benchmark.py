import argparse
import asyncio
import html
import random
import string
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit


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
CYRILLIC_CONFUSABLES = {
    "A": "А",
    "B": "В",
    "C": "С",
    "E": "Е",
    "H": "Н",
    "K": "К",
    "M": "М",
    "O": "О",
    "P": "Р",
    "T": "Т",
    "X": "Х",
}
GREEK_CONFUSABLES = {
    "A": "Α",
    "B": "Β",
    "E": "Ε",
    "H": "Η",
    "I": "Ι",
    "K": "Κ",
    "M": "Μ",
    "N": "Ν",
    "O": "Ο",
    "P": "Ρ",
    "T": "Τ",
    "X": "Χ",
}

CHO = [
    "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]
JUNG = [
    "ㅏ", "ㅐ", "ㅑ", "ㅒ", "ㅓ", "ㅔ", "ㅕ", "ㅖ", "ㅗ", "ㅘ", "ㅙ",
    "ㅚ", "ㅛ", "ㅜ", "ㅝ", "ㅞ", "ㅟ", "ㅠ", "ㅡ", "ㅢ", "ㅣ",
]
JONG = [
    "", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ",
    "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ",
    "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


def _pct(value):
    return f"{value * 100:.1f}%"


def _safe_div(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def _normalized_page(value):
    parts = urlsplit(value)
    path = parts.path.lstrip("/")
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return f"{path}?{query}" if query else path


def _record_key(record):
    return (
        _normalized_page(record["page"]),
        record["technique"],
        record["evidence_text"],
    )


def _candidate_key(candidate):
    return (
        _normalized_page(candidate.get("url", "")),
        candidate.get("technique", ""),
        candidate.get("evidence_text", ""),
    )


def _token(rng, length=5):
    alphabet = "QWRTYPSDFGHJKLZCVBNM"
    return "".join(rng.choice(alphabet) for _ in range(length))


def _neutral_text(rng, index, zero_width=False):
    first = _token(rng, 4 + index % 2)
    second = _token(rng, 4 + (index + 1) % 2)
    separator = "\u200b " if zero_width else " "
    return f"{first}{separator}{second} {100 + index}"


def _decompose_compat(text):
    out = []
    for char in text:
        code = ord(char)
        if not 0xAC00 <= code <= 0xD7A3:
            out.append(char)
            continue
        offset = code - 0xAC00
        choseong = offset // 588
        jungseong = (offset % 588) // 28
        jongseong = offset % 28
        out.append(CHO[choseong])
        out.append(JUNG[jungseong])
        if jongseong:
            out.append(JONG[jongseong])
    return "".join(out)


def _decompose_modern(text):
    out = []
    for char in text:
        code = ord(char)
        if not 0xAC00 <= code <= 0xD7A3:
            out.append(char)
            continue
        offset = code - 0xAC00
        choseong = offset // 588
        jungseong = (offset % 588) // 28
        jongseong = offset % 28
        out.append(chr(0x1100 + choseong))
        out.append(chr(0x1161 + jungseong))
        if jongseong:
            out.append(chr(0x11A7 + jongseong))
    return "".join(out)


def _pseudo_hangul(index):
    syllables = ["카", "파", "노", "루", "베", "도", "세", "미", "타", "라", "코", "주"]
    a = syllables[index % len(syllables)]
    b = syllables[(index * 3 + 2) % len(syllables)]
    c = syllables[(index * 5 + 5) % len(syllables)]
    return a + b + c


def _fullwidth(text):
    result = []
    for char in text:
        code = ord(char)
        if 0x21 <= code <= 0x7E:
            result.append(chr(code + 0xFEE0))
        else:
            result.append(char)
    return "".join(result)


def _mixed_confusable(text, mapping):
    chars = list(text)
    for index, char in enumerate(chars):
        upper = char.upper()
        if upper in mapping:
            replacement = mapping[upper]
            chars[index] = replacement.lower() if char.islower() else replacement
            return "".join(chars)
    return text


def _digit_confusable(text):
    replacements = (("O", "0"), ("I", "1"), ("E", "3"), ("A", "4"), ("S", "5"), ("T", "7"), ("B", "8"))
    for source, target in replacements:
        position = text.find(source, 1)
        if 0 < position < len(text) - 1:
            return text[:position] + target + text[position + 1 :]
    return text[:2] + "0" + text[3:] if len(text) >= 4 else "A0A"


def _make_case(rng, technique, index):
    family_index = index % 6
    case_id = f"F-{technique[:2]}-{index + 1:03d}"
    unique_id = f"case-{technique.lower()}-{index + 1:03d}"
    shared_id = f"shared-{technique.lower()}"

    if technique == "TRANSPARENT":
        families = (
            "opacity-zero-zws",
            "color-transparent-plain",
            "same-color-plain",
            "mobile-only-zws",
            "delayed-plain",
            "repeated-location-zws",
        )
        family = families[family_index]
        text = _neutral_text(rng, index, zero_width=family in {"opacity-zero-zws", "mobile-only-zws", "repeated-location-zws"})
        element_id = shared_id if family == "repeated-location-zws" else unique_id
        if family == "opacity-zero-zws":
            html_text = f'<p id="{element_id}" style="opacity:0">{html.escape(text)}</p>'
            script = ""
        elif family == "color-transparent-plain":
            html_text = f'<p id="{element_id}" style="color:transparent">{html.escape(text)}</p>'
            script = ""
        elif family == "same-color-plain":
            html_text = f'<p id="{element_id}" style="color:#ffffff;background:#ffffff">{html.escape(text)}</p>'
            script = ""
        elif family == "mobile-only-zws":
            html_text = f'<p id="{element_id}" class="mobile-transparent">{html.escape(text)}</p>'
            script = ""
        elif family == "delayed-plain":
            html_text = f'<div id="slot-{unique_id}"></div>'
            payload = html.escape(text).replace("'", "&#39;")
            script = f"setTimeout(() => document.getElementById('slot-{unique_id}').insertAdjacentHTML('beforeend', '<p id=\"{unique_id}\" style=\"color:transparent\">{payload}</p>'), 180);"
        else:
            html_text = f'<p id="{element_id}" style="color:transparent">{html.escape(text)}</p>'
            script = ""

    elif technique == "OFFSCREEN":
        families = (
            "far-left-zws",
            "tiny-plain",
            "fixed-top-zws",
            "display-none-zws",
            "mobile-only-plain",
            "repeated-location-zws",
        )
        family = families[family_index]
        text = _neutral_text(rng, index + 1000, zero_width=family in {"far-left-zws", "fixed-top-zws", "display-none-zws", "repeated-location-zws"})
        element_id = shared_id if family == "repeated-location-zws" else unique_id
        if family == "far-left-zws":
            html_text = f'<p id="{element_id}" style="position:absolute;left:-9999px;top:320px">{html.escape(text)}</p>'
        elif family == "tiny-plain":
            html_text = f'<p id="{element_id}" style="font-size:1px">{html.escape(text)}</p>'
        elif family == "fixed-top-zws":
            html_text = f'<p id="{element_id}" style="position:fixed;top:-9999px;left:10px">{html.escape(text)}</p>'
        elif family == "display-none-zws":
            html_text = f'<p id="{element_id}" style="display:none">{html.escape(text)}</p>'
        elif family == "mobile-only-plain":
            html_text = f'<p id="{element_id}" class="mobile-offscreen">{html.escape(text)}</p>'
        else:
            html_text = f'<p id="{element_id}" style="position:absolute;left:-9999px;top:360px">{html.escape(text)}</p>'
        script = ""

    elif technique == "JAMO":
        families = (
            "compat-stable",
            "compat-mobile-only",
            "compat-delayed",
            "modern-stable",
            "compat-punctuation",
            "repeated-location",
        )
        family = families[family_index]
        base = _pseudo_hangul(index)
        if family == "modern-stable":
            text = _decompose_modern(base)
        else:
            text = _decompose_compat(base)
        if family == "compat-punctuation":
            text = text[:2] + " · " + text[2:]
        element_id = shared_id if family == "repeated-location" else unique_id
        if family == "compat-mobile-only":
            escaped = html.escape(text).replace("'", "&#39;")
            html_text = f'<div id="slot-{unique_id}"></div>'
            script = (
                f"function render_{index}(){{const s=document.getElementById('slot-{unique_id}');s.innerHTML='';"
                f"if(innerWidth<=500)s.insertAdjacentHTML('beforeend','<p id=\"{unique_id}\">{escaped}</p>');}}"
                f"render_{index}();addEventListener('resize',()=>setTimeout(render_{index},0));"
            )
        elif family == "compat-delayed":
            escaped = html.escape(text).replace("'", "&#39;")
            html_text = f'<div id="slot-{unique_id}"></div>'
            script = f"setTimeout(() => document.getElementById('slot-{unique_id}').insertAdjacentHTML('beforeend','<p id=\"{unique_id}\">{escaped}</p>'),180);"
        else:
            html_text = f'<p id="{element_id}">{html.escape(text)}</p>'
            script = ""

    else:
        families = (
            "cyrillic-mixed",
            "fullwidth-plain",
            "digit-internal",
            "greek-mixed",
            "mobile-only-mixed",
            "repeated-location-mixed",
        )
        family = families[family_index]
        base = _token(rng, 7)
        if family == "cyrillic-mixed":
            text = _mixed_confusable(base, CYRILLIC_CONFUSABLES) + " " + _token(rng, 5)
        elif family == "fullwidth-plain":
            text = _fullwidth(base + " " + _token(rng, 5))
        elif family == "digit-internal":
            text = _digit_confusable(base) + " " + _token(rng, 5)
        elif family == "greek-mixed":
            text = _mixed_confusable(base, GREEK_CONFUSABLES) + " " + _token(rng, 5)
        elif family == "mobile-only-mixed":
            text = _mixed_confusable(base, CYRILLIC_CONFUSABLES) + " " + _token(rng, 5)
        else:
            text = _mixed_confusable(base, CYRILLIC_CONFUSABLES) + " " + _token(rng, 5)
        element_id = shared_id if family == "repeated-location-mixed" else unique_id
        if family == "mobile-only-mixed":
            escaped = html.escape(text).replace("'", "&#39;")
            html_text = f'<div id="slot-{unique_id}"></div>'
            script = (
                f"function render_h_{index}(){{const s=document.getElementById('slot-{unique_id}');s.innerHTML='';"
                f"if(innerWidth<=500)s.insertAdjacentHTML('beforeend','<p id=\"{unique_id}\">{escaped}</p>');}}"
                f"render_h_{index}();addEventListener('resize',()=>setTimeout(render_h_{index},0));"
            )
        else:
            html_text = f'<p id="{element_id}">{html.escape(text)}</p>'
            script = ""

    return {
        "id": case_id,
        "technique": technique,
        "family": family,
        "evidence_text": text,
        "html": html_text,
        "script": script,
    }


def _control_html(page_index):
    controls = []
    controls.append({
        "id": f"C-SKIP-{page_index:03d}",
        "technique": "OFFSCREEN",
        "evidence_text": "본문 바로가기",
        "html": '<a id="site-skip-link" href="#content" style="position:absolute;left:-9999px;top:0">본문 바로가기</a>',
    })

    mode = page_index % 4
    if mode == 0:
        controls.append({
            "id": f"C-MENU-{page_index:03d}",
            "technique": "OFFSCREEN",
            "evidence_text": "모바일 메뉴",
            "html": '<div id="site-mobile-menu" style="display:none">모바일 메뉴</div>',
        })
    elif mode == 1:
        controls.append({
            "id": f"C-META-{page_index:03d}",
            "technique": "OFFSCREEN",
            "evidence_text": "문서 버전 정보",
            "html": '<span id="site-version-meta" style="font-size:1px">문서 버전 정보</span>',
        })
    elif mode == 2:
        controls.append({
            "id": f"C-FW-{page_index:03d}",
            "technique": "HOMOGLYPH",
            "evidence_text": "ＶＥＲＳＩＯＮ ２",
            "html": '<p id="site-fullwidth-version">ＶＥＲＳＩＯＮ ２</p>',
        })
    else:
        controls.append({
            "id": f"C-JAMO-{page_index:03d}",
            "technique": "JAMO",
            "evidence_text": "ㅁㅔㄴㅠ ㅇㅏㄴㄴㅐ",
            "html": '<p id="site-jamo-menu">ㅁㅔㄴㅠ ㅇㅏㄴㄴㅐ</p>',
        })
    return controls


def _build_site(root, seed, per_technique):
    rng = random.Random(seed)
    positives = []
    controls = []
    pages = []

    cases_by_technique = {
        technique: [_make_case(rng, technique, index) for index in range(per_technique)]
        for technique in TECHNIQUES
    }

    for page_index in range(per_technique):
        filename = f"post-{page_index + 1:03d}.html"
        page_cases = [cases_by_technique[technique][page_index] for technique in TECHNIQUES]
        page_controls = _control_html(page_index)
        controls.extend({**control, "page": filename} for control in page_controls)

        body_parts = []
        scripts = []
        for case in page_cases:
            body_parts.append(case["html"])
            if case["script"]:
                scripts.append(case["script"])
            positives.append({
                "id": case["id"],
                "page": filename,
                "technique": case["technique"],
                "family": case["family"],
                "evidence_text": case["evidence_text"],
            })

        body_parts.extend(control["html"] for control in page_controls)
        page_html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fuzz 문서 {page_index + 1}</title>
<style>
body{{font-family:Arial,sans-serif;background:#f6f7f9;color:#20242b;margin:0}}
header{{background:#17324d;color:white;padding:18px 28px}}
main{{max-width:920px;margin:auto;padding:28px;position:relative}}
article{{background:white;border:1px solid #d8dee6;padding:24px;min-height:520px}}
.mobile-transparent{{color:#20242b}}
.mobile-offscreen{{position:static}}
@media(max-width:500px){{
  .mobile-transparent{{color:transparent}}
  .mobile-offscreen{{position:absolute;left:-9999px;top:300px}}
}}
</style>
</head>
<body>
<header><strong>ARGUS 로컬 변이 테스트</strong></header>
<main>
<article id="content">
<h1>일반 안내 문서 {page_index + 1}</h1>
<p>이 페이지는 외부 연결이나 입력 기능이 없는 로컬 합성 테스트 문서입니다.</p>
<div id="cases">{''.join(body_parts)}</div>
</article>
<p><a href="board.html">목록으로</a></p>
</main>
<script>{''.join(scripts)}</script>
</body>
</html>'''
        (root / filename).write_text(page_html, encoding="utf-8")
        pages.append(filename)

    links = "".join(
        f'<li><a href="{name}">합성 문서 {index + 1}</a></li>'
        for index, name in enumerate(pages)
    )
    (root / "board.html").write_text(
        f'''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><title>Fuzz 게시판</title></head>
<body><h1>Fuzz 게시판</h1><ul>{links}</ul><a href="index.html">홈</a></body></html>''',
        encoding="utf-8",
    )
    (root / "index.html").write_text(
        '''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><title>ARGUS Fuzz</title></head>
<body><h1>ARGUS Mutation Fuzz Benchmark</h1><p>완전한 로컬 합성 사이트입니다.</p><a href="board.html">게시판</a></body></html>''',
        encoding="utf-8",
    )

    return {
        "entry": "index.html",
        "expected_min_pages": per_technique + 2,
        "positives": positives,
        "benign_controls": controls,
    }


def _start_server(site_root):
    handler = partial(QuietHandler, directory=str(site_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


async def _run(seed, per_technique, max_seconds):
    with tempfile.TemporaryDirectory(prefix="argus_fuzz_") as temp_dir:
        site_root = Path(temp_dir)
        truth = _build_site(site_root, seed, per_technique)
        server, thread = _start_server(site_root)
        port = server.server_address[1]
        entry_url = f"http://127.0.0.1:{port}/{truth['entry']}"

        try:
            print("===================================")
            print("      ARGUS MUTATION FUZZ TEST")
            print("===================================")
            print("seed               :", seed)
            print("entry              :", entry_url)
            print("positive           :", len(truth["positives"]))
            print("normal controls    :", len(truth["benign_controls"]))
            print("pages expected     :", truth["expected_min_pages"])
            print()

            started = time.perf_counter()
            crawl_result = await crawl_site(
                entry_url,
                max_pages=max(80, per_technique + 10),
                max_seconds=max_seconds,
                worker_count=4,
                discovery_worker_count=8,
            )
            elapsed = time.perf_counter() - started

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
            raw = [candidate for group in groups for candidate in group]
            verified, rejected = verify_candidates(groups, pages=crawl_result["pages"])

            positives = {_record_key(record): record for record in truth["positives"]}
            controls = {_record_key(record): record for record in truth["benign_controls"]}
            detector_keys = {_candidate_key(candidate) for candidate in raw}
            verified_by_key = {_candidate_key(candidate): candidate for candidate in verified}

            detector_hits = {key for key in positives if key in detector_keys}
            verifier_hits = {key for key in positives if key in verified_by_key}
            unexpected = [candidate for key, candidate in verified_by_key.items() if key not in positives]
            control_leaks = [controls[key] for key in controls if key in verified_by_key]

            tp = len(verifier_hits)
            fp = len(unexpected)
            precision = _safe_div(tp, tp + fp)
            detector_recall = _safe_div(len(detector_hits), len(positives))
            verifier_recall = _safe_div(tp, len(positives))
            f1 = _safe_div(2 * precision * verifier_recall, precision + verifier_recall)

            status_counts = Counter(
                verified_by_key[key].get("verification_status", "UNKNOWN")
                for key in verifier_hits
            )

            per_technique_stats = defaultdict(lambda: {"expected": 0, "detected": 0, "verified": 0})
            per_family_stats = defaultdict(lambda: {"expected": 0, "detected": 0, "verified": 0, "scores": []})
            for key, record in positives.items():
                technique_row = per_technique_stats[record["technique"]]
                family_key = f"{record['technique']}::{record['family']}"
                family_row = per_family_stats[family_key]
                technique_row["expected"] += 1
                family_row["expected"] += 1
                if key in detector_keys:
                    technique_row["detected"] += 1
                    family_row["detected"] += 1
                if key in verified_by_key:
                    technique_row["verified"] += 1
                    family_row["verified"] += 1
                    family_row["scores"].append(verified_by_key[key].get("open_set_score", 0.0))

            page_count = crawl_result.get("page_count", len(crawl_result.get("pages", [])))

            print("==============================")
            print("          결과 요약")
            print("==============================")
            print("분석 완료 페이지 :", page_count, f"(최소 기대 {truth['expected_min_pages']})")
            print("분석 frame 수    :", crawl_result.get("frame_count", 0))
            print("구조 후보 관측합 :", len(raw))
            print("검증 유지 후보   :", len(verified))
            print("검증 제외 후보   :", len(rejected))
            print("크롤링+검사 시간 :", f"{elapsed:.3f}초")
            print()
            print("Detector recall   :", _pct(detector_recall), f"({len(detector_hits)}/{len(positives)})")
            print("Verifier precision:", _pct(precision), f"({tp}/{tp + fp})" if tp + fp else "(0/0)")
            print("Verifier recall   :", _pct(verifier_recall), f"({tp}/{len(positives)})")
            print("Verifier F1       :", _pct(f1))
            print("CONFIRMED         :", status_counts.get("CONFIRMED", 0))
            print("SUSPICIOUS        :", status_counts.get("SUSPICIOUS", 0))
            print("Unexpected FP     :", fp)
            print("Control leakage   :", len(control_leaks), "/", len(controls))
            print()

            print("기법별 정답 / detector / verifier")
            for technique in TECHNIQUES:
                row = per_technique_stats[technique]
                print(f"  {technique:<11} {row['expected']:>3} / {row['detected']:>3} / {row['verified']:>3}")

            print("\n[변이 family별 결과]")
            for family_key in sorted(per_family_stats):
                row = per_family_stats[family_key]
                average = _safe_div(sum(row["scores"]), len(row["scores"])) if row["scores"] else 0.0
                print(
                    f"  {family_key:<42} "
                    f"{row['expected']:>2} / {row['detected']:>2} / {row['verified']:>2} "
                    f"open_avg={average:.3f}"
                )

            misses = [
                record for key, record in positives.items()
                if key not in verified_by_key
            ]
            if misses:
                print("\n[Verifier 누락 상위 20건]")
                for record in misses[:20]:
                    print(
                        " -",
                        record["id"],
                        record["technique"],
                        record["family"],
                        record["page"],
                        "|",
                        record["evidence_text"],
                    )

            weakest = []
            for key in verifier_hits:
                candidate = verified_by_key[key]
                weakest.append((candidate.get("open_set_score", 0.0), positives[key], candidate))
            weakest.sort(key=lambda item: item[0])
            if weakest:
                print("\n[유지된 정답 중 open-set 점수 하위 10건]")
                for score, record, candidate in weakest[:10]:
                    print(
                        " -",
                        record["id"],
                        candidate.get("verification_status"),
                        record["technique"],
                        record["family"],
                        f"semantic={candidate.get('semantic_score')}",
                        f"open={score}",
                        f"passes={len(candidate.get('scan_passes') or [])}",
                    )

            if unexpected:
                print("\n[예상하지 않은 최종 유지 후보 상위 20건]")
                for candidate in unexpected[:20]:
                    print(
                        " -",
                        candidate.get("verification_status"),
                        candidate.get("technique"),
                        _normalized_page(candidate.get("url", "")),
                        "|",
                        candidate.get("evidence_text", ""),
                    )

            return {
                "page_count": page_count,
                "min_pages": truth["expected_min_pages"],
                "detector_recall": detector_recall,
                "precision": precision,
                "recall": verifier_recall,
                "f1": f1,
                "control_leakage": len(control_leaks),
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description="ARGUS deterministic mutation fuzz benchmark")
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument("--per-technique", type=int, default=24, help="각 탐지 기법마다 생성할 positive 수")
    parser.add_argument("--max-seconds", type=float, default=240.0)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="내부 스트레스 기준 미달 시 exit code 1",
    )
    args = parser.parse_args()

    if args.per_technique < 6:
        parser.error("--per-technique은 최소 6이어야 합니다")

    result = asyncio.run(_run(args.seed, args.per_technique, args.max_seconds))

    # 공모전 공식 기준이 아니라 ARGUS 자체 스트레스 회귀 기준이다.
    if args.strict and (
        result["page_count"] < result["min_pages"]
        or result["detector_recall"] < 1.0
        or result["precision"] < 0.98
        or result["recall"] < 0.90
        or result["control_leakage"] > 0
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
