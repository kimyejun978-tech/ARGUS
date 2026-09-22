import asyncio
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import urlsplit

import crawler_parallel
from crawler_parallel import crawl_site
from fast_discovery import extract_sitemap_entries


def _write_response(handler, status, body=b"", headers=None):
    handler.send_response(status)
    for name, value in (headers or {}).items():
        handler.send_header(name, value)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if body:
        try:
            handler.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass


class RecoveryFixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        path = urlsplit(self.path).path

        if path == "/index.html":
            body = b"""<!doctype html><html><body>
            <p>ENTRY OK</p>
            <a href='/good.html'>good</a>
            <a href='/status-404.html'>404</a>
            <a href='/status-500.html'>500</a>
            <a href='/slow.html'>slow</a>
            <a href='/redirect.html'>redirect</a>
            <a href='/redirect-loop-a.html'>redirect loop</a>
            <a href='/empty.html'>empty</a>
            <a href='/broken-iframe.html'>broken iframe</a>
            <a href='/download'>download</a>
            <a href='/malformed.html'>malformed</a>
            <a href='/connection-reset.html'>connection failure</a>
            </body></html>"""
            _write_response(
                self,
                200,
                body,
                {"Content-Type": "text/html; charset=utf-8"},
            )
            return

        if path == "/connection-reset.html":
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            self.close_connection = True
            return

        if path == "/good.html":
            _write_response(
                self,
                200,
                b"<html><body><p>GOOD PAGE</p></body></html>",
                {"Content-Type": "text/html"},
            )
            return

        if path == "/status-404.html":
            _write_response(
                self,
                404,
                b"<html><body><p>NOT FOUND BODY</p></body></html>",
                {"Content-Type": "text/html"},
            )
            return

        if path == "/status-500.html":
            _write_response(
                self,
                500,
                b"<html><body><p>SERVER ERROR BODY</p></body></html>",
                {"Content-Type": "text/html"},
            )
            return

        if path == "/slow.html":
            time.sleep(0.15)
            _write_response(
                self,
                200,
                b"<html><body><p>SLOW PAGE</p></body></html>",
                {"Content-Type": "text/html"},
            )
            return

        if path == "/redirect.html":
            self.send_response(302)
            self.send_header("Location", "/redirect-final.html")
            self.end_headers()
            return

        if path == "/redirect-final.html":
            _write_response(
                self,
                200,
                b"<html><body><p>REDIRECT FINAL</p></body></html>",
                {"Content-Type": "text/html"},
            )
            return

        if path == "/redirect-loop-a.html":
            self.send_response(302)
            self.send_header("Location", "/redirect-loop-b.html")
            self.end_headers()
            return

        if path == "/redirect-loop-b.html":
            self.send_response(302)
            self.send_header("Location", "/redirect-loop-a.html")
            self.end_headers()
            return

        if path == "/empty.html":
            _write_response(self, 200, b"", {"Content-Type": "text/html"})
            return

        if path == "/broken-iframe.html":
            body = b"""<html><body><p>BROKEN IFRAME PARENT</p>
            <iframe src='http://127.0.0.1:1/missing-frame.html'></iframe>
            </body></html>"""
            _write_response(
                self,
                200,
                body,
                {"Content-Type": "text/html"},
            )
            return

        if path == "/download":
            _write_response(
                self,
                200,
                b"download payload",
                {
                    "Content-Type": "application/octet-stream",
                    "Content-Disposition": "attachment; filename=payload.dat",
                },
            )
            return

        if path == "/malformed.html":
            _write_response(
                self,
                200,
                b"<html><body><div><p>MALFORMED PAGE<div><span>still parsed",
                {"Content-Type": "text/html"},
            )
            return

        if path == "/robots.txt":
            _write_response(self, 500, b"robots unavailable")
            return

        if path == "/sitemap.xml":
            _write_response(
                self,
                200,
                b"<urlset><url><loc>broken",
                {"Content-Type": "application/xml"},
            )
            return

        if path == "/sitemap_index.xml":
            _write_response(self, 500, b"sitemap unavailable")
            return

        _write_response(self, 404, b"missing")


class PageCapSitemapHandler(BaseHTTPRequestHandler):
    sitemap_started = threading.Event()

    def log_message(self, format, *args):
        return

    def do_GET(self):
        path = urlsplit(self.path).path

        if path == "/index.html":
            _write_response(
                self,
                200,
                b"<html><body><p>CAP TEST</p></body></html>",
                {"Content-Type": "text/html"},
            )
            return

        if path == "/robots.txt":
            _write_response(self, 404, b"missing")
            return

        if path == "/sitemap.xml":
            type(self).sitemap_started.set()
            time.sleep(0.35)
            _write_response(
                self,
                200,
                b"<urlset></urlset>",
                {"Content-Type": "application/xml"},
            )
            return

        if path == "/sitemap_index.xml":
            _write_response(self, 404, b"missing")
            return

        _write_response(self, 404, b"missing")


class PartialNavigationHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        path = urlsplit(self.path).path

        if path in {"/robots.txt", "/sitemap.xml", "/sitemap_index.xml"}:
            _write_response(self, 404, b"missing")
            return

        if path == "/slow-parser-block.js":
            time.sleep(3.0)
            _write_response(
                self,
                200,
                b"window.partialScriptLoaded = true;",
                {"Content-Type": "application/javascript"},
            )
            return

        body = (
            b"<!doctype html><html><head><title>Partial</title></head>"
            b"<body><p>PARTIAL RECOVERY TOKEN</p>"
            b"<script src='/slow-parser-block.js'></script>"
            b"</body></html>"
        )
        _write_response(
            self,
            200,
            body,
            {"Content-Type": "text/html"},
        )


class _ServerTestCase(unittest.TestCase):
    handler_class = None

    def setUp(self):
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            self.handler_class,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class CrawlerFailureIsolationTests(_ServerTestCase):
    handler_class = RecoveryFixtureHandler

    def test_mixed_failures_do_not_abort_other_pages(self):
        result = asyncio.run(
            crawl_site(
                f"{self.origin}/index.html",
                max_pages=30,
                max_seconds=25,
                worker_count=2,
                discovery_worker_count=2,
            )
        )

        pages_by_path = {
            urlsplit(page["url"]).path: page
            for page in result["pages"]
        }
        observed_text = {
            element.get("text")
            for page in result["pages"]
            for element in page.get("elements", [])
        }

        self.assertIn("/good.html", pages_by_path)
        self.assertIn("/status-404.html", pages_by_path)
        self.assertIn("/status-500.html", pages_by_path)
        self.assertIn("/slow.html", pages_by_path)
        self.assertIn("/redirect-final.html", pages_by_path)
        self.assertIn("/empty.html", pages_by_path)
        self.assertIn("/broken-iframe.html", pages_by_path)
        self.assertIn("/malformed.html", pages_by_path)
        self.assertIn("GOOD PAGE", observed_text)
        self.assertIn("SLOW PAGE", observed_text)
        self.assertIn("REDIRECT FINAL", observed_text)
        self.assertIn("BROKEN IFRAME PARENT", observed_text)
        self.assertIn("MALFORMED PAGE", observed_text)
        self.assertGreaterEqual(result["browser_download_skip_count"], 1)
        self.assertGreaterEqual(result["discovery_fetch_count"], 3)
        self.assertFalse(result["time_limit_reached"])
        self.assertTrue(
            any("connection-reset.html" in item["url"] for item in result["errors"])
        )
        self.assertTrue(
            any("redirect-loop" in item["url"] for item in result["errors"])
        )


class CrawlerPageCapTests(_ServerTestCase):
    handler_class = PageCapSitemapHandler

    def test_page_cap_stops_inflight_sitemap_from_growing_known_queue(self):
        self.handler_class.sitemap_started.clear()
        bulk_urls = {
            f"{self.origin}/bulk-{index:05d}.html"
            for index in range(5000)
        }

        async def quick_scan(page):
            deadline = time.perf_counter() + 2.0
            while (
                not self.handler_class.sitemap_started.is_set()
                and time.perf_counter() < deadline
            ):
                await asyncio.sleep(0.01)

            return {
                "url": page.url,
                "title": "cap",
                "elements": [],
                "links": set(),
                "frame_count": 1,
                "unique_element_count": 0,
                "observation_count": 0,
                "scan_pass_count": 5,
                "scan_passes": [
                    "desktop-initial",
                    "desktop-settled",
                    "desktop-scrolled",
                    "mobile-settled",
                    "mobile-scrolled",
                ],
                "timings": {"scan_total": 0.0},
            }

        started = time.perf_counter()

        with (
            patch.object(
                crawler_parallel,
                "_scan_loaded_page_multi",
                side_effect=quick_scan,
            ),
            patch.object(
                crawler_parallel,
                "extract_sitemap_entries",
                return_value=(bulk_urls, set()),
            ),
        ):
            result = asyncio.run(
                crawl_site(
                    f"{self.origin}/index.html",
                    max_pages=1,
                    max_seconds=5,
                    worker_count=1,
                    discovery_worker_count=1,
                )
            )

        elapsed = time.perf_counter() - started

        self.assertEqual(result["page_count"], 1)
        self.assertTrue(result["page_limit_reached"])
        self.assertFalse(result["time_limit_reached"])
        self.assertEqual(result["known_page_count"], 1)
        self.assertLess(elapsed, 3.0)


class CrawlerPartialRecoveryTests(_ServerTestCase):
    handler_class = PartialNavigationHandler

    def test_timeout_partial_dom_is_scanned_with_all_five_passes(self):
        with (
            patch.object(crawler_parallel, "BROWSER_NAVIGATION_TIMEOUT_MS", 1000),
            patch.object(
                crawler_parallel,
                "BROWSER_NAVIGATION_SETTLE_TIMEOUT_MS",
                100,
            ),
            patch.object(
                crawler_parallel,
                "BROWSER_NAVIGATION_RETRY_TIMEOUT_MS",
                1000,
            ),
        ):
            result = asyncio.run(
                crawl_site(
                    f"{self.origin}/partial.html",
                    max_pages=1,
                    max_seconds=8,
                    worker_count=1,
                    discovery_worker_count=0,
                )
            )

        self.assertEqual(result["page_count"], 1)
        self.assertGreaterEqual(result["browser_timeout_retry_count"], 1)
        self.assertGreaterEqual(result["browser_partial_recovery_count"], 1)
        self.assertEqual(result["pages"][0]["scan_pass_count"], 5)
        self.assertEqual(
            result["pages"][0]["scan_passes"],
            [
                "desktop-initial",
                "desktop-settled",
                "desktop-scrolled",
                "mobile-settled",
                "mobile-scrolled",
            ],
        )
        self.assertIn(
            "PARTIAL RECOVERY TOKEN",
            {
                element.get("text")
                for element in result["pages"][0]["elements"]
            },
        )


class DiscoveryFailureParsingTests(unittest.TestCase):
    def test_malformed_sitemap_is_empty_instead_of_raising(self):
        pages, sitemaps = extract_sitemap_entries(
            "<urlset><url><loc>broken",
            "https://example.test/sitemap.xml",
        )
        self.assertEqual(pages, set())
        self.assertEqual(sitemaps, set())


if __name__ == "__main__":
    unittest.main()
