"""SQLite persistence with connections created and used in a worker thread."""

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from job_bot.models import Vacancy


class VacancyStorage:
    """Persist normalized vacancies without collecting Telegram user data."""

    def __init__(self, path: Path) -> None:
        self.path = path

    async def save(self, vacancies: list[Vacancy]) -> list[Vacancy]:
        """Upsert vacancies and preserve the first observation of each source ID."""
        return await asyncio.to_thread(self._save, vacancies)

    def _save(self, vacancies: list[Vacancy]) -> list[Vacancy]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        saved = []
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute("BEGIN")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vacancies (
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT,
                    location TEXT,
                    salary_text TEXT,
                    remote INTEGER CHECK (remote IN (0, 1) OR remote IS NULL),
                    published_at TEXT,
                    first_seen_at TEXT NOT NULL,
                    PRIMARY KEY (source, source_id)
                )
                """
            )
            for vacancy in vacancies:
                row = connection.execute(
                    """
                    INSERT INTO vacancies (
                        source, source_id, url, title, company, location,
                        salary_text, remote, published_at, first_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (source, source_id) DO UPDATE SET
                        url = excluded.url,
                        title = excluded.title,
                        company = excluded.company,
                        location = excluded.location,
                        salary_text = excluded.salary_text,
                        remote = excluded.remote,
                        published_at = excluded.published_at
                    RETURNING first_seen_at
                    """,
                    (
                        vacancy.source,
                        vacancy.source_id,
                        vacancy.url,
                        vacancy.title,
                        vacancy.company,
                        vacancy.location,
                        vacancy.salary_text,
                        vacancy.remote,
                        vacancy.published_at.astimezone(UTC).isoformat()
                        if vacancy.published_at is not None
                        else None,
                        vacancy.first_seen_at.astimezone(UTC).isoformat(),
                    ),
                ).fetchone()
                saved.append(
                    replace(vacancy, first_seen_at=datetime.fromisoformat(row[0]))
                )
        return saved
