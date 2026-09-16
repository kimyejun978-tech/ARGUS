import asyncio
import itertools
import time
from collections import Counter
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from crawler import (
    _canonicalize_url,
    _is_same_site,
    _is_supported_page_url,
    _scan_loaded_page_multi,
    _url_pattern,
)


async def crawl_site(
    entry_url,
    max_pages=10000,
    max_seconds=1620,
    pattern_priority_samples=2,
    worker_count=4,
):
    """
    정밀 다중 검사를 여러 Playwright page worker로 병렬 수행한다.

    정확도 우선 원칙:
    - URL 패턴은 탐색 우선순위에만 사용하고 페이지를 생략하지 않는다.
    - 발견한 모든 고유 URL은 시간이 허용되는 한 실제 브라우저로 검사한다.
    - 각 worker는 기존 5-pass 정밀 검사(데스크톱/모바일, 초기/안정/스크롤)를 그대로 수행한다.
    - max_seconds는 목표 시간이 아니라 대회 30분 상한 전에 결과를 보존하기 위한 비상 watchdog이다.
    """

    canonical_entry = _canonicalize_url(entry_url)
    entry_parsed = urlsplit(canonical_entry)
    entry_scheme = entry_parsed.scheme

    allowed_hosts = set()
    if entry_parsed.hostname:
        allowed_hosts.add(entry_parsed.hostname.lower())

    worker_count = max(1, int(worker_count))
    priority_queue = asyncio.PriorityQueue()
    sequence = itertools.count()

    queued = set()
    visited = set()
    scanned_urls = set()
    scheduled_patterns = Counter()

    pages = []
    errors = []

    state_lock = asyncio.Lock()
    stop_event = asyncio.Event()

    start_timer = time.perf_counter()
    active_workers = 0
    claimed_count = 0
    time_limit_reached = False
    page_limit_reached = False
    interrupted_count = 0

    async def schedule_url(url):
        candidate = _canonicalize_url(url)

        if not _is_supported_page_url(candidate):
            return False

        if not _is_same_site(candidate, allowed_hosts, entry_scheme):
            return False

        async with state_lock:
            if stop_event.is_set():
                return False

            if candidate in visited or candidate in queued:
                return False

            pattern = _url_pattern(candidate)
            priority = (
                0
                if scheduled_patterns[pattern] < pattern_priority_samples
                else 1
            )
            scheduled_patterns[pattern] += 1

            queued.add(candidate)
            priority_queue.put_nowait(
                (priority, next(sequence), candidate)
            )
            return True

    await schedule_url(canonical_entry)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )

        pages_by_worker = [
            await context.new_page()
            for _ in range(worker_count)
        ]

        async def worker(worker_id, page):
            nonlocal active_workers
            nonlocal claimed_count
            nonlocal time_limit_reached
            nonlocal page_limit_reached
            nonlocal interrupted_count

            while True:
                if stop_event.is_set():
                    return

                if max_seconds is not None:
                    elapsed = time.perf_counter() - start_timer
                    if elapsed >= max_seconds:
                        time_limit_reached = True
                        stop_event.set()
                        return

                try:
                    _, _, requested_url = await asyncio.wait_for(
                        priority_queue.get(),
                        timeout=0.25,
                    )
                except TimeoutError:
                    async with state_lock:
                        crawl_finished = (
                            priority_queue.empty()
                            and active_workers == 0
                        )

                    if crawl_finished:
                        return

                    continue

                claimed = False

                try:
                    async with state_lock:
                        queued.discard(requested_url)

                        if requested_url in visited:
                            continue

                        if claimed_count >= max_pages:
                            page_limit_reached = True
                            stop_event.set()
                            continue

                        visited.add(requested_url)
                        claimed_count += 1
                        active_workers += 1
                        claimed = True
                        ordinal = claimed_count

                    print(
                        f"[ARGUS][W{worker_id}] 페이지 정밀 탐색 "
                        f"{ordinal}: {requested_url}"
                    )

                    timeout_ms = 30000

                    if max_seconds is not None:
                        remaining = max_seconds - (
                            time.perf_counter() - start_timer
                        )

                        if remaining <= 0:
                            time_limit_reached = True
                            stop_event.set()
                            continue

                        timeout_ms = int(
                            max(1000, min(30000, remaining * 1000))
                        )

                    try:
                        await page.set_viewport_size(
                            {"width": 1280, "height": 720}
                        )
                        await page.goto(
                            requested_url,
                            wait_until="domcontentloaded",
                            timeout=timeout_ms,
                        )
                    except Exception as exc:
                        async with state_lock:
                            errors.append(
                                {
                                    "url": requested_url,
                                    "error": str(exc),
                                    "worker": worker_id,
                                }
                            )
                        continue

                    final_url = _canonicalize_url(page.url)
                    final_parsed = urlsplit(final_url)

                    if requested_url == canonical_entry and final_parsed.hostname:
                        async with state_lock:
                            allowed_hosts.add(
                                final_parsed.hostname.lower()
                            )

                    if not _is_same_site(
                        final_url,
                        allowed_hosts,
                        entry_scheme,
                    ):
                        continue

                    async with state_lock:
                        already_scanned = final_url in scanned_urls

                    if already_scanned:
                        continue

                    try:
                        page_result = await _scan_loaded_page_multi(page)
                    except asyncio.CancelledError:
                        interrupted_count += 1
                        raise
                    except Exception as exc:
                        async with state_lock:
                            errors.append(
                                {
                                    "url": final_url,
                                    "error": f"multi-scan failed: {exc}",
                                    "worker": worker_id,
                                }
                            )
                        continue

                    page_result["url"] = final_url
                    links = page_result.pop("links", set())

                    async with state_lock:
                        if final_url not in scanned_urls:
                            scanned_urls.add(final_url)
                            pages.append(page_result)
                            completed_count = len(pages)
                        else:
                            completed_count = len(pages)

                    for link in sorted(links):
                        await schedule_url(link)

                    print(
                        f"[ARGUS][W{worker_id}] 완료 "
                        f"{completed_count}: {final_url}"
                    )

                finally:
                    if claimed:
                        async with state_lock:
                            active_workers -= 1

                    priority_queue.task_done()

        worker_tasks = [
            asyncio.create_task(
                worker(index + 1, page),
                name=f"argus-worker-{index + 1}",
            )
            for index, page in enumerate(pages_by_worker)
        ]

        try:
            if max_seconds is None:
                await asyncio.gather(*worker_tasks)
            else:
                remaining = max_seconds - (
                    time.perf_counter() - start_timer
                )

                if remaining <= 0:
                    time_limit_reached = True
                    stop_event.set()
                else:
                    await asyncio.wait_for(
                        asyncio.gather(*worker_tasks),
                        timeout=remaining,
                    )

        except TimeoutError:
            time_limit_reached = True
            stop_event.set()

        finally:
            if stop_event.is_set():
                for task in worker_tasks:
                    if not task.done():
                        task.cancel()

            await asyncio.gather(
                *worker_tasks,
                return_exceptions=True,
            )

            await context.close()
            await browser.close()

    pending_count = priority_queue.qsize() + interrupted_count

    if claimed_count >= max_pages and pending_count > 0:
        page_limit_reached = True

    return {
        "entry_url": canonical_entry,
        "pages": pages,
        "page_count": len(pages),
        "frame_count": sum(
            page.get("frame_count", 1)
            for page in pages
        ),
        "element_count": sum(
            page.get(
                "unique_element_count",
                len(page["elements"]),
            )
            for page in pages
        ),
        "observation_count": sum(
            page.get(
                "observation_count",
                len(page["elements"]),
            )
            for page in pages
        ),
        "scan_pass_count": sum(
            page.get("scan_pass_count", 1)
            for page in pages
        ),
        "worker_count": worker_count,
        "claimed_count": claimed_count,
        "limit_reached": (
            page_limit_reached or time_limit_reached
        ),
        "page_limit_reached": page_limit_reached,
        "time_limit_reached": time_limit_reached,
        "pending_count": pending_count,
        "errors": errors,
    }
