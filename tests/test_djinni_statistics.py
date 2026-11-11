"""Public listing counters, English display, and non-destructive SQLite upgrade."""

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from job_bot.sources.djinni import parse_search_results
from job_bot.storage import VacancyStorage
from job_bot.telegram.formatting import format_vacancy


def test_snapshot_statistics_and_reporting_window(djinni_html: str) -> None:
    vacancy = parse_search_results(djinni_html)[0]
    assert vacancy.views == 1534
    assert vacancy.applications == 196
    assert vacancy.applications_period_days == 30
    assert vacancy.updated_text == "оновлено 4 дн. тому"
    assert vacancy.published_at is None
    assert (
        "1,534 views · 196 applications in the last 30 days · Updated 4 days ago"
        in format_vacancy(vacancy)
    )


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (
            ("63 перегляди", "9 відгуків", "оновлено 2 год. тому"),
            "63 views · 9 applications · Updated 2 hours ago",
        ),
        (
            ("1 перегляд", "1 відгук", "оновлено 1 год. тому"),
            "1 view · 1 application · Updated 1 hour ago",
        ),
        (
            ("0 переглядів", "0 відгуків", "оновлено 5 хв. тому"),
            "0 views · 0 applications · Updated 5 minutes ago",
        ),
        (
            ("1\u202f234 перегляди", "2 відгуки за 1 день", "оновлено вчора"),
            "1,234 views · 2 applications in the last 1 day · Updated yesterday",
        ),
    ],
)
def test_statistics_variants_from_observed_spans(
    djinni_html: str, texts: tuple[str, str, str], expected: str
) -> None:
    soup = BeautifulSoup(djinni_html, "html.parser")
    spans = soup.select_one(".job-item").select("span.text-nowrap")[-3:]
    for span, text in zip(spans, texts, strict=True):
        span.string = text
    vacancy = parse_search_results(str(soup))[0]
    assert expected in format_vacancy(vacancy)


def test_missing_or_unrecognized_statistics_are_not_invented(djinni_html: str) -> None:
    soup = BeautifulSoup(djinni_html, "html.parser")
    spans = soup.select_one(".job-item").select("span.text-nowrap")[-3:]
    for span in spans:
        span.decompose()
    vacancy = parse_search_results(str(soup))[0]
    assert vacancy.views is None and vacancy.applications is None
    assert vacancy.updated_text is None and vacancy.applications_period_days is None
    card = format_vacancy(vacancy)
    assert "views" not in card and "applications" not in card and "Updated" not in card
    assert "Updated" not in format_vacancy(
        replace(vacancy, updated_text="оновлено <script>")
    )


@pytest.mark.parametrize(
    ("source_text", "translated"),
    [
        ("оновлено 2 тиж. тому", "Updated 2 weeks ago"),
        ("оновлено 1 міс. тому", "Updated 1 month ago"),
        ("оновлено 1 р. тому", "Updated 1 year ago"),
        ("оновлено сьогодні", "Updated today"),
        ("оновлено щойно", "Updated just now"),
    ],
)
def test_relative_labels_stay_relative(
    djinni_html: str, source_text: str, translated: str
) -> None:
    vacancy = replace(parse_search_results(djinni_html)[0], updated_text=source_text)
    assert translated in format_vacancy(vacancy)
    assert vacancy.published_at is None


def test_statistics_migration_preserves_old_records_and_updates_counts(
    tmp_path: Path, djinni_html: str
) -> None:
    path = tmp_path / "legacy.sqlite3"
    observed = datetime(2026, 11, 1, tzinfo=UTC)
    vacancy = parse_search_results(djinni_html)[0]
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("""
            CREATE TABLE vacancies (
                source TEXT NOT NULL, source_id TEXT NOT NULL, url TEXT NOT NULL,
                title TEXT NOT NULL, company TEXT, location TEXT, salary_text TEXT,
                remote INTEGER, published_at TEXT, first_seen_at TEXT NOT NULL,
                PRIMARY KEY (source, source_id)
            )
        """)
        connection.execute(
            "INSERT INTO vacancies (source, source_id, url, title, first_seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                vacancy.source,
                vacancy.source_id,
                vacancy.url,
                "Old title",
                observed.isoformat(),
            ),
        )
    store = VacancyStorage(path)

    async def scenario() -> None:
        saved = (await store.save([vacancy]))[0]
        assert saved.first_seen_at == observed and saved.views == 1534
        saved = (await store.save([replace(vacancy, views=1600, applications=200)]))[0]
        assert saved.first_seen_at == observed
        assert saved.views == 1600 and saved.applications == 200

    asyncio.run(scenario())
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            "SELECT title, first_seen_at, views, applications, "
            "applications_period_days, updated_text FROM vacancies"
        ).fetchone()
        assert row == (
            vacancy.title,
            observed.isoformat(),
            1600,
            200,
            30,
            "оновлено 4 дн. тому",
        )
