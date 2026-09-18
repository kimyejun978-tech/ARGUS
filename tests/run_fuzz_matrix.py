import argparse
import asyncio
import io
import statistics
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from run_fuzz_benchmark import run


def pct(value):
    return f"{value * 100:.1f}%"


def seed_sequence(base_seed, runs, step):
    return [base_seed + index * step for index in range(runs)]


async def run_matrix(
    base_seed,
    runs,
    step,
    per_technique,
    max_seconds,
    show_failures,
    workers=4,
    discovery_workers=8,
):
    seeds = seed_sequence(base_seed, runs, step)
    results = []
    started = time.perf_counter()

    print("===================================")
    print("     ARGUS MULTI-SEED FUZZ MATRIX")
    print("===================================")
    print("runs               :", runs)
    print("base seed          :", base_seed)
    print("seed step          :", step)
    print("per technique      :", per_technique)
    print("generated target   :", runs * per_technique * 4)
    print("browser workers    :", workers)
    print("discovery workers  :", discovery_workers)
    print()

    for index, seed in enumerate(seeds, start=1):
        capture = io.StringIO()
        try:
            with redirect_stdout(capture), redirect_stderr(capture):
                result = await run(
                    seed,
                    per_technique,
                    max_seconds,
                    workers=workers,
                    discovery_workers=discovery_workers,
                )
        except Exception as exc:
            print(f"[{index:02d}/{runs:02d}] seed={seed} ERROR {type(exc).__name__}: {exc}")
            if show_failures:
                detail = capture.getvalue().strip()
                if detail:
                    print(detail)
            results.append({
                "seed": seed,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        result = dict(result)
        result["seed"] = seed
        results.append(result)

        passed = (
            result["page_count"] >= result["min_pages"]
            and result["detector_recall"] >= 1.0
            and result["precision"] >= 0.98
            and result["recall"] >= 1.0
            and result["control_leakage"] == 0
        )

        status = "PASS" if passed else "FAIL"
        print(
            f"[{index:02d}/{runs:02d}] seed={seed} {status} | "
            f"det={pct(result['detector_recall'])} "
            f"req={pct(result['recall'])} "
            f"prec={pct(result['precision'])} "
            f"probe={pct(result['probe_retention'])} "
            f"ctrl={result['control_leakage']}/{result['control_total']} "
            f"time={result['elapsed']:.2f}s"
        )

        if not passed and show_failures:
            detail = capture.getvalue().strip()
            if detail:
                print("\n--- failed seed detail ---")
                print(detail)
                print("--- end detail ---\n")

    elapsed = time.perf_counter() - started
    completed = [r for r in results if "error" not in r]
    failures = [
        r for r in completed
        if not (
            r["page_count"] >= r["min_pages"]
            and r["detector_recall"] >= 1.0
            and r["precision"] >= 0.98
            and r["recall"] >= 1.0
            and r["control_leakage"] == 0
        )
    ]
    errors = [r for r in results if "error" in r]

    print()
    print("==============================")
    print("          MATRIX SUMMARY")
    print("==============================")
    print("완료 run          :", len(completed), "/", runs)
    print("실패 run          :", len(failures))
    print("실행 오류         :", len(errors))

    if completed:
        total_generated = sum(r["generated_cases"] for r in completed)
        total_required = sum(r["required_total"] for r in completed)
        total_required_hits = sum(r["required_hits"] for r in completed)
        total_controls = sum(r["control_total"] for r in completed)
        total_control_leaks = sum(r["control_leakage"] for r in completed)
        total_fp = sum(r["unexpected_fp"] for r in completed)
        total_probe = sum(r["probe_total"] for r in completed)
        total_probe_hits = sum(r["probe_hits"] for r in completed)
        times = [r["elapsed"] for r in completed]

        print("생성 case 합계    :", total_generated)
        print(
            "required retain    :",
            f"{total_required_hits}/{total_required}",
            f"({pct(total_required_hits / total_required if total_required else 0.0)})",
        )
        print("normal controls    :", f"{total_control_leaks}/{total_controls} leakage")
        print("unexpected FP      :", total_fp)
        print(
            "probe retention    :",
            f"{total_probe_hits}/{total_probe}",
            f"({pct(total_probe_hits / total_probe if total_probe else 0.0)})",
        )
        print("평균 run 시간      :", f"{statistics.mean(times):.2f}s")
        print("최대 run 시간      :", f"{max(times):.2f}s")
        print("총 matrix 시간     :", f"{elapsed:.2f}s")

        min_detector = min(r["detector_recall"] for r in completed)
        min_required = min(r["recall"] for r in completed)
        min_precision = min(r["precision"] for r in completed)
        print("최저 detector      :", pct(min_detector))
        print("최저 required      :", pct(min_required))
        print("최저 precision     :", pct(min_precision))

    if failures:
        print("\n[FAIL seeds]")
        for result in failures:
            print(
                " -",
                result["seed"],
                f"det={pct(result['detector_recall'])}",
                f"req={pct(result['recall'])}",
                f"prec={pct(result['precision'])}",
                f"ctrl={result['control_leakage']}",
            )

    if errors:
        print("\n[ERROR seeds]")
        for result in errors:
            print(" -", result["seed"], result["error"])

    return {
        "runs": runs,
        "completed": len(completed),
        "failures": len(failures),
        "errors": len(errors),
    }


def main():
    parser = argparse.ArgumentParser(
        description="ARGUS multi-seed mutation fuzz matrix"
    )
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument("--step", type=int, default=7919)
    parser.add_argument("--per-technique", type=int, default=24)
    parser.add_argument("--max-seconds", type=float, default=240.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--discovery-workers", type=int, default=8)
    parser.add_argument(
        "--show-failures",
        action="store_true",
        help="실패한 seed의 전체 단일-run 로그를 함께 출력",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="하나의 seed라도 내부 기준을 통과하지 못하면 exit code 1",
    )
    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs는 1 이상이어야 합니다")
    if args.per_technique < 6:
        parser.error("--per-technique은 최소 6이어야 합니다")
    if args.workers < 1:
        parser.error("--workers는 1 이상이어야 합니다")
    if args.discovery_workers < 0:
        parser.error("--discovery-workers는 0 이상이어야 합니다")

    result = asyncio.run(
        run_matrix(
            args.seed,
            args.runs,
            args.step,
            args.per_technique,
            args.max_seconds,
            args.show_failures,
            workers=args.workers,
            discovery_workers=args.discovery_workers,
        )
    )

    if args.strict and (
        result["completed"] != result["runs"]
        or result["failures"] > 0
        or result["errors"] > 0
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
