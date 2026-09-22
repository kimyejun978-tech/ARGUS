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

from crawler import DOM_SCAN_SCRIPT


AUTO_TUNE_SCHEMA = 1
AUTO_TUNE_CANDIDATES = (4, 6, 8)
AUTO_TUNE_MARGIN = 0.05
AUTO_TUNE_SAMPLE_PAGES = 16
AUTO_TUNE_ROWS = 420
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
    cpu_count = int(snapshot.get("cpu_count") or 1)
    total_mb = snapshot.get("memory_total_mb")

    max_worker = 8

    if cpu_count <= 2:
        max_worker = 4
    elif total_mb is not None and total_mb < 6144:
        max_worker = 4
    elif total_mb is not None and total_mb < 10240:
        max_worker = 6

    candidates = [
        worker
        for worker in AUTO_TUNE_CANDIDATES
        if worker <= max_worker
    ]

    return candidates or [4]


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


async def _scan_probe_page(context, html_text, semaphore):
    async with semaphore:
        page = await context.new_page()

        try:
            await page.set_content(
                html_text,
                wait_until="domcontentloaded",
                timeout=5000,
            )

            total_observations = 0

            for pass_index in range(AUTO_TUNE_PASSES):
                if pass_index < 3:
                    viewport = {"width": 1280, "height": 720}
                else:
                    viewport = {"width": 390, "height": 844}

                await page.set_viewport_size(viewport)

                if pass_index in {2, 4}:
                    await page.evaluate(
                        "window.scrollTo(0, document.body.scrollHeight)"
                    )
                else:
                    await page.evaluate("window.scrollTo(0, 0)")

                elements = await page.main_frame.evaluate(DOM_SCAN_SCRIPT)
                total_observations += len(elements)

            return {
                "ok": True,
                "observations": total_observations,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "observations": 0,
            }
        finally:
            try:
                await page.close()
            except Exception:
                pass


async def _benchmark_candidate(context, worker_count, html_text):
    semaphore = asyncio.Semaphore(worker_count)
    started = time.perf_counter()

    results = await asyncio.gather(
        *[
            _scan_probe_page(context, html_text, semaphore)
            for _ in range(AUTO_TUNE_SAMPLE_PAGES)
        ]
    )

    elapsed = max(time.perf_counter() - started, 0.001)
    errors = [item for item in results if not item.get("ok")]
    observations = sum(
        item.get("observations", 0)
        for item in results
        if item.get("ok")
    )

    return {
        "workers": worker_count,
        "elapsed_sec": round(elapsed, 4),
        "pages_per_sec": round(AUTO_TUNE_SAMPLE_PAGES / elapsed, 4),
        "errors": len(errors),
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

            # 첫 candidate에만 브라우저/JIT warm-up 비용이 몰리지 않게 한 번 예열한다.
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
