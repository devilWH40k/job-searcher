"""SQLite persistence with connections created and used in a worker thread."""

import asyncio
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from job_bot.models import SavedSearch, Vacancy, normalize_keyword
from job_bot.sources.djinni_categories import normalize_categories


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
                    views INTEGER,
                    applications INTEGER,
                    applications_period_days INTEGER,
                    updated_text TEXT,
                    PRIMARY KEY (source, source_id)
                )
                """
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(vacancies)")
            }
            for name, sql_type in (
                ("views", "INTEGER"),
                ("applications", "INTEGER"),
                ("applications_period_days", "INTEGER"),
                ("updated_text", "TEXT"),
            ):
                if name not in columns:
                    # Names and types are fixed application constants, not input.
                    connection.execute(
                        f"ALTER TABLE vacancies ADD COLUMN {name} {sql_type}"
                    )
            for vacancy in vacancies:
                row = connection.execute(
                    """
                    INSERT INTO vacancies (
                        source, source_id, url, title, company, location,
                        salary_text, remote, published_at, first_seen_at,
                        views, applications, applications_period_days, updated_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (source, source_id) DO UPDATE SET
                        url = excluded.url,
                        title = excluded.title,
                        company = excluded.company,
                        location = excluded.location,
                        salary_text = excluded.salary_text,
                        remote = excluded.remote,
                        published_at = excluded.published_at,
                        views = excluded.views,
                        applications = excluded.applications,
                        applications_period_days = excluded.applications_period_days,
                        updated_text = excluded.updated_text
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
                        vacancy.views,
                        vacancy.applications,
                        vacancy.applications_period_days,
                        vacancy.updated_text,
                    ),
                ).fetchone()
                saved.append(
                    replace(vacancy, first_seen_at=datetime.fromisoformat(row[0]))
                )
        return saved


class SavedSearchStorage:
    """Store user-owned filters alongside vacancies, with scoped reads."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                keyword TEXT NOT NULL,
                keyword_key TEXT NOT NULL,
                categories TEXT NOT NULL,
                remote_only INTEGER NOT NULL CHECK (remote_only IN (0, 1)),
                created_at TEXT NOT NULL,
                UNIQUE (user_id, source, keyword_key, categories)
            )
            """
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> SavedSearch:
        return SavedSearch(
            id=row["id"],
            user_id=row["user_id"],
            source=row["source"],
            keyword=row["keyword"],
            categories=tuple(json.loads(row["categories"])),
            remote_only=bool(row["remote_only"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    async def save(
        self, user_id: int, source: str, keyword: str, categories: tuple[str, ...]
    ) -> SavedSearch:
        """Save normalized filters; repeated equivalent saves return the same ID."""
        if user_id <= 0 or source != "djinni":
            raise ValueError("A valid owner and supported source are required.")
        keyword = normalize_keyword(keyword) if keyword else ""
        categories = normalize_categories(categories)
        return await asyncio.to_thread(self._save, user_id, source, keyword, categories)

    def _save(
        self, user_id: int, source: str, keyword: str, categories: tuple[str, ...]
    ) -> SavedSearch:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(categories, ensure_ascii=False)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            self._initialize(connection)
            connection.execute(
                """
                INSERT INTO saved_searches (
                    user_id, source, keyword, keyword_key, categories,
                    remote_only, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id, source, keyword_key, categories) DO NOTHING
                """,
                (
                    user_id,
                    source,
                    keyword,
                    keyword.casefold(),
                    encoded,
                    bool(keyword or categories),
                    datetime.now(UTC).isoformat(),
                ),
            )
            row = connection.execute(
                """SELECT * FROM saved_searches
                   WHERE user_id = ? AND source = ? AND keyword_key = ?
                     AND categories = ?""",
                (user_id, source, keyword.casefold(), encoded),
            ).fetchone()
            return self._record(row)

    async def list_for_user(
        self, user_id: int, *, offset: int = 0, limit: int = 7
    ) -> list[SavedSearch]:
        """Read a bounded page belonging only to the requesting user."""
        if user_id <= 0 or offset < 0 or not 1 <= limit <= 7:
            raise ValueError("Invalid saved-search page.")
        return await asyncio.to_thread(self._list, user_id, offset, limit)

    def _list(self, user_id: int, offset: int, limit: int) -> list[SavedSearch]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            self._initialize(connection)
            return [
                self._record(row)
                for row in connection.execute(
                    "SELECT * FROM saved_searches WHERE user_id = ? "
                    "ORDER BY id DESC LIMIT ? OFFSET ?",
                    (user_id, limit, offset),
                )
            ]

    async def get_for_user(self, user_id: int, search_id: int) -> SavedSearch | None:
        """Never look up a saved search without checking its owner in SQL."""
        if user_id <= 0 or search_id <= 0:
            return None
        return await asyncio.to_thread(self._get, user_id, search_id)

    def _get(self, user_id: int, search_id: int) -> SavedSearch | None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            self._initialize(connection)
            row = connection.execute(
                "SELECT * FROM saved_searches WHERE user_id = ? AND id = ?",
                (user_id, search_id),
            ).fetchone()
            return self._record(row) if row is not None else None

    async def delete_for_user(self, user_id: int, search_id: int) -> bool:
        """Delete only the requesting owner's record; stale IDs are harmless."""
        if user_id <= 0 or search_id <= 0:
            return False
        return await asyncio.to_thread(self._delete, user_id, search_id)

    def _delete(self, user_id: int, search_id: int) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute("BEGIN")
            self._initialize(connection)
            cursor = connection.execute(
                "DELETE FROM saved_searches WHERE user_id = ? AND id = ?",
                (user_id, search_id),
            )
            return cursor.rowcount == 1
