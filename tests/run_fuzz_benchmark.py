import argparse
import asyncio
import html
import random
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
CHO = ["ㄱ","ㄲ","ㄴ","ㄷ","ㄸ","ㄹ","ㅁ","ㅂ","ㅃ","ㅅ","ㅆ","ㅇ","ㅈ","ㅉ","ㅊ","ㅋ","ㅌ","ㅍ","ㅎ"]
JUNG = ["ㅏ","ㅐ","ㅑ","ㅒ","ㅓ","ㅔ","ㅕ","ㅖ","ㅗ","ㅘ","ㅙ","ㅚ","ㅛ","ㅜ","ㅝ","ㅞ","ㅟ","ㅠ","ㅡ","ㅢ","ㅣ"]
JONG = ["","ㄱ","ㄲ","ㄳ","ㄴ","ㄵ","ㄶ","ㄷ","ㄹ","ㄺ","ㄻ","ㄼ","ㄽ","ㄾ","ㄿ","ㅀ","ㅁ","ㅂ","ㅄ","ㅅ","ㅆ","ㅇ","ㅈ","ㅊ","ㅋ","ㅌ","ㅍ","ㅎ"]
SYLLABLES = ["카","파","노","루","베","도","세","미","타","라","코","주"]

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


def pct(value):
    return f"{value * 100:.1f}%"


def div(a, b):
    return a / b if b else 0.0


def normalized_page(value):
    parts = urlsplit(value)
    path = parts.path.lstrip("/")
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return f"{path}?{query}" if query else path


def record_key(record):
    return (normalized_page(record["page"]), record["technique"], record["evidence_text"])


def candidate_key(candidate):
    return (
        normalized_page(candidate.get("url", "")),
        candidate.get("technique", ""),
        candidate.get("evidence_text", ""),
    )


def token(rng, length=5):
    alphabet = "QWRTYPSDFGHJKLZCVBNM"
    chars = [rng.choice(alphabet) for _ in range(max(3, length))]
    chars[len(chars) // 2] = "O"
    return "".join(chars[:length])


def neutral_text(rng, index, zws=False):
    sep = "\u200b " if zws else " "
    return f"{token(rng, 5)}{sep}{token(rng, 4)} {100 + index}"


def pseudo_hangul(index):
    return (
        SYLLABLES[index % len(SYLLABLES)]
        + SYLLABLES[(index * 3 + 2) % len(SYLLABLES)]
        + SYLLABLES[(index * 5 + 5) % len(SYLLABLES)]
    )


def decompose_compat(text):
    out = []
    for char in text:
        code = ord(char)
        if not 0xAC00 <= code <= 0xD7A3:
            out.append(char)
            continue
        offset = code - 0xAC00
        cho = offset // 588
        jung = (offset % 588) // 28
        jong = offset % 28
        out.extend([CHO[cho], JUNG[jung]])
        if jong:
            out.append(JONG[jong])
    return "".join(out)


def decompose_modern(text):
    out = []
    for char in text:
        code = ord(char)
        if not 0xAC00 <= code <= 0xD7A3:
            out.append(char)
            continue
        offset = code - 0xAC00
        cho = offset // 588
        jung = (offset % 588) // 28
        jong = offset % 28
        out.extend([chr(0x1100 + cho), chr(0x1161 + jung)])
        if jong:
            out.append(chr(0x11A7 + jong))
    return "".join(out)


def fullwidth(text):
    return "".join(chr(ord(c) + 0xFEE0) if 0x21 <= ord(c) <= 0x7E else c for c in text)


def make_case(rng, technique, index):
    family_index = index % 6
    case_id = f"F-{technique[:2]}-{index + 1:03d}"
    unique_id = f"case-{technique.lower()}-{index + 1:03d}"
    shared_id = f"shared-{technique.lower()}"
    script = ""

    if technique == "TRANSPARENT":
        families = ("opacity-zero-zws","color-transparent-plain","same-color-plain","mobile-only-zws","delayed-plain","repeated-location-zws")
        family = families[family_index]
        text = neutral_text(rng, index, family in {"opacity-zero-zws","mobile-only-zws","repeated-location-zws"})
        element_id = shared_id if family == "repeated-location-zws" else unique_id
        if family == "opacity-zero-zws":
            markup = f'<p id="{element_id}" style="opacity:0">{html.escape(text)}</p>'
        elif family == "color-transparent-plain":
            markup = f'<p id="{element_id}" style="color:transparent">{html.escape(text)}</p>'
        elif family == "same-color-plain":
            markup = f'<p id="{element_id}" style="color:#fff;background:#fff">{html.escape(text)}</p>'
        elif family == "mobile-only-zws":
            markup = f'<p id="{element_id}" class="mobile-transparent">{html.escape(text)}</p>'
        elif family == "delayed-plain":
            markup = f'<div id="slot-{unique_id}"></div>'
            payload = html.escape(text).replace("'", "&#39;")
            script = f"setTimeout(()=>document.getElementById('slot-{unique_id}').insertAdjacentHTML('beforeend','<p id=\"{unique_id}\" style=\"color:transparent\">{payload}</p>'),180);"
        else:
            markup = f'<p id="{element_id}" style="color:transparent">{html.escape(text)}</p>'

    elif technique == "OFFSCREEN":
        families = ("far-left-zws","tiny-plain","fixed-top-zws","display-none-zws","mobile-only-plain","repeated-location-zws")
        family = families[family_index]
        text = neutral_text(rng, index + 1000, family in {"far-left-zws","fixed-top-zws","display-none-zws","repeated-location-zws"})
        element_id = shared_id if family == "repeated-location-zws" else unique_id
        if family == "far-left-zws":
            markup = f'<p id="{element_id}" style="position:absolute;left:-9999px;top:320px">{html.escape(text)}</p>'
        elif family == "tiny-plain":
            markup = f'<p id="{element_id}" style="font-size:1px">{html.escape(text)}</p>'
        elif family == "fixed-top-zws":
            markup = f'<p id="{element_id}" style="position:fixed;top:-9999px;left:10px">{html.escape(text)}</p>'
        elif family == "display-none-zws":
            markup = f'<p id="{element_id}" style="display:none">{html.escape(text)}</p>'
        elif family == "mobile-only-plain":
            markup = f'<p id="{element_id}" class="mobile-offscreen">{html.escape(text)}</p>'
        else:
            markup = f'<p id="{element_id}" style="position:absolute;left:-9999px;top:360px">{html.escape(text)}</p>'

    elif technique == "JAMO":
        families = ("compat-stable","compat-mobile-only","compat-delayed","modern-stable","compat-punctuation","repeated-location")
        family = families[family_index]
        base = pseudo_hangul(index)
        text = decompose_modern(base) if family == "modern-stable" else decompose_compat(base)
        if family == "compat-punctuation":
            text = text[:2] + " · " + text[2:]
        element_id = shared_id if family == "repeated-location" else unique_id
        if family == "compat-mobile-only":
            payload = html.escape(text).replace("'", "&#39;")
            markup = f'<div id="slot-{unique_id}"></div>'
            script = (
                f"function rj{index}(){{const s=document.getElementById('slot-{unique_id}');s.innerHTML='';"
                f"if(innerWidth<=500)s.insertAdjacentHTML('beforeend','<p id=\"{unique_id}\">{payload}</p>');}}"
                f"rj{index}();addEventListener('resize',()=>setTimeout(rj{index},0));"
            )
        elif family == "compat-delayed":
            payload = html.escape(text).replace("'", "&#39;")
            markup = f'<div id="slot-{unique_id}"></div>'
            script = f"setTimeout(()=>document.getElementById('slot-{unique_id}').insertAdjacentHTML('beforeend','<p id=\"{unique_id}\">{payload}</p>'),180);"
        else:
            markup = f'<p id="{element_id}">{html.escape(text)}</p>'

    else:
        families = ("cyrillic-mixed","fullwidth-plain","digit-internal","greek-mixed","mobile-only-mixed","repeated-location-mixed")
        family = families[family_index]
        base = f"QO{token(rng, 3)}E"
        if family in {"cyrillic-mixed","mobile-only-mixed","repeated-location-mixed"}:
            text = base.replace("O", "О", 1) + " " + token(rng, 5)
        elif family == "fullwidth-plain":
            text = fullwidth(base + " " + token(rng, 5))
        elif family == "digit-internal":
            text = base.replace("O", "0", 1) + " " + token(rng, 5)
        else:
            text = base.replace("O", "Ο", 1) + " " + token(rng, 5)
        element_id = shared_id if family == "repeated-location-mixed" else unique_id
        if family == "mobile-only-mixed":
            payload = html.escape(text).replace("'", "&#39;")
            markup = f'<div id="slot-{unique_id}"></div>'
            script = (
                f"function rh{index}(){{const s=document.getElementById('slot-{unique_id}');s.innerHTML='';"
                f"if(innerWidth<=500)s.insertAdjacentHTML('beforeend','<p id=\"{unique_id}\">{payload}</p>');}}"
                f"rh{index}();addEventListener('resize',()=>setTimeout(rh{index},0));"
            )
        else:
            markup = f'<p id="{element_id}">{html.escape(text)}</p>'

    return {"id":case_id,"technique":technique,"family":family,"evidence_text":text,"html":markup,"script":script}


def controls_for_page(page_index):
    controls = [
        {"id":f"C-SKIP-{page_index:03d}","technique":"OFFSCREEN","evidence_text":"본문 바로가기","html":'<a id="site-skip-link" href="#content" style="position:absolute;left:-9999px;top:0">본문 바로가기</a>'}
    ]
    mode = page_index % 4
    if mode == 0:
        controls.append({"id":f"C-MENU-{page_index:03d}","technique":"OFFSCREEN","evidence_text":"모바일 메뉴","html":'<div id="site-mobile-menu" style="display:none">모바일 메뉴</div>'})
    elif mode == 1:
        controls.append({"id":f"C-META-{page_index:03d}","technique":"OFFSCREEN","evidence_text":"문서 버전 정보","html":'<span id="site-version-meta" style="font-size:1px">문서 버전 정보</span>'})
    elif mode == 2:
        controls.append({"id":f"C-FW-{page_index:03d}","technique":"HOMOGLYPH","evidence_text":"ＶＥＲＳＩＯＮ ２","html":'<p id="site-fullwidth-version">ＶＥＲＳＩＯＮ ２</p>'})
    else:
        controls.append({"id":f"C-JAMO-{page_index:03d}","technique":"JAMO","evidence_text":"ㅁㅔㄴㅠ ㅇㅏㄴㄴㅐ","html":'<p id="site-jamo-menu">ㅁㅔㄴㅠ ㅇㅏㄴㄴㅐ</p>'})
    return controls


def build_site(root, seed, per_technique):
    rng = random.Random(seed)
    positives, controls, pages = [], [], []
    by_technique = {t:[make_case(rng,t,i) for i in range(per_technique)] for t in TECHNIQUES}

    for i in range(per_technique):
        filename = f"post-{i + 1:03d}.html"
        page_cases = [by_technique[t][i] for t in TECHNIQUES]
        page_controls = controls_for_page(i)
        controls.extend({**c,"page":filename} for c in page_controls)
        markup = []
        scripts = []
        for case in page_cases:
            markup.append(case["html"])
            if case["script"]:
                scripts.append(case["script"])
            positives.append({
                "id":case["id"],"page":filename,"technique":case["technique"],
                "family":case["family"],"evidence_text":case["evidence_text"],
            })
        markup.extend(c["html"] for c in page_controls)
        document = f'''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fuzz {i+1}</title>
<style>body{{font-family:Arial,sans-serif;background:#f6f7f9;color:#20242b}}main{{max-width:900px;margin:auto;padding:24px;position:relative}}article{{background:white;padding:24px;min-height:520px}}.mobile-transparent{{color:#20242b}}.mobile-offscreen{{position:static}}@media(max-width:500px){{.mobile-transparent{{color:transparent}}.mobile-offscreen{{position:absolute;left:-9999px;top:300px}}}}</style></head>
<body><main><article id="content"><h1>일반 안내 문서 {i+1}</h1><p>외부 연결이나 입력 기능이 없는 로컬 합성 테스트 문서입니다.</p><div id="cases">{''.join(markup)}</div></article><p><a href="board.html">목록</a></p></main><script>{''.join(scripts)}</script></body></html>'''
        (root / filename).write_text(document, encoding="utf-8")
        pages.append(filename)

    links = "".join(f'<li><a href="{name}">문서 {idx+1}</a></li>' for idx,name in enumerate(pages))
    (root / "board.html").write_text(f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Fuzz Board</title></head><body><h1>게시판</h1><ul>{links}</ul><a href="index.html">홈</a></body></html>', encoding="utf-8")
    (root / "index.html").write_text('<!DOCTYPE html><html><head><meta charset="UTF-8"><title>ARGUS Fuzz</title></head><body><h1>ARGUS Mutation Fuzz Benchmark</h1><a href="board.html">게시판</a></body></html>', encoding="utf-8")
    return {"entry":"index.html","expected_min_pages":per_technique+2,"positives":positives,"benign_controls":controls}


def start_server(site_root):
    handler = partial(QuietHandler, directory=str(site_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


async def run(seed, per_technique, max_seconds):
    with tempfile.TemporaryDirectory(prefix="argus_fuzz_") as temp:
        root = Path(temp)
        truth = build_site(root, seed, per_technique)
        server, thread = start_server(root)
        port = server.server_address[1]
        entry = f"http://127.0.0.1:{port}/{truth['entry']}"
        try:
            print("===================================")
            print("      ARGUS MUTATION FUZZ TEST")
            print("===================================")
            print("seed               :", seed)
            print("positive           :", len(truth["positives"]))
            print("normal controls    :", len(truth["benign_controls"]))
            print("pages expected     :", truth["expected_min_pages"])
            print()

            started = time.perf_counter()
            crawl = await crawl_site(entry, max_pages=max(80, per_technique+10), max_seconds=max_seconds, worker_count=4, discovery_worker_count=8)
            elapsed = time.perf_counter() - started

            transparent, offscreen, jamo, homoglyph = [], [], [], []
            for page in crawl["pages"]:
                transparent.extend(detect_transparent_candidates(page))
                offscreen.extend(detect_offscreen_candidates(page))
                jamo.extend(detect_jamo_candidates(page))
                homoglyph.extend(detect_homoglyph_candidates(page))
            groups = [transparent, offscreen, jamo, homoglyph]
            raw = [c for group in groups for c in group]
            verified, rejected = verify_candidates(groups, pages=crawl["pages"])

            positives = {record_key(r):r for r in truth["positives"]}
            controls = {record_key(r):r for r in truth["benign_controls"]}
            detector_keys = {candidate_key(c) for c in raw}
            verified_map = {candidate_key(c):c for c in verified}
            detector_hits = {k for k in positives if k in detector_keys}
            verifier_hits = {k for k in positives if k in verified_map}
            unexpected = [c for k,c in verified_map.items() if k not in positives]
            control_leaks = [controls[k] for k in controls if k in verified_map]

            tp = len(verifier_hits)
            fp = len(unexpected)
            detector_recall = div(len(detector_hits), len(positives))
            precision = div(tp, tp + fp)
            recall = div(tp, len(positives))
            f1 = div(2 * precision * recall, precision + recall)
            status_counts = Counter(verified_map[k].get("verification_status","UNKNOWN") for k in verifier_hits)

            tech_stats = defaultdict(lambda:{"e":0,"d":0,"v":0})
            family_stats = defaultdict(lambda:{"e":0,"d":0,"v":0,"scores":[]})
            for key, record in positives.items():
                tr = tech_stats[record["technique"]]
                fr = family_stats[f"{record['technique']}::{record['family']}"]
                tr["e"] += 1; fr["e"] += 1
                if key in detector_keys:
                    tr["d"] += 1; fr["d"] += 1
                if key in verified_map:
                    tr["v"] += 1; fr["v"] += 1
                    fr["scores"].append(verified_map[key].get("open_set_score",0.0))

            page_count = crawl.get("page_count", len(crawl.get("pages",[])))
            print("==============================")
            print("          결과 요약")
            print("==============================")
            print("분석 완료 페이지 :", page_count, f"(최소 기대 {truth['expected_min_pages']})")
            print("분석 frame 수    :", crawl.get("frame_count",0))
            print("구조 후보 관측합 :", len(raw))
            print("검증 유지 후보   :", len(verified))
            print("검증 제외 후보   :", len(rejected))
            print("크롤링+검사 시간 :", f"{elapsed:.3f}초")
            print()
            print("Detector recall   :", pct(detector_recall), f"({len(detector_hits)}/{len(positives)})")
            print("Verifier precision:", pct(precision), f"({tp}/{tp+fp})" if tp+fp else "(0/0)")
            print("Verifier recall   :", pct(recall), f"({tp}/{len(positives)})")
            print("Verifier F1       :", pct(f1))
            print("CONFIRMED         :", status_counts.get("CONFIRMED",0))
            print("SUSPICIOUS        :", status_counts.get("SUSPICIOUS",0))
            print("Unexpected FP     :", fp)
            print("Control leakage   :", len(control_leaks), "/", len(controls))
            print()

            print("기법별 정답 / detector / verifier")
            for technique in TECHNIQUES:
                row = tech_stats[technique]
                print(f"  {technique:<11} {row['e']:>3} / {row['d']:>3} / {row['v']:>3}")

            print("\n[변이 family별 결과]")
            for name in sorted(family_stats):
                row = family_stats[name]
                avg = div(sum(row["scores"]), len(row["scores"])) if row["scores"] else 0.0
                print(f"  {name:<42} {row['e']:>2} / {row['d']:>2} / {row['v']:>2} open_avg={avg:.3f}")

            detector_misses = [record for key,record in positives.items() if key not in detector_keys]
            verifier_only_misses = [
                record for key,record in positives.items()
                if key in detector_keys and key not in verified_map
            ]
            if detector_misses:
                print("\n[Detector 누락 상위 20건]")
                for record in detector_misses[:20]:
                    print(" -", record["id"], record["technique"], record["family"], record["page"], "|", record["evidence_text"])

            if verifier_only_misses:
                print("\n[Detector는 잡았지만 Verifier가 제외한 상위 20건]")
                for record in verifier_only_misses[:20]:
                    print(" -", record["id"], record["technique"], record["family"], record["page"], "|", record["evidence_text"])

            weakest = sorted(
                (
                    (
                        verified_map[k].get("open_set_score",0.0),
                        positives[k],
                        verified_map[k],
                    )
                    for k in verifier_hits
                ),
                key=lambda item: item[0],
            )
            if weakest:
                print("\n[유지된 정답 중 open-set 점수 하위 10건]")
                for score,record,candidate in weakest[:10]:
                    print(" -", record["id"], candidate.get("verification_status"), record["technique"], record["family"], f"semantic={candidate.get('semantic_score')}", f"open={score}", f"passes={len(candidate.get('scan_passes') or [])}")

            if unexpected:
                print("\n[예상하지 않은 최종 유지 후보 상위 20건]")
                for candidate in unexpected[:20]:
                    print(" -", candidate.get("verification_status"), candidate.get("technique"), normalized_page(candidate.get("url","")), "|", candidate.get("evidence_text",""))

            return {"page_count":page_count,"min_pages":truth["expected_min_pages"],"detector_recall":detector_recall,"precision":precision,"recall":recall,"f1":f1,"control_leakage":len(control_leaks)}
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description="ARGUS deterministic mutation fuzz benchmark")
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument("--per-technique", type=int, default=24, help="각 탐지 기법마다 생성할 positive 수")
    parser.add_argument("--max-seconds", type=float, default=240.0)
    parser.add_argument("--strict", action="store_true", help="ARGUS 내부 스트레스 기준 미달 시 exit code 1")
    args = parser.parse_args()
    if args.per_technique < 6:
        parser.error("--per-technique은 최소 6이어야 합니다")
    result = asyncio.run(run(args.seed, args.per_technique, args.max_seconds))
    # 공모전 공식 기준이 아니라 ARGUS 자체 회귀 기준.
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