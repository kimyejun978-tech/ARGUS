import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autotune import (
    _candidate_workers,
    _choose_result,
    auto_tune_workers,
)


class AutoTuneTests(unittest.TestCase):
    def test_candidate_workers_respect_small_memory(self):
        self.assertEqual(
            _candidate_workers(
                {
                    "cpu_count": 16,
                    "memory_total_mb": 4096,
                }
            ),
            [4],
        )

    def test_candidate_workers_use_six_and_eight_on_strong_pc(self):
        self.assertEqual(
            _candidate_workers(
                {
                    "cpu_count": 16,
                    "memory_total_mb": 16384,
                }
            ),
            [6, 8],
        )

    def test_candidate_workers_use_four_and_six_on_midrange_pc(self):
        self.assertEqual(
            _candidate_workers(
                {
                    "cpu_count": 8,
                    "memory_total_mb": 8192,
                }
            ),
            [4, 6],
        )

    def test_choose_fastest_when_difference_is_material(self):
        selected = _choose_result(
            [
                {
                    "workers": 4,
                    "pages_per_sec": 4.0,
                    "errors": 0,
                    "observations": 100,
                },
                {
                    "workers": 6,
                    "pages_per_sec": 5.0,
                    "errors": 0,
                    "observations": 100,
                },
                {
                    "workers": 8,
                    "pages_per_sec": 6.4,
                    "errors": 0,
                    "observations": 100,
                },
            ]
        )
        self.assertEqual(selected["workers"], 8)

    def test_choose_lower_worker_inside_five_percent_margin(self):
        selected = _choose_result(
            [
                {
                    "workers": 4,
                    "pages_per_sec": 5.8,
                    "errors": 0,
                    "observations": 100,
                },
                {
                    "workers": 6,
                    "pages_per_sec": 6.1,
                    "errors": 0,
                    "observations": 100,
                },
                {
                    "workers": 8,
                    "pages_per_sec": 6.0,
                    "errors": 0,
                    "observations": 100,
                },
            ]
        )
        self.assertEqual(selected["workers"], 4)

    def test_error_result_is_not_selected(self):
        selected = _choose_result(
            [
                {
                    "workers": 4,
                    "pages_per_sec": 4.0,
                    "errors": 0,
                    "observations": 100,
                },
                {
                    "workers": 8,
                    "pages_per_sec": 9.0,
                    "errors": 1,
                    "observations": 100,
                },
            ]
        )
        self.assertEqual(selected["workers"], 4)

    def test_cached_worker_count_skips_benchmark(self):
        cached = {
            "selected_workers": 6,
            "benchmark_elapsed_sec": 1.25,
            "results": [{"workers": 6}],
        }

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("autotune.machine_snapshot", return_value={}),
            patch("autotune._load_cache", return_value=cached),
            patch(
                "autotune.async_playwright",
                side_effect=AssertionError("benchmark must not run"),
            ),
        ):
            workers, info = asyncio.run(auto_tune_workers(4))

        self.assertEqual(workers, 6)
        self.assertEqual(info["source"], "cache")

    def test_retune_ignores_cache_and_attempts_measurement(self):
        with (
            patch.dict(os.environ, {"ARGUS_RETUNE": "1"}, clear=True),
            patch("autotune.machine_snapshot", return_value={}),
            patch(
                "autotune._load_cache",
                side_effect=AssertionError("cache must be skipped"),
            ),
            patch(
                "autotune.async_playwright",
                side_effect=RuntimeError("measurement attempted"),
            ),
        ):
            workers, info = asyncio.run(auto_tune_workers(4))

        self.assertEqual(workers, 4)
        self.assertEqual(info["source"], "fallback")
        self.assertIn("measurement attempted", info["error"])

    def test_argus_workers_overrides_cache_and_benchmark(self):
        with (
            patch.dict(os.environ, {"ARGUS_WORKERS": "7"}, clear=True),
            patch(
                "autotune.machine_snapshot",
                side_effect=AssertionError("hardware probe must not run"),
            ),
        ):
            workers, info = asyncio.run(auto_tune_workers(4))

        self.assertEqual(workers, 7)
        self.assertEqual(info["source"], "env")

    def test_corrupt_cache_safely_falls_back_after_measurement_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "worker_tuning.json"
            cache_path.write_text("{not-json", encoding="utf-8")

            with (
                patch.dict(
                    os.environ,
                    {"ARGUS_AUTOTUNE_CACHE": str(cache_path)},
                    clear=True,
                ),
                patch("autotune.machine_snapshot", return_value={}),
                patch(
                    "autotune.async_playwright",
                    side_effect=RuntimeError("browser unavailable"),
                ),
            ):
                workers, info = asyncio.run(auto_tune_workers(5))

        self.assertEqual(workers, 5)
        self.assertEqual(info["source"], "fallback")

    def test_measurement_failure_uses_existing_fallback(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("autotune.machine_snapshot", return_value={}),
            patch("autotune._load_cache", return_value=None),
            patch(
                "autotune.async_playwright",
                side_effect=RuntimeError("launch failed"),
            ),
        ):
            workers, info = asyncio.run(auto_tune_workers(6))

        self.assertEqual(workers, 6)
        self.assertEqual(info["source"], "fallback")
        self.assertEqual(info["results"], [])


if __name__ == "__main__":
    unittest.main()
