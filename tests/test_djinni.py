"""Public Djinni HTML parsing and robots enforcement, fully offline."""

import asyncio
from copy import copy
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from job_bot.sources import djinni, http_client
from job_bot.sources.djinni import (
    ROBOTS_URL,
    SEARCH_URL,
    DjinniClient,
    parse_search_results,
)
from job_bot.sources.http_client import SourceAccessError, SourceMarkupError


def test_parse_public_snapshot(djinni_html: str) -> None:
    seen_at = datetime(2026, 11, 9, tzinfo=UTC)
    vacancies = parse_search_results(djinni_html, seen_at=seen_at)

    assert len(vacancies) == 9
    assert [v.source_id for v in vacancies[:6]] == [
        "848243",
        "849054",
        "855646",
        "855321",
        "855021",
        "853017",
    ]
    assert vacancies[0].source == "djinni"
    assert vacancies[0].title == "Junior Frontend Developer"
    assert vacancies[0].company == "TenThousand"
    assert (
        vacancies[0].url == "https://djinni.co/jobs/848243-junior-frontend-developer/"
    )
    assert vacancies[0].location == "Тільки віддалено · Україна"
    assert vacancies[0].salary_text == "$"
    assert vacancies[0].remote is True
    assert vacancies[0].first_seen_at == seen_at
    assert vacancies[0].published_at is None


def test_missing_optional_fields_stay_unknown(djinni_html: str) -> None:
    soup = BeautifulSoup(djinni_html, "html.parser")
    cards = soup.select(".job-item")
    for card in cards[1:]:
        card.decompose()
    card = cards[0]
    card.select_one("header .small.font-weight-500").decompose()
    card.select_one("header > .col-auto:last-child > .fs-5").decompose()
    card.select_one("a.job_item__header-link").find_next_sibling("div").decompose()

    vacancy = parse_search_results(str(soup))[0]

    assert vacancy.company is None
    assert vacancy.salary_text is None
    assert vacancy.location is None
    assert vacancy.remote is None


def test_actual_empty_state_is_distinct_from_changed_markup(
    djinni_empty_html: str,
) -> None:
    assert parse_search_results(djinni_empty_html) == []
    with pytest.raises(SourceMarkupError):
        parse_search_results("<main id='jobs_main'><ul class='list-jobs'></ul></main>")
    with pytest.raises(SourceMarkupError):
        parse_search_results("<html><h1>Access denied</h1></html>")


def test_duplicate_ids_keep_first_result(djinni_html: str) -> None:
    soup = BeautifulSoup(djinni_html, "html.parser")
    soup.select_one("ul.list-jobs").append(copy(soup.select_one(".job-item")))

    assert len(parse_search_results(str(soup))) == 9


@pytest.mark.parametrize(
    "href",
    [
        "https://other.example/jobs/848243-job/",
        "/developers/848243/",
        "/jobs/999-job/",
        "javascript:alert(1)",
        "https://[invalid/jobs/848243-job/",
    ],
)
def test_external_profile_or_mismatched_links_are_rejected(
    djinni_html: str, href: str
) -> None:
    soup = BeautifulSoup(djinni_html, "html.parser")
    soup.select_one("a.job_item__header-link")["href"] = href

    with pytest.raises(SourceMarkupError):
        parse_search_results(str(soup))


@pytest.fixture
def fake_djinni_clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    clock = [0.0]

    async def sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(http_client, "monotonic", lambda: clock[0])
    monkeypatch.setattr(djinni, "monotonic", lambda: clock[0])
    monkeypatch.setattr(http_client.asyncio, "sleep", sleep)
    return clock


def test_robots_is_checked_and_cached_before_public_search(
    djinni_html: str, fake_djinni_clock: list[float]
) -> None:
    requests = []
    robots = (Path(__file__).parent / "fixtures/djinni_robots.txt").read_text(
        encoding="utf-8"
    )

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append((str(request.url), fake_djinni_clock[0]))
        if str(request.url) == ROBOTS_URL:
            return httpx.Response(
                200, text=robots, headers={"Content-Type": "text/plain"}
            )
        assert str(request.url) == SEARCH_URL
        return httpx.Response(
            200, text=djinni_html, headers={"Content-Type": "text/html"}
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        source = DjinniClient(client)
        assert len(await source.search_remote_frontend()) == 9
        assert len(await source.search_remote_frontend()) == 9
        await source.aclose()
        assert client.is_closed

    asyncio.run(scenario())
    assert requests == [(ROBOTS_URL, 0), (SEARCH_URL, 2), (SEARCH_URL, 4)]


@pytest.mark.parametrize(
    ("status", "body", "content_type"),
    [
        (200, "User-agent: *\nDisallow: /jobs/\n", "text/plain"),
        (200, "User-agent: JobSearcherBot\nDisallow: /jobs/\n", "text/plain"),
        (200, "unrecognized response", "text/plain"),
        (403, "Access denied", "text/html"),
    ],
)
def test_unverifiable_or_denied_robots_stops_before_search(
    status: int, body: str, content_type: str
) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(status, text=body, headers={"Content-Type": content_type})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(SourceAccessError):
                await DjinniClient(client).search_remote_frontend()

    asyncio.run(scenario())
    assert requests == [ROBOTS_URL]


@pytest.mark.parametrize(
    ("rule", "interval"), [("Crawl-delay: 5", 5), ("Request-rate: 1/7", 7)]
)
def test_robots_request_interval_is_honored(
    rule: str, interval: int, djinni_empty_html: str, fake_djinni_clock: list[float]
) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append((str(request.url), fake_djinni_clock[0]))
        if str(request.url) == ROBOTS_URL:
            return httpx.Response(
                200,
                text=f"User-agent: *\n{rule}\n",
                headers={"Content-Type": "text/plain"},
            )
        assert str(request.url) == SEARCH_URL
        return httpx.Response(
            200, text=djinni_empty_html, headers={"Content-Type": "text/html"}
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert await DjinniClient(client).search_remote_frontend() == []

    asyncio.run(scenario())
    assert requests == [(ROBOTS_URL, 0), (SEARCH_URL, interval)]


def test_expired_robots_policy_is_rechecked(
    djinni_empty_html: str, fake_djinni_clock: list[float]
) -> None:
    robots_count = 0
    search_count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal robots_count, search_count
        if str(request.url) == ROBOTS_URL:
            robots_count += 1
            rule = "Disallow: /jobs/" if robots_count > 1 else "Disallow: /developers"
            return httpx.Response(
                200,
                text=f"User-agent: *\n{rule}\n",
                headers={"Content-Type": "text/plain"},
            )
        assert str(request.url) == SEARCH_URL
        search_count += 1
        return httpx.Response(
            200, text=djinni_empty_html, headers={"Content-Type": "text/html"}
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            source = DjinniClient(client)
            assert await source.search_remote_frontend() == []
            fake_djinni_clock[0] = 3601
            with pytest.raises(SourceAccessError):
                await source.search_remote_frontend()

    asyncio.run(scenario())
    assert robots_count == 2
    assert search_count == 1
