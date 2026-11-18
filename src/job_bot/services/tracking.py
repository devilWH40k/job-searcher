"""Resumable searches and durable, per-subscription vacancy deduplication."""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime

from job_bot.models import TrackedSearch, Vacancy
from job_bot.services.job_search import JobSearchService
from job_bot.sources.http_client import SourceMarkupError
from job_bot.storage import TrackingStorage

PAGES_PER_TURN = 3


class TrackingService:
    """Scan a few pages per turn, sharing the interactive cache and request limits."""

    def __init__(self, search: JobSearchService, storage: TrackingStorage) -> None:
        self.search = search
        self.storage = storage

    async def check(
        self,
        tracking: TrackedSearch,
        notify: Callable[[TrackedSearch, Vacancy], Awaitable[None]],
    ) -> None:
        """The initial full scan is a baseline; later scans enqueue unseen IDs."""
        await self._deliver(tracking, notify)
        for _ in range(PAGES_PER_TURN):
            if not await self.storage.active(tracking.id):
                return
            page = await self.search.search(
                tracking.search.keyword or None,
                tracking.next_page,
                categories=tracking.search.categories,
            )
            if page.next_page is not None and page.next_page <= tracking.next_page:
                raise SourceMarkupError("Source pagination did not advance.")
            await self.storage.record_page(
                tracking, page.vacancies, page.next_page, datetime.now(UTC)
            )
            await self._deliver(tracking, notify)
            if page.next_page is None:
                return
            tracking = replace(tracking, next_page=page.next_page)

    async def _deliver(
        self,
        tracking: TrackedSearch,
        notify: Callable[[TrackedSearch, Vacancy], Awaitable[None]],
    ) -> None:
        while vacancies := await self.storage.pending(tracking.id):
            for vacancy in vacancies:
                if not await self.storage.active(tracking.id):
                    return
                await notify(tracking, vacancy)
                await self.storage.acknowledge(tracking.id, vacancy)
