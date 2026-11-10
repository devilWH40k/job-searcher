"""Keyword validation, real source pagination, and isolated page caches."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup

from job_bot.models import SearchInputError, VacancyPage, normalize_keyword
from job_bot.services import job_search
from job_bot.services.job_search import JobSearchService
from job_bot.sources.djinni import build_search_url, parse_search_page
from job_bot.sources.http_client import SourceMarkupError
from job_bot.storage import VacancyStorage


@pytest.mark.parametrize(
    "value", ["", "   ", "!!!", "x" * 101, "Py\u200bthon", "\ud800"]
)
def test_invalid_keywords_are_rejected(value: str) -> None:
    with pytest.raises(SearchInputError):
        normalize_keyword(value)


@pytest.mark.parametrize("value", ["C", "C++", "C#", ".NET", "QA", "розробник"])
def test_position_and_language_names_are_accepted(value: str) -> None:
    assert normalize_keyword(value) == value


def test_keyword_is_encoded_without_injecting_url_parameters() -> None:
    url = build_search_url("  C++   & Python?  ", 2)
    assert parse_qs(urlsplit(url).query) == {
        "all_keywords": ["C++ & Python?"],
        "employment": ["remote"],
        "page": ["2"],
    }


def test_saved_source_pagination_and_single_page(djinni_html: str) -> None:
    root = Path(__file__).parent / "fixtures"
    first = parse_search_page(
        (root / "djinni_python_page1.html").read_text(encoding="utf-8")
    )
    second = parse_search_page(
        (root / "djinni_python_page2.html").read_text(encoding="utf-8"), 2
    )
    assert len(first.vacancies) == 15
    assert first.next_page == 2
    assert len(second.vacancies) == 15
    assert second.next_page == 3
    assert parse_search_page(djinni_html).next_page is None


def test_changed_or_external_pagination_is_not_followed() -> None:
    html = (Path(__file__).parent / "fixtures/djinni_python_page1.html").read_text(
        encoding="utf-8"
    )
    with pytest.raises(SourceMarkupError):
        parse_search_page(html, 2)
    soup = BeautifulSoup(html, "html.parser")
    soup.select_one(".pagination a[href*='page=2']")["href"] = (
        "https://other.example/jobs/?page=2"
    )
    with pytest.raises(SourceMarkupError):
        parse_search_page(str(soup))


def test_cache_separates_keywords_and_pages_and_normalizes_spacing(
    tmp_path: Path,
) -> None:
    source = MagicMock()
    source.search = AsyncMock(return_value=VacancyPage(()))
    service = JobSearchService(source, VacancyStorage(tmp_path / "jobs.sqlite3"))

    async def scenario() -> None:
        await service.search("  Python  ")
        await service.search("python")
        await service.search("Python", 2)
        await service.search("Java")
        await service.search("Python", 2)

    asyncio.run(scenario())
    assert [call.args for call in source.search.await_args_list] == [
        ("Python", 1),
        ("Python", 2),
        ("Java", 1),
    ]


def test_cache_has_a_bounded_page_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(job_search, "MAX_CACHE_PAGES", 2)
    source = MagicMock()
    source.search = AsyncMock(return_value=VacancyPage(()))
    service = JobSearchService(source, VacancyStorage(tmp_path / "jobs.sqlite3"))

    async def scenario() -> None:
        for keyword in ("Python", "Java", "Go", "Python"):
            await service.search(keyword)

    asyncio.run(scenario())
    assert source.search.await_count == 4
