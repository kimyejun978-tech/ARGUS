from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET


class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = set()

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return

        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.add(value)
                break


def extract_html_links(html, base_url):
    """원본 HTML의 <a href> 링크를 절대 URL로 빠르게 수집한다."""

    parser = _AnchorParser()

    try:
        parser.feed(html)
    except Exception:
        # 일부 깨진 HTML도 feed 중간까지 수집한 href는 사용할 수 있다.
        pass

    links = set()

    for href in parser.hrefs:
        try:
            links.add(urljoin(base_url, href))
        except Exception:
            continue

    return links


def extract_robots_sitemaps(text, base_url):
    """robots.txt의 Sitemap: 선언을 추출한다."""

    result = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line.lower().startswith("sitemap:"):
            continue

        value = line.split(":", 1)[1].strip()

        if value:
            result.add(urljoin(base_url, value))

    return result


def _local_name(tag):
    if "}" in tag:
        return tag.rsplit("}", 1)[1].lower()
    return tag.lower()


def extract_sitemap_entries(text, base_url):
    """
    sitemap urlset / sitemapindex를 파싱한다.
    반환값: (페이지 URL 집합, 하위 sitemap URL 집합)
    """

    page_urls = set()
    sitemap_urls = set()

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return page_urls, sitemap_urls

    root_name = _local_name(root.tag)

    for element in root.iter():
        if _local_name(element.tag) != "loc":
            continue

        value = (element.text or "").strip()
        if not value:
            continue

        absolute = urljoin(base_url, value)

        if root_name == "sitemapindex":
            sitemap_urls.add(absolute)
        else:
            page_urls.add(absolute)

    return page_urls, sitemap_urls


def standard_discovery_resources(entry_url):
    """
    일반적인 robots/sitemap endpoint를 반환한다.
    브라우저 탐색 대상이 아니라 URL discovery 보조 자원이다.
    """

    parsed = urlsplit(entry_url)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []

    origin = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            "",
            "",
            "",
        )
    ).rstrip("/")

    return [
        ("robots", origin + "/robots.txt"),
        ("sitemap", origin + "/sitemap.xml"),
        ("sitemap", origin + "/sitemap_index.xml"),
    ]
