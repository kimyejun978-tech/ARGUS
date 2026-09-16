import asyncio

from crawler import scan_page


async def main():

    print("==============================")
    print("            ARGUS")
    print("==============================")

    url = input(
        "검사할 URL을 입력하세요: "
    ).strip()

    result = await scan_page(url)


    print()
    print("[분석 완료]")

    print("페이지 제목 :", result["title"])

    print("현재 URL    :", result["url"])

    print(
        "텍스트 요소 :",
        len(result["elements"]),
        "개"
    )


    print()
    print("===== 일부 요소 =====")


    for element in result["elements"][:20]:

        print()
        print(
            "TEXT     :",
            element["text"][:80]
        )

        print(
            "SELECTOR :",
            element["selector"]
        )

        print(
            "DISPLAY  :",
            element["style"]["display"]
        )

        print(
            "OPACITY  :",
            element["style"]["opacity"]
        )

        print(
            "POSITION :",
            element["rect"]
        )

        print(
            "VIEWPORT :",
            element["inViewport"]
        )


if __name__ == "__main__":
    asyncio.run(main())