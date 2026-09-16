from playwright.async_api import async_playwright


async def scan_page(url):

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        page = await browser.new_page(
            viewport={
                "width": 1280,
                "height": 720
            }
        )

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

                function makeSelector(element) {

                    if (!element) {
                        return "";
                    }

                    const parts = [];

                    let current = element;


                    while (
                        current &&
                        current.nodeType === 1
                    ) {

                        let part =
                            current.tagName.toLowerCase();


                        if (current.id) {

                            part +=
                                "#" +
                                CSS.escape(current.id);

                            parts.unshift(part);

                            break;
                        }


                        const parent =
                            current.parentElement;


                        if (parent) {

                            const sameTags =
                                Array.from(
                                    parent.children
                                ).filter(
                                    child =>
                                        child.tagName ===
                                        current.tagName
                                );


                            if (sameTags.length > 1) {

                                const index =
                                    sameTags.indexOf(
                                        current
                                    ) + 1;

                                part +=
                                    `:nth-of-type(${index})`;
                            }
                        }


                        parts.unshift(part);

                        current =
                            current.parentElement;
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


                    const match =
                        color.match(
                            /rgba\\([^,]+,[^,]+,[^,]+,\\s*([0-9.]+)\\)/
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

                        const style =
                            window.getComputedStyle(
                                current
                            );


                        const opacity =
                            Number(style.opacity);


                        if (!Number.isNaN(opacity)) {

                            effectiveOpacity *=
                                opacity;


                            if (
                                opacity === 0 &&
                                opacitySource === null
                            ) {

                                opacitySource =
                                    makeSelector(current);
                            }
                        }


                        current =
                            current.parentElement;
                    }


                    return {

                        effectiveOpacity:
                            effectiveOpacity,

                        opacitySource:
                            opacitySource
                    };
                }



                function findBackgroundColor(
                    element
                ) {

                    let current = element;


                    while (current) {

                        const style =
                            window.getComputedStyle(
                                current
                            );

                        const background =
                            style.backgroundColor;


                        if (
                            getColorAlpha(
                                background
                            ) > 0
                        ) {

                            return background;
                        }


                        current =
                            current.parentElement;
                    }


                    return null;
                }



                const result = [];

                const elements =
                    document.querySelectorAll(
                        "body *"
                    );


                for (const element of elements) {

                    const directText =
                        Array.from(
                            element.childNodes
                        )
                        .filter(
                            node =>
                                node.nodeType ===
                                Node.TEXT_NODE
                        )
                        .map(
                            node =>
                                node.textContent
                        )
                        .join(" ")
                        .trim();


                    if (!directText) {
                        continue;
                    }


                    const style =
                        window.getComputedStyle(
                            element
                        );


                    const rect =
                        element.getBoundingClientRect();


                    const effective =
                        getEffectiveInfo(
                            element
                        );


                    const backgroundColor =
                        findBackgroundColor(
                            element
                        );


                    const textColor =
                        style.color;


                    const sameColor =
                        backgroundColor !== null &&
                        textColor === backgroundColor;


                    result.push({

                        tag:
                            element.tagName
                            .toLowerCase(),

                        selector:
                            makeSelector(element),

                        text:
                            directText,

                        style: {

                            display:
                                style.display,

                            visibility:
                                style.visibility,

                            opacity:
                                Number(style.opacity),

                            color:
                                textColor,

                            backgroundColor:
                                backgroundColor,

                            fontSize:
                                style.fontSize,

                            position:
                                style.position,

                            left:
                                style.left,

                            top:
                                style.top
                        },

                        effectiveOpacity:
                            effective
                            .effectiveOpacity,

                        opacitySource:
                            effective
                            .opacitySource,

                        textColorAlpha:
                            getColorAlpha(
                                textColor
                            ),

                        sameTextBackground:
                            sameColor,

                        rect: {

                            x:
                                rect.x,

                            y:
                                rect.y,

                            width:
                                rect.width,

                            height:
                                rect.height
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
        )


        result = {

            "title":
                title,

            "url":
                page.url,

            "elements":
                elements
        }


        await browser.close()

        return result