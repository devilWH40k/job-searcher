"""Public Djinni job search, with a runtime robots.txt check and offline parsing."""

import asyncio
import logging
import re
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from job_bot.models import Vacancy, VacancyPage, normalize_keyword
from job_bot.sources.djinni_categories import normalize_categories
from job_bot.sources.http_client import (
    PublicSearchHttp,
    SourceAccessError,
    SourceMarkupError,
)

SEARCH_URL = "https://djinni.co/jobs/?all_keywords=frontend&employment=remote"
ROBOTS_URL = "https://djinni.co/robots.txt"
USER_AGENT = "JobSearcherBot/0.1 (public job search learning project)"
logger = logging.getLogger(__name__)


def build_search_url(
    keyword: str | None = None, page: int = 1, *, categories: tuple[str, ...] = ()
) -> str:
    """Encode verified filters; an omitted keyword and categories means all jobs."""
    keyword = normalize_keyword(keyword) if keyword is not None else None
    categories = normalize_categories(categories)
    if page < 1:
        raise ValueError("Search page must be positive.")
    parameters = [("all_keywords", keyword)] if keyword is not None else []
    if keyword is not None or categories:
        parameters.append(("employment", "remote"))
    parameters.extend(("primary_keyword", key) for key in categories)
    if page > 1:
        parameters.append(("page", str(page)))
    return "https://djinni.co/jobs/" + (
        "?" + urlencode(parameters) if parameters else ""
    )


def parse_search_results(
    html: str, *, seen_at: datetime | None = None
) -> list[Vacancy]:
    """Read only public listing summaries; never collect candidate/contact data."""
    soup = BeautifulSoup(html, "html.parser")
    return _parse_results(soup, seen_at=seen_at)


def _parse_results(
    soup: BeautifulSoup, *, seen_at: datetime | None = None
) -> list[Vacancy]:
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
        views = applications = applications_period_days = None
        updated_text = None
        for span in card.select("span.text-nowrap"):
            text = " ".join(span.get_text(" ", strip=True).split())
            view_match = re.fullmatch(r"([0-9 ]{1,20}) перегляд(?:и|ів)?", text)
            application_match = re.fullmatch(
                r"([0-9 ]{1,20}) відгук(?:и|ів)?"
                r"(?: за ([0-9]{1,5}) (?:день|дні|днів))?",
                text,
            )
            if view_match:
                views = int(view_match[1].replace(" ", ""))
            elif application_match:
                applications = int(application_match[1].replace(" ", ""))
                applications_period_days = (
                    int(application_match[2]) if application_match[2] else None
                )
            elif text.startswith("оновлено ") and len(text) <= 100:
                updated_text = text
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
                views=views,
                applications=applications,
                applications_period_days=applications_period_days,
                updated_text=updated_text,
                # Listings show update times without an offset, not a reliably
                # timezone-aware publication timestamp. Leave published_at unknown.
            )
        )
    return vacancies


def parse_search_page(html: str, page: int = 1) -> VacancyPage:
    """Read cards and numbered pagination links observed in actual Djinni HTML."""
    soup = BeautifulSoup(html, "html.parser")
    vacancies = _parse_results(soup)
    pagination = soup.select_one("main#jobs_main .pagination")
    if pagination is None:
        return VacancyPage(tuple(vacancies))
    active = pagination.select_one(".page-item.active .page-link")
    if active is None or active.get_text(strip=True) != str(page):
        raise SourceMarkupError("Djinni returned an unexpected pagination state.")
    available_pages = set()
    for link in pagination.select(".page-item:not(.disabled) a.page-link[href]"):
        href = link.get("href")
        if not isinstance(href, str):
            raise SourceMarkupError("A Djinni pagination link is invalid.")
        try:
            parsed = urlsplit(urljoin(SEARCH_URL, href))
        except ValueError as exc:
            raise SourceMarkupError("A Djinni pagination URL is malformed.") from exc
        numbers = parse_qs(parsed.query).get("page", [])
        if (
            parsed.scheme != "https"
            or parsed.netloc != "djinni.co"
            or parsed.path != "/jobs/"
            or parsed.fragment
            or len(numbers) != 1
            or not numbers[0].isascii()
            or not numbers[0].isdigit()
            or int(numbers[0]) < 1
        ):
            raise SourceMarkupError("A Djinni pagination URL is invalid.")
        available_pages.add(int(numbers[0]))
    if (
        any(number > page for number in available_pages)
        and page + 1 not in available_pages
    ):
        raise SourceMarkupError("Djinni's next pagination link is missing.")
    next_page = page + 1 if page + 1 in available_pages else None
    return VacancyPage(tuple(vacancies), next_page)


class DjinniClient:
    """Read anonymous public jobs only, stopping if robots rules deny access."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._http = PublicSearchHttp(client, "Djinni")
        self._robots_lock = asyncio.Lock()
        self._robots_expires_at = 0.0
        self._robots_rules: RobotFileParser | None = None

    async def _check_robots(self, url: str) -> None:
        async with self._robots_lock:
            if self._robots_rules is None or monotonic() >= self._robots_expires_at:
                robots_text = await self._http.get_text(
                    ROBOTS_URL, content_type="text/plain"
                )
                if "user-agent:" not in robots_text.lower():
                    raise SourceAccessError("Djinni robots.txt could not be verified.")
                rules = RobotFileParser(ROBOTS_URL)
                rules.parse(robots_text.splitlines())
                rate = rules.request_rate(USER_AGENT)
                self._http.respect_robots_interval(
                    max(
                        rules.crawl_delay(USER_AGENT) or 0,
                        rate.seconds if rate is not None else 0,
                    )
                )
                self._robots_rules = rules
                self._robots_expires_at = monotonic() + 3600
            if not self._robots_rules.can_fetch(USER_AGENT, url):
                logger.warning("Djinni robots.txt disallows the public search request.")
                raise SourceAccessError("Djinni robots.txt disallows this search.")

    async def search(
        self,
        keyword: str | None = None,
        page: int = 1,
        *,
        categories: tuple[str, ...] = (),
    ) -> VacancyPage:
        """Check this URL against robots and retrieve one keyword results page."""
        url = build_search_url(keyword, page, categories=categories)
        await self._check_robots(url)
        html = await self._http.get_text(url)
        try:
            results = await asyncio.to_thread(parse_search_page, html, page)
        except SourceMarkupError:
            logger.warning("Djinni HTML did not match the expected results structure.")
            raise
        logger.info(
            "Djinni parsed vacancies=%d explicit_remote=%d",
            len(results.vacancies),
            sum(v.remote is True for v in results.vacancies),
        )
        return results

    async def aclose(self) -> None:
        """Close the anonymous source client at application shutdown."""
        await self._http.aclose()
