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


def _escape_css_attribute(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


async def _scan_frame(frame, prefix=""):
    """현재 frame과 모든 하위 iframe의 텍스트 요소를 재귀적으로 수집한다."""

    try:
        elements = await frame.evaluate(DOM_SCAN_SCRIPT)
    except Exception:
        # 로딩 도중 제거된 iframe 등은 전체 탐지를 중단하지 않고 건너뛴다.
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
            child_prefix = (
                prefix
                + f'iframe[src="{escaped_src}"] >>> '
            )

            child_elements, child_count = await _scan_frame(
                child,
                child_prefix,
            )

            elements.extend(child_elements)
            frame_count += child_count

        except Exception:
            # 특정 iframe 하나의 실패가 전체 페이지 분석 실패로 이어지지 않게 한다.
            continue

    return elements, frame_count


async def scan_page(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            viewport={
                "width": 1280,
                "height": 720,
            },
            ignore_https_errors=True,
        )

        page = await context.new_page()

        print("[ARGUS] 페이지 접속 중...")

        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        # DOMContentLoaded 직후 생성되는 iframe/콘텐츠가 붙을 시간을 아주 조금 준다.
        await page.wait_for_timeout(150)

        title = await page.title()

        print("[ARGUS] DOM 및 iframe 분석 중...")

        elements, frame_count = await _scan_frame(page.main_frame)

        result = {
            "title": title,
            "url": page.url,
            "elements": elements,
            "frame_count": frame_count,
        }

        await context.close()
        await browser.close()

        return result
