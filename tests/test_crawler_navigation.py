import unittest
from unittest.mock import AsyncMock

from crawler_parallel import (
    _is_download_navigation_error,
    _is_navigation_timeout_error,
    _is_transient_browser_error,
    _reset_page_after_failure,
)


class CrawlerNavigationErrorTests(unittest.TestCase):
    def test_page_goto_timeout_is_recoverable_navigation_timeout(self):
        error = RuntimeError(
            "Page.goto: Timeout 30000ms exceeded.\n"
            "Call log:\n"
            '  - navigating to "https://example.test/", '
            'waiting until "domcontentloaded"'
        )
        self.assertTrue(_is_navigation_timeout_error(error))

    def test_generic_timeout_text_is_not_misclassified(self):
        error = RuntimeError("Timeout while waiting for unrelated worker")
        self.assertFalse(_is_navigation_timeout_error(error))

    def test_download_remains_separate_from_timeout(self):
        error = RuntimeError("Page.goto: Download is starting")
        self.assertTrue(_is_download_navigation_error(error))
        self.assertFalse(_is_navigation_timeout_error(error))

    def test_existing_transient_navigation_hint_still_matches(self):
        error = RuntimeError("Page.goto: net::ERR_ABORTED")
        self.assertTrue(_is_transient_browser_error(error))

    def test_failed_page_reset_reports_failure(self):
        page = AsyncMock()
        page.goto.side_effect = RuntimeError("reset navigation failed")
        page.evaluate.side_effect = RuntimeError("window.stop failed")

        reset = __import__("asyncio").run(_reset_page_after_failure(page))

        self.assertFalse(reset)


if __name__ == "__main__":
    unittest.main()
