import asyncio
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from crawler_parallel import crawl_site
from detectors.homoglyph import detect_homoglyph_candidates
from detectors.jamo import detect_jamo_candidates
from detectors.offscreen import detect_offscreen_candidates
from detectors.transparent import detect_transparent_candidates
from json_exporter import export_result_json
from result_validator import validate_result_file
from verifier.contextual import verify_candidates


SITE_ROOT = Path(__file__).resolve().parent / "mock_site"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


class SyntheticSubmissionPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = partial(_QuietHandler, directory=str(SITE_ROOT))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(
            target=cls.server.serve_forever,
            daemon=True,
        )
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_local_synthetic_pipeline_exports_valid_submission(self):
        port = self.server.server_address[1]
        entry_url = f"http://127.0.0.1:{port}/benchmark/index.html"

        crawl = asyncio.run(
            crawl_site(
                entry_url,
                max_pages=20,
                max_seconds=90,
                worker_count=2,
                discovery_worker_count=2,
            )
        )

        groups = [[], [], [], []]
        for page in crawl["pages"]:
            groups[0].extend(detect_transparent_candidates(page))
            groups[1].extend(detect_offscreen_candidates(page))
            groups[2].extend(detect_jamo_candidates(page))
            groups[3].extend(detect_homoglyph_candidates(page))

        verified, _ = verify_candidates(groups, pages=crawl["pages"])

        self.assertGreater(crawl["page_count"], 0)
        self.assertGreater(sum(len(group) for group in groups), 0)
        self.assertGreater(len(verified), 0)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "result.json"
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            exported_path, exported = export_result_json(
                entry_url=crawl["entry_url"],
                started_at=now,
                finished_at=now,
                elapsed_sec=0.0,
                candidate_groups=[verified],
                output_path=output_path,
            )
            validated = validate_result_file(exported_path)

        self.assertEqual(validated, exported)
        self.assertEqual(len(validated["findings"]), len(verified))


if __name__ == "__main__":
    unittest.main()
