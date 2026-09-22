import asyncio
import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import time
from pathlib import Path

from playwright.async_api import async_playwright

from crawler import DOM_SCAN_SCRIPT, _scan_loaded_page_multi


AUTO_TUNE_SCHEMA = 2
AUTO_TUNE_CANDIDATES = (4, 6, 8)
AUTO_TUNE_MARGIN = 0.05
AUTO_TUNE_SAMPLE_PAGES = 8
AUTO_TUNE_ROWS = 90
AUTO_TUNE_PASSES = 5
AUTO_TUNE_CACHE_MAX_AGE_SEC = 30 * 24 * 60 * 60


def _env_truthy(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _memory_status():
    total = None
    available = None

    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)

        try:
            ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(
                ctypes.byref(status)
            )
            if ok:
                total = int(status.ullTotalPhys)
                available = int(status.ullAvailPhys)
        except Exception:
            pass

    if total is None and hasattr(os, "sysconf"):
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            total_pages = int(os.sysconf("SC_PHYS_PAGES"))
            available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
            total = page_size * total_pages
            available = page_size * available_pages
        except Exception:
            pass

    return total, available


def _playwright_version():
    try:
        return importlib.metadata.version("playwright")
    except Exception:
        return "unknown"


def machine_snapshot():
    total_memory, available_memory = _memory_status()

    return {
        "schema": AUTO_TUNE_SCHEMA,
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "cpu_count": int(os.cpu_count() or 1),
        "memory_total_mb": (
            round(total_memory / (1024 * 1024))
            if total_memory is not None
            else None
        ),
        "playwright_version": _playwright_version(),
        "python": platform.python_version(),
        "memory_available_mb": (
            round(available_memory / (1024 * 1024))
            if available_memory is not None
            else None
        ),
    }


def machine_fingerprint(snapshot=None):
    data = dict(snapshot or machine_snapshot())

    # 현재 남은 RAM은 순간 부하에 따라 달라지므로 cache fingerprint에는 넣지 않는다.
    data.pop("memory_available_mb", None)

    payload = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()[:20]


def _cache_path():
    override = os.getenv("ARGUS_AUTOTUNE_CACHE")
    if override:
        return Path(override).expanduser()

    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA", Path.home()))
        return root / "ARGUS" / "worker_tuning.json"

    xdg_cache = os.getenv("XDG_CACHE_HOME")
    if xdg_cache:
        root = Path(xdg_cache)
    else:
        root = Path.home() / ".cache"

    return root / "argus" / "worker_tuning.json"


def _candidate_workers(snapshot):
    """
    하드웨어로 불가능/비효율 후보를 먼저 줄이고, 남은 후보만 실측한다.

    강한 PC에서 4/6/8을 모두 재는 방식은 시작 시간이 길고, 순수 DOM CPU
    micro-benchmark가 실제 크롤러의 navigation/대기 병렬성을 과소평가할 수 있다.
    그래서 저사양은 4, 중간급은 4/6, 충분한 CPU/RAM은 6/8만 비교한다.
    """
    cpu_count = int(snapshot.get("cpu_count") or 1)
    total_mb = snapshot.get("memory_total_mb")

    if cpu_count <= 4:
        return [4]

    if total_mb is not None and total_mb < 6144:
        return [4]

    if cpu_count <= 8:
        return [4, 6]

    if total_mb is not None and total_mb < 12288:
        return [4, 6]

    return [6, 8]


def _benchmark_html():
    rows = []

    for index in range(AUTO_TUNE_ROWS):
        if index % 37 == 0:
            style = ' style="position:absolute;left:-9999px;top:10px"'
        elif index % 41 == 0:
            style = ' style="opacity:0"'
        elif index % 43 == 0:
            style = ' style="display:none"'
        else:
            style = ""

        rows.append(
            f'<div class="row"{style}>'
            f'<span>항목 {index:04d}</span>'
            f'<span class="value">값 {index * 13}</span>'
            "</div>"
        )

    iframe_rows = "".join(
        f"<p>iframe sample {index}</p>"
        for index in range(28)
    )
    iframe_srcdoc = iframe_rows.replace('"', "&quot;")

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body {{ font-family: Arial, sans-serif; }}
main {{ max-width: 1100px; margin: auto; position: relative; }}
.row {{ display: flex; gap: 12px; padding: 2px; }}
@media (max-width: 500px) {{
  .row:nth-child(17n) {{ position:absolute; left:-9999px; }}
}}
</style>
</head>
<body>
<main>
<h1>ARGUS Auto-Tune Probe</h1>
{''.join(rows)}
<iframe srcdoc="{iframe_srcdoc}"></iframe>
</main>
</body>
</html>"""


async def _benchmark_candidate(context, worker_count, html_text):
    """
    실제 crawler와 비슷하게 worker별 Page를 하나씩 재사용하며
    전체 5-pass(_scan_loaded_page_multi)를 수행한다.

    이전 probe는 DOM evaluate만 반복해 CPU 경합만 측정했고, 실제 크롤러에서
    병렬화 이득이 큰 DOM 안정 대기/스크롤/링크/iframe 단계를 반영하지 못했다.
    """
    queue = asyncio.Queue()
    for sample_index in range(AUTO_TUNE_SAMPLE_PAGES):
        queue.put_nowait(sample_index)

    observations = 0
    errors = 0
    observation_lock = asyncio.Lock()

    async def worker():
        nonlocal observations, errors
        page = await context.new_page()

        try:
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                try:
                    await page.set_content(
                        html_text,
                        wait_until="domcontentloaded",
                        timeout=5000,
                    )
                    result = await _scan_loaded_page_multi(page)

                    async with observation_lock:
                        observations += int(
                            result.get("observation_count", 0)
                        )
                except Exception:
                    async with observation_lock:
                        errors += 1
                finally:
                    queue.task_done()
        finally:
            try:
                await page.close()
            except Exception:
                pass

    started = time.perf_counter()
    active_workers = min(worker_count, AUTO_TUNE_SAMPLE_PAGES)
    await asyncio.gather(
        *[worker() for _ in range(active_workers)]
    )
    elapsed = max(time.perf_counter() - started, 0.001)

    return {
        "workers": worker_count,
        "elapsed_sec": round(elapsed, 4),
        "pages_per_sec": round(AUTO_TUNE_SAMPLE_PAGES / elapsed, 4),
        "errors": errors,
        "observations": observations,
    }


def _choose_result(results):
    valid = [
        item
        for item in results
        if item.get("errors", 0) == 0
        and item.get("observations", 0) > 0
    ]

    if not valid:
        return None

    fastest = max(valid, key=lambda item: item["pages_per_sec"])
    threshold = fastest["pages_per_sec"] * (1.0 - AUTO_TUNE_MARGIN)

    near_fastest = [
        item
        for item in valid
        if item["pages_per_sec"] >= threshold
    ]

    # 성능 차이가 5% 이내면 더 적은 worker를 택해 메모리 여유를 확보한다.
    return min(near_fastest, key=lambda item: item["workers"])


def _load_cache(snapshot):
    path = _cache_path()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if payload.get("schema") != AUTO_TUNE_SCHEMA:
        return None

    if payload.get("fingerprint") != machine_fingerprint(snapshot):
        return None

    created_at = payload.get("created_at_epoch")
    if not isinstance(created_at, (int, float)):
        return None

    if time.time() - created_at > AUTO_TUNE_CACHE_MAX_AGE_SEC:
        return None

    selected = payload.get("selected_workers")
    if selected not in AUTO_TUNE_CANDIDATES:
        return None

    return payload


def _save_cache(snapshot, selected, results, elapsed_sec):
    path = _cache_path()
    payload = {
        "schema": AUTO_TUNE_SCHEMA,
        "fingerprint": machine_fingerprint(snapshot),
        "created_at_epoch": time.time(),
        "selected_workers": selected,
        "benchmark_elapsed_sec": round(elapsed_sec, 4),
        "results": results,
        "machine": {
            key: value
            for key, value in snapshot.items()
            if key != "memory_available_mb"
        },
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        return None

    return str(path)


async def auto_tune_workers(fallback_workers):
    explicit = os.getenv("ARGUS_WORKERS")
    if explicit is not None:
        return max(1, int(explicit)), {
            "source": "env",
            "benchmark_elapsed_sec": 0.0,
            "results": [],
            "cache_path": None,
        }

    if not _env_truthy("ARGUS_AUTOTUNE", default=True):
        return fallback_workers, {
            "source": "disabled",
            "benchmark_elapsed_sec": 0.0,
            "results": [],
            "cache_path": None,
        }

    snapshot = machine_snapshot()

    if not _env_truthy("ARGUS_RETUNE", default=False):
        cached = _load_cache(snapshot)
        if cached is not None:
            return int(cached["selected_workers"]), {
                "source": "cache",
                "benchmark_elapsed_sec": float(
                    cached.get("benchmark_elapsed_sec", 0.0)
                ),
                "results": cached.get("results", []),
                "cache_path": str(_cache_path()),
                "machine": snapshot,
            }

    candidates = _candidate_workers(snapshot)
    html_text = _benchmark_html()
    started = time.perf_counter()

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                ignore_https_errors=True,
            )

            # 첫 candidate에만 브라우저/JIT 비용이 몰리지 않게 가벼운 DOM
            # evaluate로 엔진만 예열한다. 전체 5-pass 예열은 시작 시간을 늘린다.
            warmup = await context.new_page()
            try:
                await warmup.set_content(
                    "<html><body><p>ARGUS warmup</p></body></html>",
                    wait_until="domcontentloaded",
                    timeout=5000,
                )
                await warmup.main_frame.evaluate(DOM_SCAN_SCRIPT)
            finally:
                await warmup.close()

            results = []
            for worker_count in candidates:
                result = await _benchmark_candidate(
                    context,
                    worker_count,
                    html_text,
                )
                results.append(result)

            await context.close()
            await browser.close()
    except Exception as exc:
        return fallback_workers, {
            "source": "fallback",
            "benchmark_elapsed_sec": round(
                time.perf_counter() - started,
                4,
            ),
            "results": [],
            "error": str(exc),
            "cache_path": None,
            "machine": snapshot,
        }

    elapsed = time.perf_counter() - started
    selected_result = _choose_result(results)

    if selected_result is None:
        return fallback_workers, {
            "source": "fallback",
            "benchmark_elapsed_sec": round(elapsed, 4),
            "results": results,
            "cache_path": None,
            "machine": snapshot,
        }

    selected = int(selected_result["workers"])
    cache_path = _save_cache(
        snapshot,
        selected,
        results,
        elapsed,
    )

    return selected, {
        "source": "benchmark",
        "benchmark_elapsed_sec": round(elapsed, 4),
        "results": results,
        "cache_path": cache_path,
        "machine": snapshot,
    }
