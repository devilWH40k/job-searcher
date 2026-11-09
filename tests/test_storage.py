"""SQLite uniqueness, updates, original text, and UTC timestamp tests."""

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from job_bot.models import Vacancy
from job_bot.storage import VacancyStorage


def test_upsert_keeps_first_seen_and_original_salary(tmp_path: Path) -> None:
    path = tmp_path / "data/jobs.sqlite3"
    storage = VacancyStorage(path)
    first_seen = datetime(2026, 11, 9, tzinfo=UTC)
    vacancy = Vacancy(
        "work.ua",
        "123",
        "https://www.work.ua/jobs/123/",
        "Front-end",
        first_seen_at=first_seen,
    )
    updated = replace(
        vacancy,
        title="Developer's job; DROP TABLE vacancies;",
        salary_text="35 000 – 55 000 грн",
        remote=True,
        first_seen_at=first_seen + timedelta(hours=1),
    )

    async def scenario() -> None:
        await storage.save([vacancy])
        saved = await storage.save([updated, updated])
        assert all(item.first_seen_at == first_seen for item in saved)

    asyncio.run(scenario())

    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT title, salary_text, remote, first_seen_at FROM vacancies"
        ).fetchall()
    assert rows == [(updated.title, updated.salary_text, 1, first_seen.isoformat())]


def test_unknown_values_and_timestamps_are_stored_in_utc(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    now = datetime(2026, 11, 9, 12, tzinfo=timezone(timedelta(hours=2)))
    vacancy = Vacancy(
        "work.ua",
        "123",
        "https://www.work.ua/jobs/123/",
        "Front-end",
        first_seen_at=now,
    )

    saved = asyncio.run(
        VacancyStorage(path).save([vacancy, replace(vacancy, source="another-source")])
    )

    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT company, location, salary_text, remote, published_at, "
            "first_seen_at FROM vacancies"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0] == (None, None, None, None, None, now.astimezone(UTC).isoformat())
    assert saved[0].first_seen_at.tzinfo == UTC
