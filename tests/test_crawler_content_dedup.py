import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import crawler_parallel
from crawler import _url_pattern
from crawler_parallel import _canonicalize_pipeline_url, crawl_site


def _respond(handler, body):
    payload = body.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


class ContentDedupHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/same-index.html":
            _respond(
                self,
                """<html><body>
                <a href='/board.php?bo_table=free2&page=1&sst=name'>one</a>
                <a href='/board.php?bo_table=free2&page=2&sst=date'>two</a>
                <a href='/board.php?bo_table=free2&page=3&sst=hit'>three</a>
                </body></html>""",
            )
            return

        if parsed.path == "/board.php":
            _respond(
                self,
                "<html><head><title>Board</title></head>"
                "<body><main>UNCHANGED BOARD CONTENT</main></body></html>",
            )
            return

        if parsed.path == "/different-index.html":
            _respond(
                self,
                """<html><body>
                <a href='/article.php?bo_table=free2&wr_id=245'>a</a>
                <a href='/article.php?bo_table=free2&wr_id=449'>b</a>
                </body></html>""",
            )
            return

        if parsed.path == "/article.php":
            article_id = query.get("wr_id", [""])[0]
            _respond(
                self,
                "<html><head><title>Article</title></head>"
                f"<body><main>ARTICLE {article_id}</main></body></html>",
            )
            return

        if parsed.path == "/hidden-index.html":
            _respond(
                self,
                """<html><body>
                <a href='/hidden.php?id=1'>a</a>
                <a href='/hidden.php?id=2'>b</a>
                </body></html>""",
            )
            return

        if parsed.path == "/hidden.php":
            item_id = query.get("id", [""])[0]
            _respond(
                self,
                "<html><head><title>Hidden</title></head>"
                "<body><main>SAME VISIBLE CONTENT</main>"
                f"<div hidden>HIDDEN PAYLOAD {item_id}</div></body></html>",
            )
            return

        _respond(self, "<html><body>missing</body></html>")


async def _noop(*args, **kwargs):
    return None


async def _fast_scan(page):
    links = await crawler_parallel._collect_links(page)
    pass_names = [
        "desktop-initial",
        "desktop-settled",
        "desktop-scrolled",
        "mobile-settled",
        "mobile-scrolled",
    ]
    content_states = [
        await crawler_parallel._capture_dom_state_digest(page, name)
        for name in pass_names
    ]
    return {
        "title": await page.title(),
        "url": page.url,
        "elements": [],
        "frame_count": 1,
        "unique_element_count": 0,
        "observation_count": 0,
        "scan_pass_count": 5,
        "scan_passes": pass_names,
        "content_states": content_states,
        "timings": {},
        "links": links,
    }


class CrawlerContentDedupTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            ContentDedupHandler,
        )
        cls.thread = threading.Thread(
            target=cls.server.serve_forever,
            daemon=True,
        )
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    async def _crawl(self, path):
        with (
            patch.object(
                crawler_parallel,
                "_scan_loaded_page_multi",
                new=_fast_scan,
            ),
            patch.object(
                crawler_parallel,
                "_wait_for_dom_quiet",
                new=_noop,
            ),
            patch.object(
                crawler_parallel,
                "_auto_scroll",
                new=_noop,
            ),
        ):
            return await crawl_site(
                self.base_url + path,
                max_pages=20,
                max_seconds=15,
                pattern_priority_samples=1,
                worker_count=3,
                discovery_worker_count=0,
            )

    def test_query_order_has_one_canonical_url(self):
        first = _canonicalize_pipeline_url(
            "https://example.test/board.php?page=9&sst=wr_hit&wr_id=245"
        )
        second = _canonicalize_pipeline_url(
            "https://example.test/board.php?wr_id=245&sst=wr_hit&page=9"
        )
        self.assertEqual(first, second)

    def test_meaningful_query_values_are_not_merged_at_url_level(self):
        first = _canonicalize_pipeline_url(
            "https://example.test/board.php?bo_table=free2&wr_id=245"
        )
        second = _canonicalize_pipeline_url(
            "https://example.test/board.php?bo_table=free2&wr_id=449"
        )
        self.assertNotEqual(first, second)
        self.assertEqual(_url_pattern(first), _url_pattern(second))

    async def test_identical_content_with_sort_queries_is_skipped(self):
        result = await self._crawl("/same-index.html")

        board_pages = [
            page for page in result["pages"]
            if urlsplit(page["url"]).path == "/board.php"
        ]
        self.assertEqual(len(board_pages), 1)
        self.assertEqual(result["content_duplicate_skip_count"], 2)
        self.assertEqual(result["page_count"], 2)

    async def test_same_pattern_with_different_body_is_fully_scanned(self):
        result = await self._crawl("/different-index.html")

        article_pages = [
            page for page in result["pages"]
            if urlsplit(page["url"]).path == "/article.php"
        ]
        self.assertEqual(len(article_pages), 2)
        self.assertEqual(result["content_duplicate_skip_count"], 0)

    async def test_hidden_dom_difference_is_never_deduplicated(self):
        result = await self._crawl("/hidden-index.html")

        hidden_pages = [
            page for page in result["pages"]
            if urlsplit(page["url"]).path == "/hidden.php"
        ]
        self.assertEqual(len(hidden_pages), 2)
        self.assertEqual(result["content_duplicate_skip_count"], 0)


if __name__ == "__main__":
    unittest.main()
