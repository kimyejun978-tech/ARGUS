import unittest

from crawler_parallel import (
    _is_download_navigation_error,
    _is_navigation_timeout_error,
    _is_transient_browser_error,
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


if __name__ == "__main__":
    unittest.main()
