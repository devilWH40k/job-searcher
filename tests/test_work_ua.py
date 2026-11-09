"""Source parsing and bounded HTTP failures without external requests."""

import asyncio
import logging
from copy import copy
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from bs4 import BeautifulSoup

from job_bot.sources import http_client
from job_bot.sources.work_ua import (
    SEARCH_URL,
    WorkUaAccessError,
    WorkUaClient,
    WorkUaFetchError,
    WorkUaMarkupError,
    parse_search_results,
)


def test_parse_public_snapshot(work_ua_html: str) -> None:
    seen_at = datetime(2026, 11, 9, tzinfo=UTC)
    vacancies = parse_search_results(work_ua_html, seen_at=seen_at)

    assert len(vacancies) == 8
    assert vacancies[0].source_id == "8450956"
    assert vacancies[0].title == "Strong Middle, Senior Frontend Developer"
    assert vacancies[0].company == "Collaborator.pro"
    assert vacancies[0].url == "https://www.work.ua/jobs/8450956/"
    assert vacancies[0].remote is True
    assert vacancies[0].first_seen_at == seen_at
    assert vacancies[0].published_at is None  # The source omits its UTC offset.
    assert vacancies[1].salary_text == (
        "35 000 – 55 000\xa0грн · Після всіх відрахувань · по результатам співбесіди"
    )
    assert vacancies[3].salary_text is None
    assert vacancies[4].location == "Вся Україна"
    assert vacancies[4].remote is None
    assert vacancies[4].salary_text.startswith("55 000 – 125 000")


def test_missing_optional_fields_are_unknown(work_ua_html: str) -> None:
    soup = BeautifulSoup(work_ua_html, "html.parser")
    cards = soup.select(".job-link")
    for card in cards[1:]:
        card.decompose()
    for icon in cards[0].select(
        ".glyphicon-company, .glyphicon-map-marker, .glyphicon-hryvnia-fill"
    ):
        icon.parent.decompose()
    cards[0].select_one("time").decompose()

    vacancy = parse_search_results(str(soup))[0]

    assert vacancy.company is None
    assert vacancy.location is None
    assert vacancy.salary_text is None
    assert vacancy.remote is None
    assert vacancy.published_at is None


def test_duplicates_keep_first_source_order(work_ua_html: str) -> None:
    soup = BeautifulSoup(work_ua_html, "html.parser")
    soup.select_one("#pjax-jobs-list").append(copy(soup.select_one(".job-link")))

    assert len(parse_search_results(str(soup))) == 8


def test_explicit_zero_count_is_empty(work_ua_html: str) -> None:
    soup = BeautifulSoup(work_ua_html, "html.parser")
    soup.select_one("#pjax-jobs-list").clear()
    soup.select_one("h1").parent.find("span", recursive=False).string = "0 вакансій"

    assert parse_search_results(str(soup)) == []


def test_missing_cards_with_nonzero_count_is_markup_failure(work_ua_html: str) -> None:
    soup = BeautifulSoup(work_ua_html, "html.parser")
    soup.select_one("#pjax-jobs-list").clear()

    with pytest.raises(WorkUaMarkupError):
        parse_search_results(str(soup))


@pytest.mark.parametrize(
    "href",
    [
        "https://evil.example/jobs/8450956/",
        "https://[invalid/jobs/8450956/",
        "javascript:alert(1)",
        "/jobs/999/",
    ],
)
def test_untrusted_or_mismatched_links_are_rejected(
    work_ua_html: str, href: str
) -> None:
    soup = BeautifulSoup(work_ua_html, "html.parser")
    soup.select_one(".job-link h2 a")["href"] = href

    with pytest.raises(WorkUaMarkupError):
        parse_search_results(str(soup))


def test_explicit_timezone_is_converted_to_utc(work_ua_html: str) -> None:
    soup = BeautifulSoup(work_ua_html, "html.parser")
    soup.select_one("time")["datetime"] = "2026-11-05T10:16:35+02:00"

    assert parse_search_results(str(soup))[0].published_at == datetime(
        2026, 11, 5, 8, 16, 35, tzinfo=UTC
    )


def test_fetch_then_parse_is_offline(work_ua_html: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == SEARCH_URL
        return httpx.Response(
            200, text=work_ua_html, headers={"Content-Type": "text/html; charset=utf-8"}
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond), timeout=10)
        source = WorkUaClient(client)
        assert len(await source.search_remote_frontend()) == 8
        await source.aclose()
        assert client.is_closed

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [401, 403, 302])
def test_denials_and_redirects_are_not_retried(status: int) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status, headers={"Location": "https://example.test/challenge"}
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(WorkUaAccessError):
                await WorkUaClient(client).fetch_remote_frontend()

    asyncio.run(scenario())
    assert len(requests) == 1


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    clock = [0.0]

    async def sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(http_client, "monotonic", lambda: clock[0])
    monkeypatch.setattr(http_client.asyncio, "sleep", sleep)
    return clock


def test_retry_after_is_respected(work_ua_html: str, fake_clock: list[float]) -> None:
    times = []

    def respond(request: httpx.Request) -> httpx.Response:
        times.append(fake_clock[0])
        if len(times) == 1:
            return httpx.Response(429, headers={"Retry-After": "5"})
        return httpx.Response(
            200, text=work_ua_html, headers={"Content-Type": "text/html"}
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert await WorkUaClient(client).fetch_remote_frontend() == work_ua_html

    asyncio.run(scenario())
    assert times == [0, 5]


def test_long_retry_after_prevents_early_requests(fake_clock: list[float]) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            source = WorkUaClient(client)
            for _ in range(2):
                with pytest.raises(WorkUaFetchError, match="cooldown"):
                    await source.fetch_remote_frontend()

    asyncio.run(scenario())
    assert len(requests) == 1


@pytest.mark.parametrize("failure", ["network", "timeout", "server"])
def test_failures_have_three_bounded_attempts(
    failure: str, fake_clock: list[float]
) -> None:
    times = []

    def respond(request: httpx.Request) -> httpx.Response:
        times.append(fake_clock[0])
        if failure == "network":
            raise httpx.ConnectError("offline failure", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("offline timeout", request=request)
        return httpx.Response(503)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(WorkUaFetchError):
                await WorkUaClient(client).fetch_remote_frontend()

    asyncio.run(scenario())
    assert times == [0, 2, 6]


def test_http_date_retry_after() -> None:
    date = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    assert 28 <= http_client.retry_after(date) <= 30
    assert http_client.retry_after("invalid") is None


@pytest.mark.parametrize("content_type", ["text/html", "application/json"])
def test_challenge_or_wrong_content_is_not_an_empty_search(content_type: str) -> None:
    async def scenario() -> None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                200, text="Access denied", headers={"Content-Type": content_type}
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(WorkUaMarkupError):
                await WorkUaClient(client).search_remote_frontend()

    asyncio.run(scenario())


def test_response_logs_explain_denial_without_exposing_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        response = httpx.Response(
            403,
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "Server": "cloudflare",
                "CF-Ray": "0123456789abcdef-WAW",
                "CF-Mitigated": "challenge",
                "Retry-After": "5",
                "Set-Cookie": "session=cookie-secret",
                "Authorization": "Bearer header-secret",
                "Location": "https://user:password-secret@example.test/?token=query-secret",
            },
            text=(
                "<h1>Just a moment...</h1>Cloudflare: access denied. "
                "private-user@example.test 123456:token-secret "
                '<input name="secret" value="form-secret">'
            ),
        )
        transport = httpx.MockTransport(lambda _: response)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(WorkUaAccessError):
                await WorkUaClient(client).fetch_remote_frontend()

    with caplog.at_level(logging.INFO, logger="job_bot"):
        asyncio.run(scenario())

    assert "attempt=1/3 status=403 elapsed_ms=" in caplog.text
    assert "bytes=" in caplog.text
    assert "0123456789abcdef-WAW" in caplog.text
    assert "challenge" in caplog.text
    assert "browser_check" in caplog.text
    assert "access_denied" in caplog.text
    for secret in (
        "cookie-secret",
        "header-secret",
        "password-secret",
        "query-secret",
        "token-secret",
        "form-secret",
        "private-user",
    ):
        assert secret not in caplog.text


def test_response_logs_reject_arbitrary_header_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = httpx.Response(
        403,
        headers={
            "Content-Type": "private-secret",
            "Server": "private-secret",
            "CF-Ray": "private-secret",
            "CF-Mitigated": "private-secret",
            "Retry-After": "private-secret",
        },
        text="private-secret",
    )

    with caplog.at_level(logging.INFO, logger="job_bot"):
        http_client.log_response("Work.ua", response, 1, 0.25)

    assert "status=403 elapsed_ms=250" in caplog.text
    assert "headers={} body_hints=[]" in caplog.text
    assert "private-secret" not in caplog.text
