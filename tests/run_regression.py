import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_case(name, args):
    command = [sys.executable, *args]
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")

    print()
    print("=" * 72)
    print(f"[REGRESSION] {name}")
    print("=" * 72)
    print(">", " ".join(command))
    print()

    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
    )
    elapsed = time.perf_counter() - started

    return {
        "name": name,
        "returncode": result.returncode,
        "elapsed": elapsed,
        "command": command,
    }


def main():
    parser = argparse.ArgumentParser(
        description="ARGUS 통합 회귀 테스트 러너"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="브라우저 benchmark worker 수 (default: 8)",
    )
    parser.add_argument(
        "--discovery-workers",
        type=int,
        default=8,
        help="HTTP discovery worker 수 (default: 8)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="500-page scale + multi-seed fuzz matrix까지 포함",
    )
    parser.add_argument(
        "--continue-on-fail",
        action="store_true",
        help="중간 실패가 있어도 나머지 테스트를 계속 실행",
    )
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers는 1 이상이어야 합니다")
    if args.discovery_workers < 0:
        parser.error("--discovery-workers는 0 이상이어야 합니다")

    cases = [
        (
            "Unit tests",
            ["-m", "unittest", "discover", "-s", "tests"],
        ),
        (
            "Mock end-to-end",
            ["tests/run_mock_benchmark.py", "--strict"],
        ),
        (
            "Realistic public-board simulation",
            ["tests/run_realistic_benchmark.py", "--strict"],
        ),
        (
            "Adversarial open-set",
            ["tests/run_adversarial_benchmark.py", "--strict"],
        ),
        (
            "Mutation fuzz",
            [
                "tests/run_fuzz_benchmark.py",
                "--strict",
                "--workers",
                str(args.workers),
                "--discovery-workers",
                str(args.discovery_workers),
            ],
        ),
        (
            "Deterministic scale 100",
            [
                "tests/run_scale_benchmark.py",
                "--pages",
                "100",
                "--workers",
                str(args.workers),
                "--discovery-workers",
                str(args.discovery_workers),
                "--max-seconds",
                "300",
                "--strict",
            ],
        ),
    ]

    if args.full:
        cases.extend(
            [
                (
                    "Mutation fuzz matrix",
                    [
                        "tests/run_fuzz_matrix.py",
                        "--runs",
                        "5",
                        "--strict",
                        "--workers",
                        str(args.workers),
                        "--discovery-workers",
                        str(args.discovery_workers),
                    ],
                ),
                (
                    "Deterministic scale 500",
                    [
                        "tests/run_scale_benchmark.py",
                        "--pages",
                        "500",
                        "--workers",
                        str(args.workers),
                        "--discovery-workers",
                        str(args.discovery_workers),
                        "--max-seconds",
                        "900",
                        "--strict",
                    ],
                ),
            ]
        )

    print("===================================")
    print("      ARGUS REGRESSION SUITE")
    print("===================================")
    print("mode              :", "FULL" if args.full else "QUICK")
    print("browser workers   :", args.workers)
    print("discovery workers :", args.discovery_workers)
    print("test count        :", len(cases))

    suite_started = time.perf_counter()
    results = []

    for name, command in cases:
        result = _run_case(name, command)
        results.append(result)

        if result["returncode"] != 0 and not args.continue_on_fail:
            print()
            print(
                f"[REGRESSION] {name} 실패 — "
                "후속 테스트를 중단합니다."
            )
            break

    total_elapsed = time.perf_counter() - suite_started
    passed = [item for item in results if item["returncode"] == 0]
    failed = [item for item in results if item["returncode"] != 0]
    not_run = len(cases) - len(results)

    print()
    print("=" * 72)
    print("                    ARGUS REGRESSION SUMMARY")
    print("=" * 72)

    for item in results:
        status = "PASS" if item["returncode"] == 0 else "FAIL"
        print(
            f"{status:<4} | "
            f"{item['elapsed']:>8.2f}s | "
            f"{item['name']}"
        )

    if not_run:
        print(f"SKIP | {'-':>8}  | {not_run} test(s) not run")

    print("-" * 72)
    print("passed      :", len(passed))
    print("failed      :", len(failed))
    print("not run     :", not_run)
    print("total time  :", f"{total_elapsed:.2f}s")
    print(
        "final       :",
        "PASS" if not failed and not not_run else "FAIL",
    )

    if failed or not_run:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
