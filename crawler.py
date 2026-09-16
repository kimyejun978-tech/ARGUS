from collections import deque
from urllib.parse import parse_qsl, urlencode, urldefrag, urlsplit, urlunsplit

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

        while (current) {
            const style = window.getComputedStyle(current);
            const opacity = Number(style.opacity);

            if (!Number.isNaN(opacity)) {
                effectiveOpacity *= opacity;

                if (opacity === 0 && opacitySource === null) {
                    opacitySource = makeSelector(current);
                }
            }

            current = current.parentElement;
        }

        return {
            effectiveOpacity,
            opacitySource
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

    for (const element of elements) {
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
    ".svg",
    ".tar",
    ".webm",
    ".webp",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
}


def _escape_css_attribute(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _canonicalize_url(url: str) -> str:
    """fragment를 제거하고 query 순서를 정규화해 중복 방문을 줄인다."""

    url, _ = urldefrag(url)
    parsed = urlsplit(url)

    if parsed.scheme in {"http", "https"}:
        query_items = parse_qsl(parsed.query, keep_blank_values=True)
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


async def crawl_site(entry_url, max_pages=50):
    """
    진입 URL에서 같은 사이트의 링크를 BFS 방식으로 따라가며 검사한다.

    max_pages는 개발 단계의 안전장치다. 최종 대회 설정에서는 테스트 사이트
    규모를 확인한 뒤 조정할 수 있다.
    """

    canonical_entry = _canonicalize_url(entry_url)
    entry_parsed = urlsplit(canonical_entry)
    entry_scheme = entry_parsed.scheme

    allowed_hosts = set()

    if entry_parsed.hostname:
        allowed_hosts.add(entry_parsed.hostname.lower())

    queue = deque([canonical_entry])
    queued = {canonical_entry}
    visited = set()
    pages = []
    errors = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )
        page = await context.new_page()

        while queue and len(pages) < max_pages:
            requested_url = queue.popleft()
            queued.discard(requested_url)

            if requested_url in visited:
                continue

            visited.add(requested_url)

            print(
                f"[ARGUS] 페이지 탐색 {len(pages) + 1}/{max_pages}: "
                f"{requested_url}"
            )

            try:
                await page.goto(
                    requested_url,
                    wait_until="domcontentloaded",
                    timeout=30000,
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

            # 최초 진입 시 www 유무 등의 redirect가 있었다면 최종 host도 허용한다.
            if len(pages) == 0 and final_parsed.hostname:
                allowed_hosts.add(final_parsed.hostname.lower())

            if not _is_same_site(final_url, allowed_hosts, entry_scheme):
                continue

            page_result = await _scan_loaded_page(page)
            page_result["url"] = final_url
            pages.append(page_result)

            links = await _collect_links(page)

            for link in links:
                candidate = _canonicalize_url(link)

                if not _is_supported_page_url(candidate):
                    continue

                if not _is_same_site(candidate, allowed_hosts, entry_scheme):
                    continue

                if candidate in visited or candidate in queued:
                    continue

                queue.append(candidate)
                queued.add(candidate)

        await context.close()
        await browser.close()

    return {
        "entry_url": canonical_entry,
        "pages": pages,
        "page_count": len(pages),
        "frame_count": sum(page.get("frame_count", 1) for page in pages),
        "element_count": sum(len(page["elements"]) for page in pages),
        "limit_reached": bool(queue),
        "errors": errors,
    }
