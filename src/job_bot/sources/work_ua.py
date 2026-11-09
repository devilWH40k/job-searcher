"""Offline Work.ua parser and inactive source adapter retained for existing data."""

import asyncio
import logging
import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from job_bot.models import Vacancy
from job_bot.sources.http_client import (
    PublicSearchHttp,
    SourceAccessError,
    SourceError,
    SourceFetchError,
    SourceMarkupError,
)

SEARCH_URL = "https://www.work.ua/jobs-remote-front-end/"
logger = logging.getLogger(__name__)
WorkUaError = SourceError
WorkUaAccessError = SourceAccessError
WorkUaFetchError = SourceFetchError
WorkUaMarkupError = SourceMarkupError


def _field(card: Tag, icon_class: str) -> str | None:
    icon = card.select_one(f".text-indent > .{icon_class}")
    if icon is None or icon.parent is None:
        return None
    if icon_class == "glyphicon-company":
        company = icon.parent.select_one(".strong-600")
        if company is None:
            return None
        return company.get_text(" ", strip=True) or None
    return icon.parent.get_text(" ", strip=True) or None


def parse_search_results(
    html: str, *, seen_at: datetime | None = None
) -> list[Vacancy]:
    """Parse the user-supplied Work.ua HTML structure without making requests."""
    soup = BeautifulSoup(html, "html.parser")
    results = soup.select_one("#pjax-job-list")
    listing = results.select_one("#pjax-jobs-list") if results else None
    heading = results.select_one("h1") if results else None
    if listing is None or heading is None:
        raise WorkUaMarkupError("The Work.ua results container is missing.")
    cards = listing.select(".job-link[data-id]")
    if not cards:
        count = heading.parent.find("span", recursive=False)
        if count and " ".join(count.get_text(" ", strip=True).split()) == "0 вакансій":
            return []
        raise WorkUaMarkupError("Work.ua did not provide recognizable vacancy cards.")

    observed_at = seen_at if seen_at is not None else datetime.now(UTC)
    vacancies = []
    seen_ids = set()
    for card in cards:
        anchor = card.select_one("h2 a[href]")
        if anchor is None:
            raise WorkUaMarkupError("A Work.ua vacancy has no title link.")
        href = anchor.get("href")
        if not isinstance(href, str):
            raise WorkUaMarkupError("A Work.ua vacancy link is invalid.")
        try:
            url = urljoin(SEARCH_URL, href)
            parsed_url = urlsplit(url)
        except ValueError as exc:
            raise WorkUaMarkupError("A Work.ua vacancy URL is malformed.") from exc
        match = re.fullmatch(r"/jobs/([0-9]+)/", parsed_url.path)
        title = anchor.get_text(" ", strip=True)
        if (
            parsed_url.scheme != "https"
            or parsed_url.netloc != "www.work.ua"
            or parsed_url.query
            or parsed_url.fragment
            or match is None
            or match[1] != card.get("data-id")
            or not title
        ):
            raise WorkUaMarkupError("A Work.ua vacancy identity is invalid.")
        source_id = match[1]
        if source_id in seen_ids:
            continue
        seen_ids.add(source_id)
        location = _field(card, "glyphicon-map-marker")
        published_at = None
        time_tag = card.select_one("time[datetime]")
        if time_tag is not None:
            raw_time = time_tag.get("datetime")
            if isinstance(raw_time, str):
                try:
                    timestamp = datetime.fromisoformat(raw_time)
                except ValueError:
                    pass
                else:
                    # Work.ua's supplied HTML has no UTC offset. Leave that
                    # timestamp unknown instead of inventing a timezone.
                    if timestamp.utcoffset() is not None:
                        published_at = timestamp.astimezone(UTC)
        vacancies.append(
            Vacancy(
                source="work.ua",
                source_id=source_id,
                url=url,
                title=title,
                company=_field(card, "glyphicon-company"),
                location=location,
                salary_text=_field(card, "glyphicon-hryvnia-fill"),
                remote=True if location == "Дистанційно" else None,
                published_at=published_at,
                first_seen_at=observed_at,
            )
        )
    return vacancies


class WorkUaClient:
    """Retained adapter; the bot's active source is Djinni."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._http = PublicSearchHttp(client, "Work.ua")

    async def fetch_remote_frontend(self) -> str:
        """Fetch the public search using the shared conservative transport."""
        return await self._http.get_text(SEARCH_URL)

    async def search_remote_frontend(self) -> list[Vacancy]:
        """Fetch once, then parse outside the event loop."""
        html = await self.fetch_remote_frontend()
        try:
            vacancies = await asyncio.to_thread(parse_search_results, html)
        except WorkUaMarkupError:
            logger.warning("Work.ua HTML did not match the expected results structure.")
            raise
        logger.info(
            "Work.ua parsed vacancies=%d explicit_remote=%d",
            len(vacancies),
            sum(v.remote is True for v in vacancies),
        )
        return vacancies

    async def aclose(self) -> None:
        """Close the reusable HTTP client."""
        await self._http.aclose()
