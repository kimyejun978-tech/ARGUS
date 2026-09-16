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
from fast_discovery import (
    extract_html_links,
    extract_robots_sitemaps,
    extract_sitemap_entries,
    standard_discovery_resources,
)


async def crawl_site(
    entry_url,
    max_pages=10000,
    max_seconds=1620,
    pattern_priority_samples=2,
    worker_count=4,
    discovery_worker_count=8,
):
    """
    HTTP 고속 discovery와 Playwright 정밀 검사를 동시에 수행한다.

    정확도 우선 원칙:
    - HTTP discovery는 브라우저 검사를 대체하지 않는다.
    - 발견한 모든 고유 HTML URL은 시간이 허용되는 한 Playwright 5-pass 검사를 받는다.
    - URL 패턴은 우선순위에만 사용하고 페이지를 생략하지 않는다.
    - robots/sitemap은 URL을 더 빨리 찾기 위한 보조 경로다.
    - max_seconds는 목표 시간이 아니라 30분 상한 전에 결과를 보존하기 위한 watchdog이다.
    """

    canonical_entry = _canonicalize_url(entry_url)
    entry_parsed = urlsplit(canonical_entry)
    entry_scheme = entry_parsed.scheme

    allowed_hosts = set()
    if entry_parsed.hostname:
        allowed_hosts.add(entry_parsed.hostname.lower())

    worker_count = max(1, int(worker_count))
    discovery_worker_count = max(0, int(discovery_worker_count))

    # file:// 테스트에서는 APIRequestContext discovery를 사용하지 않는다.
    if entry_scheme == "file":
        discovery_worker_count = 0

    browser_queue = asyncio.PriorityQueue()
    discovery_queue = asyncio.Queue()
    sequence = itertools.count()

    browser_queued = set()
    browser_visited = set()
    discovery_queued = set()
    discovery_visited = set()
    known_page_urls = set()

    scanned_urls = set()
    scanning_urls = set()
    scheduled_patterns = Counter()

    pages = []
    errors = []

    state_lock = asyncio.Lock()
    stop_event = asyncio.Event()

    start_timer = time.perf_counter()

    active_browser_workers = 0
    active_discovery_workers = 0

    claimed_count = 0
    time_limit_reached = False
    page_limit_reached = False
    interrupted_count = 0

    discovery_fetch_count = 0
    discovery_html_count = 0
    discovery_robots_count = 0
    discovery_sitemap_count = 0
    discovery_error_count = 0

    def time_remaining():
        if max_seconds is None:
            return None
        return max_seconds - (time.perf_counter() - start_timer)

    async def add_allowed_host_from_entry(url):
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()

        if host:
            async with state_lock:
                allowed_hosts.add(host)

    async def schedule_discovery(kind, url):
        """HTTP discovery 전용 자원을 중복 없이 큐에 넣는다."""

        if discovery_worker_count <= 0:
            return False

        candidate = _canonicalize_url(url)

        if kind == "page":
            if not _is_supported_page_url(candidate):
                return False
        elif kind not in {"robots", "sitemap"}:
            return False

        if not _is_same_site(candidate, allowed_hosts, entry_scheme):
            return False

        key = (kind, candidate)

        async with state_lock:
            if stop_event.is_set():
                return False

            if key in discovery_visited or key in discovery_queued:
                return False

            discovery_queued.add(key)
            discovery_queue.put_nowait(key)
            return True

    async def schedule_page(url):
        """
        한 URL을 브라우저 정밀검사 큐와 HTTP discovery 큐에 동시에 넣는다.
        HTTP discovery는 링크를 앞서 찾기 위한 경량 경로일 뿐 브라우저 검사는 생략하지 않는다.
        """

        candidate = _canonicalize_url(url)

        if not _is_supported_page_url(candidate):
            return False

        if not _is_same_site(candidate, allowed_hosts, entry_scheme):
            return False

        browser_added = False

        async with state_lock:
            known_page_urls.add(candidate)

            if (
                not stop_event.is_set()
                and candidate not in browser_visited
                and candidate not in browser_queued
            ):
                pattern = _url_pattern(candidate)
                priority = (
                    0
                    if scheduled_patterns[pattern] < pattern_priority_samples
                    else 1
                )
                scheduled_patterns[pattern] += 1

                browser_queued.add(candidate)
                browser_queue.put_nowait(
                    (priority, next(sequence), candidate)
                )
                browser_added = True

        # lock 밖에서 별도 discovery 큐를 예약한다.
        await schedule_discovery("page", candidate)
        return browser_added

    async def schedule_standard_resources(url):
        for kind, resource_url in standard_discovery_resources(url):
            await schedule_discovery(kind, resource_url)

    async def queues_are_finished():
        async with state_lock:
            return (
                browser_queue.empty()
                and discovery_queue.empty()
                and active_browser_workers == 0
                and active_discovery_workers == 0
            )

    await schedule_page(canonical_entry)
    await schedule_standard_resources(canonical_entry)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )

        request_context = context.request

        browser_pages = [
            await context.new_page()
            for _ in range(worker_count)
        ]

        async def discovery_worker(worker_id):
            nonlocal active_discovery_workers
            nonlocal discovery_fetch_count
            nonlocal discovery_html_count
            nonlocal discovery_robots_count
            nonlocal discovery_sitemap_count
            nonlocal discovery_error_count
            nonlocal time_limit_reached

            while True:
                if stop_event.is_set():
                    return

                remaining = time_remaining()
                if remaining is not None and remaining <= 0:
                    time_limit_reached = True
                    stop_event.set()
                    return

                try:
                    kind, requested_url = await asyncio.wait_for(
                        discovery_queue.get(),
                        timeout=0.15,
                    )
                except TimeoutError:
                    if await queues_are_finished():
                        return
                    continue

                claimed = False
                response = None

                try:
                    key = (kind, requested_url)

                    async with state_lock:
                        discovery_queued.discard(key)

                        if key in discovery_visited:
                            continue

                        discovery_visited.add(key)
                        active_discovery_workers += 1
                        claimed = True

                    request_timeout_ms = 10000
                    remaining = time_remaining()

                    if remaining is not None:
                        if remaining <= 0:
                            time_limit_reached = True
                            stop_event.set()
                            continue

                        request_timeout_ms = int(
                            max(750, min(10000, remaining * 1000))
                        )

                    try:
                        response = await request_context.get(
                            requested_url,
                            timeout=request_timeout_ms,
                            fail_on_status_code=False,
                        )
                    except Exception:
                        discovery_error_count += 1
                        continue

                    discovery_fetch_count += 1
                    final_url = _canonicalize_url(response.url)

                    # 진입 URL 리다이렉트(예: example.go.kr -> www.example.go.kr)를
                    # 동일 평가 사이트 범위로 인정한다.
                    if requested_url == canonical_entry:
                        await add_allowed_host_from_entry(final_url)
                        await schedule_standard_resources(final_url)

                    if not _is_same_site(
                        final_url,
                        allowed_hosts,
                        entry_scheme,
                    ):
                        continue

                    status = response.status
                    if status >= 400:
                        continue

                    try:
                        text = await response.text()
                    except Exception:
                        continue

                    if kind == "robots":
                        discovery_robots_count += 1

                        for sitemap_url in extract_robots_sitemaps(
                            text,
                            final_url,
                        ):
                            await schedule_discovery(
                                "sitemap",
                                sitemap_url,
                            )

                        continue

                    if kind == "sitemap":
                        discovery_sitemap_count += 1
                        page_urls, sitemap_urls = extract_sitemap_entries(
                            text,
                            final_url,
                        )

                        for sitemap_url in sitemap_urls:
                            await schedule_discovery(
                                "sitemap",
                                sitemap_url,
                            )

                        for page_url in page_urls:
                            await schedule_page(page_url)

                        continue

                    content_type = (
                        response.headers.get("content-type", "")
                        .split(";", 1)[0]
                        .strip()
                        .lower()
                    )

                    if content_type and content_type not in {
                        "text/html",
                        "application/xhtml+xml",
                    }:
                        continue

                    discovery_html_count += 1

                    for link in extract_html_links(text, final_url):
                        await schedule_page(link)

                finally:
                    if response is not None:
                        try:
                            await response.dispose()
                        except Exception:
                            pass

                    if claimed:
                        async with state_lock:
                            active_discovery_workers -= 1

                    discovery_queue.task_done()

        async def browser_worker(worker_id, page):
            nonlocal active_browser_workers
            nonlocal claimed_count
            nonlocal time_limit_reached
            nonlocal page_limit_reached
            nonlocal interrupted_count

            while True:
                if stop_event.is_set():
                    return

                remaining = time_remaining()
                if remaining is not None and remaining <= 0:
                    time_limit_reached = True
                    stop_event.set()
                    return

                try:
                    _, _, requested_url = await asyncio.wait_for(
                        browser_queue.get(),
                        timeout=0.15,
                    )
                except TimeoutError:
                    if await queues_are_finished():
                        return
                    continue

                claimed = False
                reserved_final_url = None

                try:
                    async with state_lock:
                        browser_queued.discard(requested_url)

                        if requested_url in browser_visited:
                            continue

                        if claimed_count >= max_pages:
                            page_limit_reached = True
                            stop_event.set()
                            continue

                        browser_visited.add(requested_url)
                        claimed_count += 1
                        active_browser_workers += 1
                        claimed = True
                        ordinal = claimed_count

                    print(
                        f"[ARGUS][W{worker_id}] 페이지 정밀 탐색 "
                        f"{ordinal}: {requested_url}"
                    )

                    timeout_ms = 30000
                    remaining = time_remaining()

                    if remaining is not None:
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

                    if (
                        requested_url == canonical_entry
                        and final_parsed.hostname
                    ):
                        await add_allowed_host_from_entry(final_url)
                        await schedule_standard_resources(final_url)

                    if not _is_same_site(
                        final_url,
                        allowed_hosts,
                        entry_scheme,
                    ):
                        continue

                    # 서로 다른 URL이 같은 최종 URL로 리다이렉트돼도
                    # 5-pass 정밀검사를 한 번만 수행한다.
                    async with state_lock:
                        known_page_urls.add(final_url)

                        if (
                            final_url in scanned_urls
                            or final_url in scanning_urls
                        ):
                            continue

                        scanning_urls.add(final_url)
                        reserved_final_url = final_url

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
                        scanning_urls.discard(final_url)
                        reserved_final_url = None

                        if final_url not in scanned_urls:
                            scanned_urls.add(final_url)
                            pages.append(page_result)

                        completed_count = len(pages)

                    # JS/DOM에서만 나타난 링크도 동일 파이프라인으로 넣는다.
                    for link in sorted(links):
                        await schedule_page(link)

                    print(
                        f"[ARGUS][W{worker_id}] 완료 "
                        f"{completed_count}: {final_url}"
                    )

                finally:
                    if reserved_final_url is not None:
                        async with state_lock:
                            scanning_urls.discard(reserved_final_url)

                    if claimed:
                        async with state_lock:
                            active_browser_workers -= 1

                    browser_queue.task_done()

        discovery_tasks = [
            asyncio.create_task(
                discovery_worker(index + 1),
                name=f"argus-discovery-{index + 1}",
            )
            for index in range(discovery_worker_count)
        ]

        browser_tasks = [
            asyncio.create_task(
                browser_worker(index + 1, page),
                name=f"argus-browser-{index + 1}",
            )
            for index, page in enumerate(browser_pages)
        ]

        all_tasks = discovery_tasks + browser_tasks

        try:
            if max_seconds is None:
                await asyncio.gather(*all_tasks)
            else:
                remaining = time_remaining()

                if remaining is None or remaining <= 0:
                    time_limit_reached = True
                    stop_event.set()
                else:
                    await asyncio.wait_for(
                        asyncio.gather(*all_tasks),
                        timeout=remaining,
                    )

        except TimeoutError:
            time_limit_reached = True
            stop_event.set()

        finally:
            if stop_event.is_set():
                for task in all_tasks:
                    if not task.done():
                        task.cancel()

            await asyncio.gather(
                *all_tasks,
                return_exceptions=True,
            )

            await context.close()
            await browser.close()

    pending_count = browser_queue.qsize() + interrupted_count
    discovery_pending_count = discovery_queue.qsize()

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
        "discovery_worker_count": discovery_worker_count,
        "known_page_count": len(known_page_urls),
        "claimed_count": claimed_count,
        "discovery_fetch_count": discovery_fetch_count,
        "discovery_html_count": discovery_html_count,
        "discovery_robots_count": discovery_robots_count,
        "discovery_sitemap_count": discovery_sitemap_count,
        "discovery_error_count": discovery_error_count,
        "limit_reached": (
            page_limit_reached or time_limit_reached
        ),
        "page_limit_reached": page_limit_reached,
        "time_limit_reached": time_limit_reached,
        "pending_count": pending_count,
        "discovery_pending_count": discovery_pending_count,
        "errors": errors,
    }
