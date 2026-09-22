import asyncio
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autotune import auto_tune_workers


async def main():
    os.environ["ARGUS_RETUNE"] = "1"

    selected, info = await auto_tune_workers(4)

    print("===================================")
    print("         ARGUS AUTO-TUNE")
    print("===================================")
    print("selected workers :", selected)
    print("source           :", info.get("source"))
    print(
        "benchmark time   :",
        f"{info.get('benchmark_elapsed_sec', 0.0):.3f}s",
    )

    machine = info.get("machine") or {}
    print("logical CPU      :", machine.get("cpu_count"))
    print("total RAM MB     :", machine.get("memory_total_mb"))
    print("available RAM MB :", machine.get("memory_available_mb"))

    print()
    print("[candidate results]")
    for result in info.get("results", []):
        print(
            f" - {result.get('workers')} workers | "
            f"{result.get('elapsed_sec', 0.0):.3f}s | "
            f"{result.get('pages_per_sec', 0.0):.2f} probe pages/s | "
            f"errors={result.get('errors', 0)} | "
            f"observations={result.get('observations', 0)}"
        )

    if info.get("error"):
        print()
        print("error:", info["error"])

    if info.get("cache_path"):
        print()
        print("cache:", info["cache_path"])


if __name__ == "__main__":
    asyncio.run(main())
