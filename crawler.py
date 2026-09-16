from playwright.async_api import async_playwright


async def scan_page(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True
        )

        page = await browser.new_page()

        print("[ARGUS] 페이지 접속 중...")

        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        title = await page.title()

        print("[ARGUS] DOM 분석 중...")

        elements = await page.evaluate(
            """
            () => {

                // 요소의 CSS Selector를 만드는 함수
                function makeSelector(element) {

                    if (!element || element.nodeType !== 1) {
                        return "";
                    }

                    const parts = [];

                    let current = element;

                    while (
                        current &&
                        current.nodeType === 1
                    ) {

                        let part = current.tagName.toLowerCase();

                        // id가 있으면 그 위치에서 종료
                        if (current.id) {

                            part += "#" + CSS.escape(current.id);

                            parts.unshift(part);

                            break;
                        }

                        const parent = current.parentElement;

                        if (parent) {

                            const sameTagElements =
                                Array.from(parent.children)
                                .filter(
                                    child =>
                                        child.tagName === current.tagName
                                );

                            // 같은 태그가 여러 개 있으면 순서를 붙임
                            if (sameTagElements.length > 1) {

                                const index =
                                    sameTagElements.indexOf(current) + 1;

                                part += `:nth-of-type(${index})`;
                            }
                        }

                        parts.unshift(part);

                        current = parent;
                    }

                    return parts.join(" > ");
                }


                const result = [];

                const allElements =
                    document.querySelectorAll("body *");


                for (const element of allElements) {

                    /*
                     * 자식 요소의 텍스트까지 몽땅 가져오면
                     * 같은 문자열이 계속 중복되므로
                     * 현재 요소가 직접 가지고 있는 텍스트만 가져온다.
                     */

                    const directText =
                        Array.from(element.childNodes)
                        .filter(
                            node =>
                                node.nodeType === Node.TEXT_NODE
                        )
                        .map(
                            node => node.textContent
                        )
                        .join(" ")
                        .trim();


                    // 텍스트가 없으면 일단 제외
                    if (!directText) {
                        continue;
                    }


                    // 브라우저가 실제로 계산한 CSS
                    const style =
                        window.getComputedStyle(element);


                    // 브라우저 화면에서의 위치
                    const rect =
                        element.getBoundingClientRect();


                    const inViewport =
                        rect.width > 0 &&
                        rect.height > 0 &&
                        rect.bottom > 0 &&
                        rect.right > 0 &&
                        rect.top < window.innerHeight &&
                        rect.left < window.innerWidth;


                    result.push({

                        tag: element.tagName.toLowerCase(),

                        selector: makeSelector(element),

                        text: directText,

                        style: {

                            display:
                                style.display,

                            visibility:
                                style.visibility,

                            opacity:
                                style.opacity,

                            color:
                                style.color,

                            backgroundColor:
                                style.backgroundColor,

                            fontSize:
                                style.fontSize,

                            position:
                                style.position
                        },

                        rect: {

                            x: rect.x,
                            y: rect.y,

                            width:
                                rect.width,

                            height:
                                rect.height
                        },

                        inViewport: inViewport,

                        hiddenAttribute:
                            element.hidden,

                        ariaHidden:
                            element.getAttribute("aria-hidden")
                    });
                }


                return result;
            }
            """
        )

        result = {
            "title": title,
            "url": page.url,
            "elements": elements
        }

        await browser.close()

        return result