"""Public Djinni job search, with a runtime robots.txt check and offline parsing."""

import asyncio
import logging
import re
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from job_bot.models import Vacancy
from job_bot.sources.http_client import (
    PublicSearchHttp,
    SourceAccessError,
    SourceMarkupError,
)

SEARCH_URL = "https://djinni.co/jobs/?all_keywords=frontend&employment=remote"
ROBOTS_URL = "https://djinni.co/robots.txt"
USER_AGENT = "JobSearcherBot/0.1 (public job search learning project)"
logger = logging.getLogger(__name__)


def parse_search_results(
    html: str, *, seen_at: datetime | None = None
) -> list[Vacancy]:
    """Read only public listing summaries; never collect candidate/contact data."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main#jobs_main")
    if main is None:
        raise SourceMarkupError("The Djinni results container is missing.")
    listing = main.select_one("ul.list-jobs")
    cards = listing.select(".job-item[id]") if listing is not None else []
    if not cards:
        empty = main.select_one("p.text-secondary")
        if (
            empty
            and empty.get_text(" ", strip=True)
            == "Немає вакансій за обраними фільтрами"
        ):
            return []
        raise SourceMarkupError(
            "Djinni returned no recognizable listing or empty state."
        )

    observed_at = seen_at if seen_at is not None else datetime.now(UTC)
    vacancies = []
    seen_ids = set()
    for card in cards:
        heading = card.select_one("h2.job-item__position")
        link = card.select_one("a.job_item__header-link[href]")
        href = link.get("href") if link is not None else None
        if heading is None or link is None or not isinstance(href, str):
            raise SourceMarkupError("A Djinni vacancy has no recognizable title link.")
        try:
            url = urljoin(SEARCH_URL, href)
            parsed = urlsplit(url)
        except ValueError as exc:
            raise SourceMarkupError("A Djinni vacancy URL is malformed.") from exc
        match = re.fullmatch(r"/jobs/([0-9]+)-[^/?#\s]+/", parsed.path)
        title = heading.get_text(" ", strip=True)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "djinni.co"
            or parsed.query
            or parsed.fragment
            or match is None
            or not title
            or card.get("id") != f"job-item-{match[1]}"
        ):
            raise SourceMarkupError("A Djinni vacancy identity is invalid.")
        source_id = match[1]
        if source_id in seen_ids:
            continue
        seen_ids.add(source_id)
        company = link.select_one("header .col .small.font-weight-500")
        salary = link.select_one("header > .col-auto:last-child > .fs-5")
        details = link.find_next_sibling("div")
        remote = None
        locations = []
        if details is not None:
            mode = details.select_one(":scope > span.text-nowrap")
            if (
                mode is not None
                and mode.get_text(" ", strip=True) == "Тільки віддалено"
            ):
                remote = True
                locations.append(mode.get_text(" ", strip=True))
            locations.extend(
                tag.get_text(" ", strip=True)
                for tag in details.select(".location-text")
            )
        vacancies.append(
            Vacancy(
                source="djinni",
                source_id=source_id,
                url=url,
                title=title,
                company=company.get_text(" ", strip=True) or None if company else None,
                location=" · ".join(locations) or None,
                salary_text=salary.get_text(" ", strip=True) or None
                if salary
                else None,
                remote=remote,
                first_seen_at=observed_at,
                # Listings show update times without an offset, not a reliably
                # timezone-aware publication timestamp. Leave published_at unknown.
            )
        )
    return vacancies


class DjinniClient:
    """Read anonymous public jobs only, stopping if robots rules deny access."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._http = PublicSearchHttp(client, "Djinni")
        self._robots_lock = asyncio.Lock()
        self._robots_expires_at = 0.0

    async def _check_robots(self) -> None:
        async with self._robots_lock:
            if monotonic() < self._robots_expires_at:
                return
            robots_text = await self._http.get_text(
                ROBOTS_URL, content_type="text/plain"
            )
            if "user-agent:" not in robots_text.lower():
                raise SourceAccessError("Djinni robots.txt could not be verified.")
            rules = RobotFileParser(ROBOTS_URL)
            rules.parse(robots_text.splitlines())
            if not rules.can_fetch(USER_AGENT, SEARCH_URL):
                logger.warning("Djinni robots.txt disallows the public search request.")
                raise SourceAccessError("Djinni robots.txt disallows this search.")
            rate = rules.request_rate(USER_AGENT)
            self._http.respect_robots_interval(
                max(
                    rules.crawl_delay(USER_AGENT) or 0,
                    rate.seconds if rate is not None else 0,
                )
            )
            self._robots_expires_at = monotonic() + 3600

    async def search_remote_frontend(self) -> list[Vacancy]:
        """Check robots, fetch one results page, and parse outside the event loop."""
        await self._check_robots()
        html = await self._http.get_text(SEARCH_URL)
        try:
            vacancies = await asyncio.to_thread(parse_search_results, html)
        except SourceMarkupError:
            logger.warning("Djinni HTML did not match the expected results structure.")
            raise
        logger.info(
            "Djinni parsed vacancies=%d explicit_remote=%d",
            len(vacancies),
            sum(v.remote is True for v in vacancies),
        )
        return vacancies

    async def aclose(self) -> None:
        """Close the anonymous source client at application shutdown."""
        await self._http.aclose()
