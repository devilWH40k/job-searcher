"""Search ordering, caching, persistence, and shared concurrent searches."""

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from job_bot.models import VacancyPage
from job_bot.services import job_search
from job_bot.services.job_search import JobSearchService
from job_bot.sources.djinni import parse_search_results
from job_bot.sources.http_client import SourceFetchError
from job_bot.storage import VacancyStorage


def test_six_remote_matches_preserve_order_and_share_cache(
    djinni_html: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = MagicMock()
    source.search = AsyncMock(
        return_value=VacancyPage(tuple(parse_search_results(djinni_html)))
    )
    source.aclose = AsyncMock()
    storage_path = tmp_path / "jobs.sqlite3"
    service = JobSearchService(source, VacancyStorage(storage_path))
    clock = [0.0]
    monkeypatch.setattr(job_search, "monotonic", lambda: clock[0])

    async def scenario() -> None:
        async with asyncio.TaskGroup() as group:
            requests = [group.create_task(service.search("frontend")) for _ in range(3)]
        expected = [
            "848243",
            "849054",
            "855646",
            "855321",
            "855021",
            "853017",
            "847547",
            "826244",
            "846091",
        ]
        for task in requests:
            assert [item.source_id for item in task.result().vacancies] == expected
        source.search.assert_awaited_once()
        assert len((await service.search("frontend")).vacancies) == 9
        clock[0] = 301
        assert len((await service.search("frontend")).vacancies) == 9
        assert source.search.await_count == 2
        await service.aclose()
        source.aclose.assert_awaited_once()

    asyncio.run(scenario())
    with closing(sqlite3.connect(storage_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM vacancies").fetchone() == (9,)


def test_failed_search_is_not_cached(djinni_html: str, tmp_path: Path) -> None:
    source = MagicMock()
    source.search = AsyncMock(
        side_effect=[
            SourceFetchError("offline"),
            VacancyPage(tuple(parse_search_results(djinni_html))),
        ]
    )
    service = JobSearchService(source, VacancyStorage(tmp_path / "jobs.sqlite3"))

    async def scenario() -> None:
        with pytest.raises(SourceFetchError):
            await service.search("frontend")
        assert len((await service.search("frontend")).vacancies) == 9

    asyncio.run(scenario())


def test_empty_results_are_cached(tmp_path: Path) -> None:
    source = MagicMock()
    source.search = AsyncMock(return_value=VacancyPage(()))
    service = JobSearchService(source, VacancyStorage(tmp_path / "jobs.sqlite3"))

    async def scenario() -> None:
        assert (await service.search("frontend")).vacancies == ()
        assert (await service.search("frontend")).vacancies == ()

    asyncio.run(scenario())
    source.search.assert_awaited_once()
