"""Keyword/page caching and persistence for Djinni searches."""

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic

from job_bot.models import VacancyPage, normalize_keyword
from job_bot.sources.djinni import DjinniClient
from job_bot.sources.djinni_categories import normalize_categories
from job_bot.storage import VacancyStorage

logger = logging.getLogger(__name__)
CACHE_SECONDS = 300
MAX_CACHE_PAGES = 128


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    page: VacancyPage
    expires_at: float


class JobSearchService:
    """Cache by keyword and page without storing user identities or messages."""

    def __init__(self, source: DjinniClient, storage: VacancyStorage) -> None:
        self._source = source
        self._storage = storage
        self._lock = asyncio.Lock()
        self._cache: OrderedDict[
            tuple[str | None, tuple[str, ...], int], _CacheEntry
        ] = OrderedDict()

    async def search(
        self,
        keyword: str | None = None,
        page: int = 1,
        *,
        categories: tuple[str, ...] = (),
    ) -> VacancyPage:
        """Cache remote matches, or all listings when no filters are selected."""
        keyword = normalize_keyword(keyword) if keyword is not None else None
        if page < 1:
            raise ValueError("Search page must be positive.")
        categories = normalize_categories(categories)
        key = (keyword.casefold() if keyword is not None else None, categories, page)
        async with self._lock:
            now = monotonic()
            for expired in [
                key for key, entry in self._cache.items() if entry.expires_at <= now
            ]:
                del self._cache[expired]
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                logger.info(
                    "Using cached Djinni results page=%d matches=%d.",
                    page,
                    len(cached.page.vacancies),
                )
                return cached.page
            result = await self._source.search(keyword, page, categories=categories)
            saved = await self._storage.save(list(result.vacancies))
            remote_page = VacancyPage(
                tuple(
                    v
                    for v in saved
                    if (keyword is None and not categories) or v.remote is True
                ),
                result.next_page,
            )
            self._cache[key] = _CacheEntry(remote_page, monotonic() + CACHE_SECONDS)
            while len(self._cache) > MAX_CACHE_PAGES:
                self._cache.popitem(last=False)
            return remote_page

    async def aclose(self) -> None:
        """Release the source's reusable HTTP client."""
        await self._source.aclose()
