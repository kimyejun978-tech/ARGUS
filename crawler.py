import re
import time
from collections import Counter, deque
from urllib.parse import parse_qsl, urlencode, urldefrag, unquote, urlsplit, urlunsplit

from playwright.async_api import async_playwright


DOM_SCAN_SCRIPT = r"""
() => {
    const styleCache = new WeakMap();
    const selectorCache = new WeakMap();
    const effectiveCache = new WeakMap();
    const backgroundCache = new WeakMap();

    function getStyle(element) {
        let style = styleCache.get(element);

        if (!style) {
            style = window.getComputedStyle(element);
            styleCache.set(element, style);
        }

        return style;
    }

    function makeSelector(element) {
        if (!element || element.nodeType !== 1) {
            return "";
        }

        const cached = selectorCache.get(element);
        if (cached !== undefined) {
            return cached;
        }

        let part = element.tagName.toLowerCase();
        let selector = part;

        if (element.id) {
            selector = part + "#" + CSS.escape(element.id);
            selectorCache.set(element, selector);
            return selector;
        }

        const parent = element.parentElement;

        if (parent) {
            let sameTagCount = 0;
            let sameTagIndex = 0;

            for (const child of parent.children) {
                if (child.tagName !== element.tagName) {
                    continue;
                }

                sameTagCount += 1;

                if (child === element) {
                    sameTagIndex = sameTagCount;
                }
            }

            if (sameTagCount > 1) {
                part += `:nth-of-type(${sameTagIndex})`;
            }

            const parentSelector = makeSelector(parent);
            selector = parentSelector
                ? parentSelector + " > " + part
                : part;
        }

        selectorCache.set(element, selector);
        return selector;
    }

    function getColorAlpha(color) {
        if (!color) {
            return 1;
        }

        if (color === "transparent") {
            return 0;
        }

        const match = color.match(
            /rgba\([^,]+,[^,]+,[^,]+,\s*([0-9.]+)\)/
        );

        if (match) {
            return Number(match[1]);
        }

        return 1;
    }

    function getEffectiveInfo(element) {
        const cached = effectiveCache.get(element);
        if (cached) {
            return cached;
        }

        const chain = [];
        let current = element;

        while (current && !effectiveCache.has(current)) {
            chain.push(current);
            current = current.parentElement;
        }

        let info = current
            ? effectiveCache.get(current)
            : {
                effectiveOpacity: 1,
                opacitySource: null,
                displayNoneSource: null
            };

        for (let index = chain.length - 1; index >= 0; index -= 1) {
            const node = chain[index];
            const style = getStyle(node);
            const opacity = Number(style.opacity);
            const localOpacity = Number.isNaN(opacity) ? 1 : opacity;

            info = {
                effectiveOpacity: info.effectiveOpacity * localOpacity,
                opacitySource:
                    opacity === 0
                        ? makeSelector(node)
                        : info.opacitySource,
                displayNoneSource:
                    style.display === "none"
                        ? makeSelector(node)
                        : info.displayNoneSource
            };

            effectiveCache.set(node, info);
        }

        return effectiveCache.get(element);
    }

    function findBackgroundColor(element) {
        if (backgroundCache.has(element)) {
            return backgroundCache.get(element);
        }

        const chain = [];
        let current = element;

        while (current && !backgroundCache.has(current)) {
            chain.push(current);
            current = current.parentElement;
        }

        let background = current
            ? backgroundCache.get(current)
            : null;

        for (let index = chain.length - 1; index >= 0; index -= 1) {
            const node = chain[index];
            const ownBackground = getStyle(node).backgroundColor;

            if (getColorAlpha(ownBackground) > 0) {
                background = ownBackground;
            }

            backgroundCache.set(node, background);
        }

        return backgroundCache.get(element);
    }

    const result = [];
    const elements = document.querySelectorAll("body *");

    const ignoredTags = new Set([
        "SCRIPT",
        "STYLE",
        "NOSCRIPT",
        "TEMPLATE",
        "META",
        "LINK"
    ]);

    for (const element of elements) {
        if (ignoredTags.has(element.tagName)) {
            continue;
        }

        const directTextParts = [];

        for (const node of element.childNodes) {
            if (node.nodeType === Node.TEXT_NODE) {
                directTextParts.push(node.textContent || "");
            }
        }

        const directText = directTextParts
            .join(" ")
            .replace(/\s+/g, " ")
            .trim();

        if (!directText) {
            continue;
        }

        const style = getStyle(element);
        const rect = element.getBoundingClientRect();
        const effective = getEffectiveInfo(element);
        const backgroundColor = findBackgroundColor(element);
        const textColor = style.color;

        result.push({
            tag: element.tagName.toLowerCase(),
            selector: makeSelector(element),
            text: directText,
            style: {
                display: style.display,
                visibility: style.visibility,
                opacity: Number(style.opacity),
                color: textColor,
                backgroundColor,
                fontSize: style.fontSize,
                position: style.position,
                left: style.left,
                top: style.top
            },
            effectiveOpacity: effective.effectiveOpacity,
            opacitySource: effective.opacitySource,
            displayNoneSource: effective.displayNoneSource,
            textColorAlpha: getColorAlpha(textColor),
            sameTextBackground:
                backgroundColor !== null && textColor === backgroundColor,
            rect: {
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height
            },
            inViewport:
                rect.width > 0 &&
                rect.height > 0 &&
                rect.bottom > 0 &&
                rect.right > 0 &&
                rect.top < window.innerHeight &&
                rect.left < window.innerWidth
        });
    }

    return result;
}
"""


STATIC_EXTENSIONS = {
    ".7z",
    ".atom",
    ".avi",
    ".css",
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".rss",
    ".svg",
    ".tar",
    ".webm",
    ".webp",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
}

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}

DYNAMIC_PATH_GROUPS = {
    "article",
    "articles",
    "board",
    "boards",
    "character",
    "characters",
    "gallery",
    "post",
    "posts",
    "series",
    "tag",
    "tags",
}

# 정밀 모드의 다중 검사 뷰포트.
# 같은 DOM이라도 media query에 따라 은닉 상태가 달라질 수 있어
# 데스크톱과 모바일을 모두 관측한다.
MULTI_SCAN_VIEWPORTS = [
    ("desktop", {"width": 1280, "height": 720}),
    ("mobile", {"width": 390, "height": 844}),
]


def _escape_css_attribute(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _canonicalize_url(url: str) -> str:
    """fragment와 대표 추적 파라미터를 제거해 중복 방문을 줄인다."""

    url, _ = urldefrag(url)
    parsed = urlsplit(url)

    if parsed.scheme in {"http", "https"}:
        query_items = []

        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            lower_key = key.lower()

            if lower_key.startswith("utm_") or lower_key in TRACKING_QUERY_KEYS:
                continue

            query_items.append((key, value))

        normalized_query = urlencode(sorted(query_items), doseq=True)

        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path or "/",
                normalized_query,
                "",
            )
        )

    return url


def _url_pattern(url: str) -> str:
    """비슷한 URL이 탐색 슬롯을 독점하지 않도록 구조 패턴을 만든다."""

    parsed = urlsplit(url)
    path = unquote(parsed.path or "/").lower()
    segments = [segment for segment in path.split("/") if segment]
    normalized_segments = []
    previous = None

    for segment in segments:
        if previous in DYNAMIC_PATH_GROUPS:
            normalized = "{item}"
        else:
            normalized = re.sub(r"\d+", "{n}", segment)

            if normalized.endswith("-all.html"):
                normalized = "{item}-all.html"

        normalized_segments.append(normalized)
        previous = segment.lower()

    normalized_path = "/" + "/".join(normalized_segments)

    if path.endswith("/") and normalized_path != "/":
        normalized_path += "/"

    query_keys = sorted(
        key.lower()
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_QUERY_KEYS
    )

    query_signature = "&".join(query_keys)

    return (
        f"{parsed.scheme.lower()}://{(parsed.hostname or '').lower()}"
        f"{normalized_path}?{query_signature}"
    )


def _is_supported_page_url(url: str) -> bool:
    parsed = urlsplit(url)

    if parsed.scheme not in {"http", "https", "file"}:
        return False

    path_lower = parsed.path.lower()
    return not any(path_lower.endswith(ext) for ext in STATIC_EXTENSIONS)


def _is_same_site(url: str, allowed_hosts: set[str], entry_scheme: str) -> bool:
    parsed = urlsplit(url)

    if entry_scheme == "file":
        return parsed.scheme == "file"

    if parsed.scheme not in {"http", "https"}:
        return False

    return (parsed.hostname or "").lower() in allowed_hosts


async def _scan_frame(frame, prefix=""):
    """현재 frame과 모든 하위 iframe의 텍스트 요소를 재귀적으로 수집한다."""

    try:
        elements = await frame.evaluate(DOM_SCAN_SCRIPT)
    except Exception:
        return [], 0

    for element in elements:
        element["selector"] = prefix + element["selector"]

        if element.get("opacitySource"):
            element["opacitySource"] = prefix + element["opacitySource"]

        if element.get("displayNoneSource"):
            element["displayNoneSource"] = prefix + element["displayNoneSource"]

    frame_count = 1

    for child in frame.child_frames:
        try:
            frame_element = await child.frame_element()

            absolute_src = await frame_element.evaluate(
                """
                element =>
                    element.src ||
                    element.getAttribute("src") ||
                    "about:blank"
                """
            )

            if not absolute_src:
                absolute_src = child.url or "about:blank"

            escaped_src = _escape_css_attribute(absolute_src)
            child_prefix = prefix + f'iframe[src="{escaped_src}"] >>> '

            child_elements, child_count = await _scan_frame(
                child,
                child_prefix,
            )

            elements.extend(child_elements)
            frame_count += child_count

        except Exception:
            continue

    return elements, frame_count


async def _collect_links(page):
    """메인 문서와 iframe 안의 링크를 절대 URL 형태로 수집한다."""

    links = set()

    for frame in page.frames:
        try:
            frame_links = await frame.eval_on_selector_all(
                "a[href]",
                "elements => elements.map(element => element.href).filter(Boolean)",
            )
            links.update(frame_links)
        except Exception:
            continue

    return links


async def _wait_for_dom_quiet(page, quiet_ms=140, max_ms=900):
    """
    고정 sleep 대신 DOM 변경이 잠시 멈출 때까지 기다린다.
    계속 변하는 페이지는 max_ms에서 강제로 빠져나온다.
    """

    try:
        await page.evaluate(
            """
            ({quietMs, maxMs}) => new Promise(resolve => {
                let finished = false;
                let quietTimer = null;
                let maxTimer = null;

                const finish = () => {
                    if (finished) return;
                    finished = true;
                    if (quietTimer) clearTimeout(quietTimer);
                    if (maxTimer) clearTimeout(maxTimer);
                    observer.disconnect();
                    resolve(true);
                };

                const armQuietTimer = () => {
                    if (quietTimer) clearTimeout(quietTimer);
                    quietTimer = setTimeout(finish, quietMs);
                };

                const observer = new MutationObserver(armQuietTimer);
                const root = document.documentElement || document;

                observer.observe(root, {
                    subtree: true,
                    childList: true,
                    attributes: true,
                    characterData: true
                });

                armQuietTimer();
                maxTimer = setTimeout(finish, maxMs);
            })
            """,
            {"quietMs": quiet_ms, "maxMs": max_ms},
        )
    except Exception:
        return


async def _auto_scroll(page, max_steps=24, delay_ms=45):
    """lazy-load/무한스크롤 계열 콘텐츠가 나타나도록 제한된 자동 스크롤을 수행한다."""

    try:
        await page.evaluate(
            """
            async ({maxSteps, delayMs}) => {
                const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
                window.scrollTo(0, 0);
                await sleep(delayMs);

                let previousHeight = 0;
                let stableBottomRounds = 0;

                for (let i = 0; i < maxSteps; i++) {
                    const height = Math.max(
                        document.documentElement.scrollHeight,
                        document.body ? document.body.scrollHeight : 0
                    );

                    const step = Math.max(Math.floor(window.innerHeight * 0.85), 420);
                    const maxY = Math.max(0, height - window.innerHeight);
                    const nextY = Math.min(window.scrollY + step, maxY);

                    window.scrollTo(0, nextY);
                    await sleep(delayMs);

                    const newHeight = Math.max(
                        document.documentElement.scrollHeight,
                        document.body ? document.body.scrollHeight : 0
                    );
                    const atBottom = window.scrollY + window.innerHeight >= newHeight - 4;

                    if (atBottom) {
                        if (newHeight === previousHeight) {
                            stableBottomRounds += 1;
                        } else {
                            stableBottomRounds = 0;
                        }

                        if (stableBottomRounds >= 2) {
                            break;
                        }
                    }

                    previousHeight = newHeight;
                }
            }
            """,
            {"maxSteps": max_steps, "delayMs": delay_ms},
        )
    except Exception:
        return


async def _capture_pass(page, pass_name):
    pass_started = time.perf_counter()

    dom_started = time.perf_counter()
    elements, frame_count = await _scan_frame(page.main_frame)
    dom_elapsed = time.perf_counter() - dom_started

    for element in elements:
        element["scan_pass"] = pass_name

    links_started = time.perf_counter()
    links = await _collect_links(page)
    links_elapsed = time.perf_counter() - links_started

    return {
        "name": pass_name,
        "elements": elements,
        "frame_count": frame_count,
        "links": links,
        "timing": {
            "total": time.perf_counter() - pass_started,
            "dom_scan": dom_elapsed,
            "link_collect": links_elapsed,
        },
    }


async def _scan_loaded_page_multi(page):
    """
    하나의 페이지를 여러 상태에서 반복 검사한다.

    1) 데스크톱 즉시 상태
    2) 데스크톱 DOM 안정 상태
    3) 데스크톱 스크롤 후 상태
    4) 모바일 DOM 안정 상태
    5) 모바일 스크롤 후 상태

    각 패스의 요소를 모두 보존해 어느 한 상태에서만 숨겨지는 요소도 놓치지 않는다.
    최종 후보 중복은 verifier에서 (url + location + technique) 기준으로 합친다.

    timings는 진단용 계측치일 뿐 탐지 동작에는 사용하지 않는다.
    """
    scan_started = time.perf_counter()
    timings = {
        "title": 0.0,
        "viewport_setup": 0.0,
        "wait_dom_quiet": 0.0,
        "auto_scroll": 0.0,
        "pass_capture": 0.0,
        "dom_scan": 0.0,
        "link_collect": 0.0,
        "passes": {},
    }

    stage_started = time.perf_counter()
    title = await page.title()
    timings["title"] += time.perf_counter() - stage_started
    passes = []

    desktop_name, desktop_viewport = MULTI_SCAN_VIEWPORTS[0]
    stage_started = time.perf_counter()
    await page.set_viewport_size(desktop_viewport)
    await page.evaluate("window.scrollTo(0, 0)")
    timings["viewport_setup"] += time.perf_counter() - stage_started

    first_pass = await _capture_pass(page, f"{desktop_name}-initial")
    passes.append(first_pass)

    stage_started = time.perf_counter()
    await _wait_for_dom_quiet(page)
    timings["wait_dom_quiet"] += time.perf_counter() - stage_started
    settled_pass = await _capture_pass(page, f"{desktop_name}-settled")
    passes.append(settled_pass)

    stage_started = time.perf_counter()
    await _auto_scroll(page)
    timings["auto_scroll"] += time.perf_counter() - stage_started
    stage_started = time.perf_counter()
    await _wait_for_dom_quiet(page)
    timings["wait_dom_quiet"] += time.perf_counter() - stage_started
    scrolled_pass = await _capture_pass(page, f"{desktop_name}-scrolled")
    passes.append(scrolled_pass)

    mobile_name, mobile_viewport = MULTI_SCAN_VIEWPORTS[1]
    stage_started = time.perf_counter()
    await page.set_viewport_size(mobile_viewport)
    await page.evaluate("window.scrollTo(0, 0)")
    timings["viewport_setup"] += time.perf_counter() - stage_started
    stage_started = time.perf_counter()
    await _wait_for_dom_quiet(page)
    timings["wait_dom_quiet"] += time.perf_counter() - stage_started
    mobile_settled_pass = await _capture_pass(
        page,
        f"{mobile_name}-settled",
    )
    passes.append(mobile_settled_pass)

    stage_started = time.perf_counter()
    await _auto_scroll(page)
    timings["auto_scroll"] += time.perf_counter() - stage_started
    stage_started = time.perf_counter()
    await _wait_for_dom_quiet(page)
    timings["wait_dom_quiet"] += time.perf_counter() - stage_started
    mobile_scrolled_pass = await _capture_pass(
        page,
        f"{mobile_name}-scrolled",
    )
    passes.append(mobile_scrolled_pass)

    all_elements = []
    all_links = set()
    max_frame_count = 1

    for scan_pass in passes:
        all_elements.extend(scan_pass["elements"])
        all_links.update(scan_pass["links"])
        max_frame_count = max(max_frame_count, scan_pass["frame_count"])

        pass_timing = scan_pass.get("timing", {})
        timings["passes"][scan_pass["name"]] = {
            "total": pass_timing.get("total", 0.0),
            "dom_scan": pass_timing.get("dom_scan", 0.0),
            "link_collect": pass_timing.get("link_collect", 0.0),
            "observations": len(scan_pass["elements"]),
            "frames": scan_pass["frame_count"],
        }
        timings["pass_capture"] += pass_timing.get("total", 0.0)
        timings["dom_scan"] += pass_timing.get("dom_scan", 0.0)
        timings["link_collect"] += pass_timing.get("link_collect", 0.0)

    unique_elements = {
        (element.get("selector"), element.get("text"))
        for element in all_elements
    }

    timings["scan_total"] = time.perf_counter() - scan_started

    return {
        "title": title,
        "url": page.url,
        "elements": all_elements,
        "frame_count": max_frame_count,
        "unique_element_count": len(unique_elements),
        "observation_count": len(all_elements),
        "scan_pass_count": len(passes),
        "scan_passes": [scan_pass["name"] for scan_pass in passes],
        "timings": timings,
        "links": all_links,
    }


async def scan_page(url):
    """단일 페이지 정밀 다중 검사. 테스트/디버깅용으로 유지한다."""

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )
        page = await context.new_page()

        print("[ARGUS] 페이지 접속 중...")

        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        print("[ARGUS] 다중 DOM/iframe 분석 중...")
        result = await _scan_loaded_page_multi(page)
        result.pop("links", None)

        await context.close()
        await browser.close()

        return result


async def crawl_site(
    entry_url,
    max_pages=10000,
    max_seconds=1500,
    pattern_priority_samples=2,
):
    """
    진입 URL에서 같은 사이트를 정밀 탐색한다.

    - URL 패턴은 우선순위에만 사용하고 반복 URL을 버리지 않는다.
    - 발견한 모든 고유 URL은 시간이 허용되는 한 실제 브라우저 검사한다.
    - 각 URL은 데스크톱/모바일, 초기/안정/스크롤 상태로 다중 검사한다.
    - 시간 예산과 큰 하드 페이지 제한은 무한 크롤링 방지용 안전장치다.
    """

    canonical_entry = _canonicalize_url(entry_url)
    entry_parsed = urlsplit(canonical_entry)
    entry_scheme = entry_parsed.scheme

    allowed_hosts = set()

    if entry_parsed.hostname:
        allowed_hosts.add(entry_parsed.hostname.lower())

    priority_queue = deque([canonical_entry])
    deferred_queue = deque()
    queued = {canonical_entry}
    visited = set()
    scanned_urls = set()
    pages = []
    errors = []

    scheduled_patterns = Counter({_url_pattern(canonical_entry): 1})
    start_timer = time.perf_counter()
    time_limit_reached = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )
        page = await context.new_page()

        while (
            (priority_queue or deferred_queue)
            and len(pages) < max_pages
        ):
            elapsed = time.perf_counter() - start_timer

            if max_seconds is not None and elapsed >= max_seconds:
                time_limit_reached = True
                break

            if priority_queue:
                requested_url = priority_queue.popleft()
            else:
                requested_url = deferred_queue.popleft()

            queued.discard(requested_url)

            if requested_url in visited:
                continue

            visited.add(requested_url)

            print(
                f"[ARGUS] 페이지 정밀 탐색 {len(pages) + 1}: "
                f"{requested_url}"
            )

            timeout_ms = 30000

            if max_seconds is not None:
                remaining = max_seconds - (time.perf_counter() - start_timer)

                if remaining <= 0:
                    time_limit_reached = True
                    break

                timeout_ms = int(max(1000, min(30000, remaining * 1000)))

            try:
                await page.set_viewport_size({"width": 1280, "height": 720})
                await page.goto(
                    requested_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
            except Exception as exc:
                errors.append(
                    {
                        "url": requested_url,
                        "error": str(exc),
                    }
                )
                continue

            final_url = _canonicalize_url(page.url)
            final_parsed = urlsplit(final_url)

            if len(pages) == 0 and final_parsed.hostname:
                allowed_hosts.add(final_parsed.hostname.lower())

            if not _is_same_site(final_url, allowed_hosts, entry_scheme):
                continue

            if final_url in scanned_urls:
                continue

            scanned_urls.add(final_url)

            try:
                page_result = await _scan_loaded_page_multi(page)
            except Exception as exc:
                errors.append(
                    {
                        "url": final_url,
                        "error": f"multi-scan failed: {exc}",
                    }
                )
                continue

            page_result["url"] = final_url
            links = page_result.pop("links", set())
            pages.append(page_result)

            for link in sorted(links):
                candidate = _canonicalize_url(link)

                if not _is_supported_page_url(candidate):
                    continue

                if not _is_same_site(candidate, allowed_hosts, entry_scheme):
                    continue

                if candidate in visited or candidate in queued:
                    continue

                pattern = _url_pattern(candidate)

                if scheduled_patterns[pattern] < pattern_priority_samples:
                    priority_queue.append(candidate)
                else:
                    deferred_queue.append(candidate)

                scheduled_patterns[pattern] += 1
                queued.add(candidate)

        await context.close()
        await browser.close()

    pending_count = len(priority_queue) + len(deferred_queue)
    page_limit_reached = (
        len(pages) >= max_pages
        and pending_count > 0
    )

    return {
        "entry_url": canonical_entry,
        "pages": pages,
        "page_count": len(pages),
        "frame_count": sum(page.get("frame_count", 1) for page in pages),
        "element_count": sum(
            page.get("unique_element_count", len(page["elements"]))
            for page in pages
        ),
        "observation_count": sum(
            page.get("observation_count", len(page["elements"]))
            for page in pages
        ),
        "scan_pass_count": sum(
            page.get("scan_pass_count", 1)
            for page in pages
        ),
        "limit_reached": page_limit_reached or time_limit_reached,
        "page_limit_reached": page_limit_reached,
        "time_limit_reached": time_limit_reached,
        "pending_count": pending_count,
        "errors": errors,
    }
