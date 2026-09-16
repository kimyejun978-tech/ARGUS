import re
import time
from collections import Counter, deque
from urllib.parse import parse_qsl, urlencode, urldefrag, unquote, urlsplit, urlunsplit

from playwright.async_api import async_playwright


DOM_SCAN_SCRIPT = r"""
() => {
    function makeSelector(element) {
        if (!element || element.nodeType !== 1) {
            return "";
        }

        const parts = [];
        let current = element;

        while (current && current.nodeType === 1) {
            let part = current.tagName.toLowerCase();

            if (current.id) {
                part += "#" + CSS.escape(current.id);
                parts.unshift(part);
                break;
            }

            const parent = current.parentElement;

            if (parent) {
                const sameTags = Array.from(parent.children).filter(
                    child => child.tagName === current.tagName
                );

                if (sameTags.length > 1) {
                    const index = sameTags.indexOf(current) + 1;
                    part += `:nth-of-type(${index})`;
                }
            }

            parts.unshift(part);
            current = current.parentElement;
        }

        return parts.join(" > ");
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
        let current = element;
        let effectiveOpacity = 1;
        let opacitySource = null;
        let displayNoneSource = null;

        while (current) {
            const style = window.getComputedStyle(current);
            const opacity = Number(style.opacity);

            if (!Number.isNaN(opacity)) {
                effectiveOpacity *= opacity;

                if (opacity === 0 && opacitySource === null) {
                    opacitySource = makeSelector(current);
                }
            }

            if (style.display === "none" && displayNoneSource === null) {
                displayNoneSource = makeSelector(current);
            }

            current = current.parentElement;
        }

        return {
            effectiveOpacity,
            opacitySource,
            displayNoneSource
        };
    }

    function findBackgroundColor(element) {
        let current = element;

        while (current) {
            const style = window.getComputedStyle(current);
            const background = style.backgroundColor;

            if (getColorAlpha(background) > 0) {
                return background;
            }

            current = current.parentElement;
        }

        return null;
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

        const directText = Array.from(element.childNodes)
            .filter(node => node.nodeType === Node.TEXT_NODE)
            .map(node => node.textContent || "")
            .join(" ")
            .replace(/\s+/g, " ")
            .trim();

        if (!directText) {
            continue;
        }

        const style = window.getComputedStyle(element);
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
    """
    비슷한 URL이 탐색 슬롯을 독점하지 않도록 URL의 구조적 패턴을 만든다.

    예:
      /post/123 -> /post/{n}
      /school/.../202601.html -> 숫자 부분을 {n}으로 일반화
      /series/foo-all.html -> /series/{item}
    """

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

    return f"{parsed.scheme.lower()}://{(parsed.hostname or '').lower()}{normalized_path}?{query_signature}"


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


async def _scan_loaded_page(page):
    title = await page.title()
    elements, frame_count = await _scan_frame(page.main_frame)

    return {
        "title": title,
        "url": page.url,
        "elements": elements,
        "frame_count": frame_count,
    }


async def scan_page(url):
    """단일 페이지 검사. 기존 테스트와 디버깅용으로 유지한다."""

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
        await page.wait_for_timeout(150)

        print("[ARGUS] DOM 및 iframe 분석 중...")
        result = await _scan_loaded_page(page)

        await context.close()
        await browser.close()

        return result


async def crawl_site(
    entry_url,
    max_pages=1000,
    max_seconds=180,
    pattern_priority_samples=2,
):
    """
    진입 URL에서 같은 사이트를 탐색한다.

    페이지 50개 같은 작은 고정 제한 대신:
    - 서로 다른 URL 패턴을 먼저 방문
    - 반복 패턴 URL은 후순위 큐에 보관
    - 시간 예산과 큰 하드 페이지 제한을 함께 사용

    반복 URL을 버리는 것이 아니라 '나중에' 검사하므로 범위와 시간을 균형 있게 쓴다.
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
                f"[ARGUS] 페이지 탐색 {len(pages) + 1}: "
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
                await page.goto(
                    requested_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                await page.wait_for_timeout(150)
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

            page_result = await _scan_loaded_page(page)
            page_result["url"] = final_url
            pages.append(page_result)

            links = await _collect_links(page)

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
                queue.add(candidate) if False else None
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
        "element_count": sum(len(page["elements"]) for page in pages),
        "limit_reached": page_limit_reached or time_limit_reached,
        "page_limit_reached": page_limit_reached,
        "time_limit_reached": time_limit_reached,
        "pending_count": pending_count,
        "errors": errors,
    }
