"""The fixed remote front-end demo search requested for /start."""

import asyncio
import logging
from time import monotonic

from job_bot.models import Vacancy
from job_bot.sources.djinni import DjinniClient
from job_bot.storage import VacancyStorage

logger = logging.getLogger(__name__)


class JobSearchService:
    """Share a five-minute cache and persist each successful source result."""

    def __init__(self, source: DjinniClient, storage: VacancyStorage) -> None:
        self._source = source
        self._storage = storage
        self._lock = asyncio.Lock()
        self._cache: tuple[Vacancy, ...] | None = None
        self._expires_at = 0.0

    async def search_remote_frontend(self) -> list[Vacancy]:
        """Return up to six explicit remote matches, preserving source order."""
        async with self._lock:
            if self._cache is not None and monotonic() < self._expires_at:
                logger.info(
                    "Using cached Djinni search results (%d matches).",
                    len(self._cache),
                )
                return list(self._cache)
            vacancies = await self._source.search_remote_frontend()
            saved = await self._storage.save(vacancies)
            matches = [vacancy for vacancy in saved if vacancy.remote is True][:6]
            self._cache = tuple(matches)
            self._expires_at = monotonic() + 300
            return matches

    async def aclose(self) -> None:
        """Release the source's reusable HTTP client."""
        await self._source.aclose()
