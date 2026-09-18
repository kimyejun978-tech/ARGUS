import asyncio
import itertools
import time
from collections import Counter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.async_api import async_playwright

from crawler import (
    _canonicalize_url as _base_canonicalize_url,
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


# 브라우저/HTTP에서 일시적으로 붙는 대표적인 비콘·challenge 파라미터.
# 대회 규칙상 실제 페이지를 구분하는 일반 query 값은 유지해야 하므로
# 명확히 비콘 성격인 prefix만 제거한다.
TRANSIENT_QUERY_PREFIXES = (
    "__cf_chl_",
)

# URL 발견 경로별 우선순위. 숫자가 작을수록 먼저 정밀검사한다.
# sitemap-only URL도 버리지는 않되, 실제 페이지에서 도달 가능한 링크를 먼저 본다.
SOURCE_PRIORITY = {
    "entry": 0,
    "browser": 0,
    "http": 1,
    "sitemap": 3,
}


def _canonicalize_pipeline_url(url: str) -> str:
    """기존 canonicalize + 명백한 일시성 challenge query 제거."""

    base = _base_canonicalize_url(url)
    parsed = urlsplit(base)

    if parsed.scheme not in {"http", "https"}:
        return base

    query_items = []

    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lower_key = key.lower()

        if any(
            lower_key.startswith(prefix)
            for prefix in TRANSIENT_QUERY_PREFIXES
        ):
            continue

        query_items.append((key, value))

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(sorted(query_items), doseq=True),
            "",
        )
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
    - 실제 DOM/HTML에서 도달한 URL을 sitemap-only URL보다 먼저 검사한다.
    - URL 패턴은 우선순위에만 사용하고 페이지를 생략하지 않는다.
    - sitemap-only URL은 브라우저 큐에는 넣되 HTTP 재귀 fetch를 즉시 대량 발생시키지 않는다.
    - max_pages는 '시도 URL 수'가 아니라 실제 완료된 정밀검사 페이지 수 기준이다.
    - max_seconds는 목표 시간이 아니라 30분 상한 전에 결과를 보존하기 위한 watchdog이다.
    """

    canonical_entry = _canonicalize_pipeline_url(entry_url)
    entry_parsed = urlsplit(canonical_entry)
    entry_scheme = entry_parsed.scheme

    allowed_hosts = set()
    if entry_parsed.hostname:
        allowed_hosts.add(entry_parsed.hostname.lower())

    worker_count = max(1, int(worker_count))
    discovery_worker_count = max(0, int(discovery_worker_count))

    if entry_scheme == "file":
        discovery_worker_count = 0

    browser_queue = asyncio.PriorityQueue()
    discovery_queue = asyncio.Queue()
    sequence = itertools.count()

    browser_priority = {}
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

    attempted_count = 0
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
        if discovery_worker_count <= 0:
            return False

        candidate = _canonicalize_pipeline_url(url)

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

    async def schedule_page(url, source="http"):
        """
        정밀검사 대상 URL을 큐에 넣는다.

        이미 sitemap 저우선순위로 들어간 URL을 실제 DOM에서 다시 발견하면
        더 높은 우선순위 항목을 추가한다. 오래된 큐 항목은 worker가 무시한다.
        """

        candidate = _canonicalize_pipeline_url(url)

        if not _is_supported_page_url(candidate):
            return False

        if not _is_same_site(candidate, allowed_hosts, entry_scheme):
            return False

        source_rank = SOURCE_PRIORITY.get(source, SOURCE_PRIORITY["http"])
        browser_added = False

        async with state_lock:
            known_page_urls.add(candidate)

            if stop_event.is_set() or candidate in browser_visited:
                pass
            else:
                pattern = _url_pattern(candidate)
                existing = browser_priority.get(candidate)

                if existing is None:
                    pattern_rank = (
                        0
                        if scheduled_patterns[pattern] < pattern_priority_samples
                        else 1
                    )
                    scheduled_patterns[pattern] += 1
                else:
                    pattern_rank = existing[1]

                new_priority = (source_rank, pattern_rank)

                if existing is None or new_priority < existing:
                    browser_priority[candidate] = new_priority
                    browser_queue.put_nowait(
                        (
                            source_rank,
                            pattern_rank,
                            next(sequence),
                            candidate,
                        )
                    )
                    browser_added = True

        # sitemap이 수천 URL을 제공해도 HTTP discovery worker까지 동시에
        # 수천 fetch로 포화시키지 않는다. 브라우저 검사는 그대로 유지한다.
        if source != "sitemap":
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

    await schedule_page(canonical_entry, source="entry")
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
                    # worker가 개별적으로 "전체 종료"를 판단하면, 다른 worker가
                    # queue에서 항목을 꺼낸 직후 active counter를 올리기 전의 짧은
                    # 틈을 완료 상태로 오인할 수 있다. 종료 판단은 아래의 중앙
                    # completion monitor만 담당한다.
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
                    final_url = _canonicalize_pipeline_url(response.url)

                    if requested_url == canonical_entry:
                        await add_allowed_host_from_entry(final_url)
                        await schedule_standard_resources(final_url)

                    if not _is_same_site(
                        final_url,
                        allowed_hosts,
                        entry_scheme,
                    ):
                        continue

                    if response.status >= 400:
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
                            await schedule_discovery("sitemap", sitemap_url)
                        continue

                    if kind == "sitemap":
                        discovery_sitemap_count += 1
                        page_urls, sitemap_urls = extract_sitemap_entries(
                            text,
                            final_url,
                        )

                        for sitemap_url in sitemap_urls:
                            await schedule_discovery("sitemap", sitemap_url)

                        for page_url in page_urls:
                            await schedule_page(page_url, source="sitemap")
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
                        await schedule_page(link, source="http")

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
            nonlocal attempted_count
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
                    source_rank, pattern_rank, _, requested_url = (
                        await asyncio.wait_for(
                            browser_queue.get(),
                            timeout=0.15,
                        )
                    )
                except TimeoutError:
                    # discovery/browser 두 queue가 서로 새 작업을 추가할 수 있으므로
                    # worker 자체는 일시적인 queue 공백만 보고 종료하지 않는다.
                    # 안정된 전체 quiescence는 completion monitor가 판정한다.
                    continue

                claimed = False
                reserved_final_url = None

                try:
                    async with state_lock:
                        current_priority = browser_priority.get(requested_url)

                        # 같은 URL이 더 높은 우선순위로 재등록된 경우
                        # 오래된 큐 항목은 버린다.
                        if current_priority != (source_rank, pattern_rank):
                            continue

                        browser_priority.pop(requested_url, None)

                        if requested_url in browser_visited:
                            continue

                        browser_visited.add(requested_url)
                        attempted_count += 1
                        active_browser_workers += 1
                        claimed = True
                        ordinal = attempted_count

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

                    final_url = _canonicalize_pipeline_url(page.url)
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

                    # 렌더링된 DOM에서 실제로 보인 링크는 최우선으로 승격한다.
                    for link in sorted(links):
                        await schedule_page(link, source="browser")

                    reached_cap = False

                    async with state_lock:
                        scanning_urls.discard(final_url)
                        reserved_final_url = None

                        if final_url not in scanned_urls:
                            if max_pages is None or len(pages) < max_pages:
                                scanned_urls.add(final_url)
                                pages.append(page_result)

                        completed_count = len(pages)

                        if (
                            max_pages is not None
                            and completed_count >= max_pages
                        ):
                            page_limit_reached = True
                            reached_cap = True
                            stop_event.set()

                    print(
                        f"[ARGUS][W{worker_id}] 완료 "
                        f"{completed_count}: {final_url}"
                    )

                    if reached_cap:
                        return

                finally:
                    if reserved_final_url is not None:
                        async with state_lock:
                            scanning_urls.discard(reserved_final_url)

                    if claimed:
                        async with state_lock:
                            active_browser_workers -= 1

                    browser_queue.task_done()

        async def completion_monitor():
            """
            두 작업 queue가 모두 비고 active worker도 없는 상태가 잠깐 보였다는
            이유만으로 crawl을 끝내지 않는다.

            Queue.get() 직후 active counter 증가 전의 아주 짧은 race window가 있어
            개별 worker 종료 방식에서는 아직 처리할 항목이 있는데 worker pool이
            줄어드는 문제가 생길 수 있다. 100ms 간격으로 연속 3회 완전 유휴가
            확인될 때만 전체 종료로 확정한다.
            """

            stable_idle_rounds = 0

            while not stop_event.is_set():
                remaining = time_remaining()

                if remaining is not None and remaining <= 0:
                    nonlocal time_limit_reached
                    time_limit_reached = True
                    stop_event.set()
                    return

                if await queues_are_finished():
                    stable_idle_rounds += 1

                    if stable_idle_rounds >= 3:
                        stop_event.set()
                        return
                else:
                    stable_idle_rounds = 0

                await asyncio.sleep(0.10)

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

        monitor_task = asyncio.create_task(
            completion_monitor(),
            name="argus-completion-monitor",
        )

        all_tasks = discovery_tasks + browser_tasks + [monitor_task]

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
        "attempted_count": attempted_count,
        "claimed_count": attempted_count,
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
