import unittest

from autotune import _candidate_workers, _choose_result


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

    def test_candidate_workers_allow_all_on_normal_pc(self):
        self.assertEqual(
            _candidate_workers(
                {
                    "cpu_count": 16,
                    "memory_total_mb": 16384,
                }
            ),
            [4, 6, 8],
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


if __name__ == "__main__":
    unittest.main()
