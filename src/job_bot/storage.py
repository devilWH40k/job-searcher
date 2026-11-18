"""SQLite persistence with connections created and used in a worker thread."""

import asyncio
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from job_bot.models import SavedSearch, TrackedSearch, Vacancy, normalize_keyword
from job_bot.sources.djinni_categories import normalize_categories


def _vacancy_payload(vacancy: Vacancy) -> str:
    values = asdict(vacancy)
    values["first_seen_at"] = vacancy.first_seen_at.astimezone(UTC).isoformat()
    values["published_at"] = (
        vacancy.published_at.astimezone(UTC).isoformat()
        if vacancy.published_at
        else None
    )
    return json.dumps(values, ensure_ascii=False)


def _vacancy_from_payload(payload: str) -> Vacancy:
    values = json.loads(payload)
    for name in ("first_seen_at", "published_at"):
        if values[name] is not None:
            values[name] = datetime.fromisoformat(values[name])
    return Vacancy(**values)


class RecentVacancyStorage:
    """Remember each user's discoveries independently of the shared source cache."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS recent_vacancies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                found_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                UNIQUE (user_id, source, source_id)
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS recent_vacancies_user_order "
            "ON recent_vacancies (user_id, id DESC)"
        )

    @staticmethod
    def _record_in_transaction(
        connection: sqlite3.Connection,
        user_id: int,
        vacancies: tuple[Vacancy, ...],
        found_at: datetime,
    ) -> None:
        RecentVacancyStorage._initialize(connection)
        unique = {(v.source, v.source_id): v for v in vacancies}
        # A newly discovered batch retains source order when read newest-first.
        for vacancy in reversed(unique.values()):
            connection.execute(
                "INSERT INTO recent_vacancies "
                "(user_id, source, source_id, found_at, payload) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (user_id, source, source_id) "
                "DO UPDATE SET payload = excluded.payload",
                (
                    user_id,
                    vacancy.source,
                    vacancy.source_id,
                    found_at.astimezone(UTC).isoformat(),
                    _vacancy_payload(vacancy),
                ),
            )

    async def record(self, user_id: int, vacancies: tuple[Vacancy, ...]) -> None:
        """Update snapshots without promoting vacancies already known to this user."""
        if user_id <= 0:
            raise ValueError("A valid owner is required.")
        if vacancies:
            await asyncio.to_thread(self._record, user_id, vacancies)

    def _record(self, user_id: int, vacancies: tuple[Vacancy, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._record_in_transaction(
                connection, user_id, vacancies, datetime.now(UTC)
            )

    async def list_for_user(self, user_id: int) -> list[Vacancy]:
        """Return at most six distinct discoveries, checking ownership in SQL."""
        if user_id <= 0:
            raise ValueError("A valid owner is required.")
        return await asyncio.to_thread(self._list, user_id)

    def _list(self, user_id: int) -> list[Vacancy]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._initialize(connection)
            return [
                _vacancy_from_payload(payload)
                for (payload,) in connection.execute(
                    "SELECT payload FROM recent_vacancies "
                    "WHERE user_id = ? ORDER BY id DESC LIMIT 6",
                    (user_id,),
                )
            ]


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
        connection.execute(
            """CREATE TABLE IF NOT EXISTS tracked_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_id INTEGER NOT NULL UNIQUE,
                initialized INTEGER NOT NULL DEFAULT 0,
                next_page INTEGER NOT NULL DEFAULT 1,
                next_check_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS tracked_matches (
                tracking_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                payload TEXT,
                PRIMARY KEY (tracking_id, source, source_id)
            )"""
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
            tracked=bool(row["tracked"]) if "tracked" in row.keys() else False,
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
                """SELECT *, EXISTS (
                       SELECT 1 FROM tracked_searches
                       WHERE search_id = saved_searches.id
                   ) AS tracked FROM saved_searches
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
                    "SELECT *, EXISTS (SELECT 1 FROM tracked_searches "
                    "WHERE search_id = saved_searches.id) AS tracked "
                    "FROM saved_searches WHERE user_id = ? "
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
                "SELECT *, EXISTS (SELECT 1 FROM tracked_searches "
                "WHERE search_id = saved_searches.id) AS tracked "
                "FROM saved_searches WHERE user_id = ? AND id = ?",
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
            connection.execute(
                "DELETE FROM tracked_matches WHERE tracking_id IN "
                "(SELECT t.id FROM tracked_searches t JOIN saved_searches s "
                "ON s.id = t.search_id WHERE s.user_id = ? AND s.id = ?)",
                (user_id, search_id),
            )
            connection.execute(
                "DELETE FROM tracked_searches WHERE search_id IN "
                "(SELECT id FROM saved_searches WHERE user_id = ? AND id = ?)",
                (user_id, search_id),
            )
            cursor = connection.execute(
                "DELETE FROM saved_searches WHERE user_id = ? AND id = ?",
                (user_id, search_id),
            )
            return cursor.rowcount == 1


TRACK_INTERVAL = timedelta(minutes=30)


class TrackingStorage(SavedSearchStorage):
    """Persist subscriptions, per-search seen IDs, and unsent alert payloads."""

    async def enable(self, user_id: int, search_id: int) -> SavedSearch | None:
        return await asyncio.to_thread(self._enable, user_id, search_id)

    def _enable(self, user_id: int, search_id: int) -> SavedSearch | None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            self._initialize(connection)
            row = connection.execute(
                "SELECT * FROM saved_searches WHERE user_id = ? AND id = ?",
                (user_id, search_id),
            ).fetchone()
            if row is None or row["source"] != "djinni":
                return None
            connection.execute(
                "INSERT INTO tracked_searches (search_id, next_check_at) VALUES (?, ?) "
                "ON CONFLICT (search_id) DO NOTHING",
                (search_id, datetime.now(UTC).isoformat()),
            )
            return replace(self._record(row), tracked=True)

    async def disable(
        self, user_id: int, search_id: int, *, tracking_id: int | None = None
    ) -> bool:
        return await asyncio.to_thread(self._disable, user_id, search_id, tracking_id)

    def _disable(self, user_id: int, search_id: int, tracking_id: int | None) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._initialize(connection)
            row = connection.execute(
                "SELECT t.id FROM tracked_searches t JOIN saved_searches s "
                "ON s.id = t.search_id WHERE s.user_id = ? AND s.id = ?",
                (user_id, search_id),
            ).fetchone()
            if row is None or (tracking_id is not None and row[0] != tracking_id):
                return False
            connection.execute(
                "DELETE FROM tracked_matches WHERE tracking_id = ?", (row[0],)
            )
            cursor = connection.execute(
                "DELETE FROM tracked_searches WHERE id = ?", (row[0],)
            )
            return cursor.rowcount == 1

    async def due(self, now: datetime) -> list[TrackedSearch]:
        return await asyncio.to_thread(self._due, now)

    def _due(self, now: datetime) -> list[TrackedSearch]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            self._initialize(connection)
            return [
                TrackedSearch(
                    id=row["tracking_id"],
                    search=replace(self._record(row), tracked=True),
                    initialized=bool(row["initialized"]),
                    next_page=row["next_page"],
                )
                for row in connection.execute(
                    "SELECT s.*, t.id AS tracking_id, t.initialized, t.next_page "
                    "FROM tracked_searches t JOIN saved_searches s "
                    "ON s.id = t.search_id WHERE t.next_check_at <= ? "
                    "ORDER BY t.next_check_at, t.id LIMIT 100",
                    (now.astimezone(UTC).isoformat(),),
                )
            ]

    async def active(self, tracking_id: int) -> bool:
        return await asyncio.to_thread(self._active, tracking_id)

    def _active(self, tracking_id: int) -> bool:
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM tracked_searches WHERE id = ?", (tracking_id,)
                ).fetchone()
                is not None
            )

    async def record_page(
        self,
        tracking: TrackedSearch,
        vacancies: tuple[Vacancy, ...],
        next_page: int | None,
        now: datetime,
    ) -> None:
        """Checkpoint one page atomically; NULL payloads are already seen IDs."""
        await asyncio.to_thread(self._record_page, tracking, vacancies, next_page, now)

    def _record_page(
        self,
        tracking: TrackedSearch,
        vacancies: tuple[Vacancy, ...],
        next_page: int | None,
        now: datetime,
    ) -> None:
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if (
                connection.execute(
                    "SELECT 1 FROM tracked_searches WHERE id = ?", (tracking.id,)
                ).fetchone()
                is None
            ):
                return
            RecentVacancyStorage._record_in_transaction(
                connection, tracking.search.user_id, vacancies, now
            )
            for vacancy in vacancies:
                payload = _vacancy_payload(vacancy) if tracking.initialized else None
                connection.execute(
                    "INSERT INTO tracked_matches "
                    "(tracking_id, source, source_id, payload) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (tracking_id, source, source_id) DO NOTHING",
                    (tracking.id, vacancy.source, vacancy.source_id, payload),
                )
            connection.execute(
                "UPDATE tracked_searches SET next_page = ?, initialized = ?, "
                "next_check_at = ? WHERE id = ?",
                (
                    next_page or 1,
                    tracking.initialized or next_page is None,
                    (now if next_page else now + TRACK_INTERVAL)
                    .astimezone(UTC)
                    .isoformat(),
                    tracking.id,
                ),
            )

    async def pending(self, tracking_id: int, *, limit: int = 6) -> list[Vacancy]:
        return await asyncio.to_thread(self._pending, tracking_id, limit)

    def _pending(self, tracking_id: int, limit: int) -> list[Vacancy]:
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            result = []
            for (payload,) in connection.execute(
                "SELECT payload FROM tracked_matches "
                "WHERE tracking_id = ? AND payload IS NOT NULL ORDER BY rowid LIMIT ?",
                (tracking_id, limit),
            ):
                result.append(_vacancy_from_payload(payload))
            return result

    async def acknowledge(self, tracking_id: int, vacancy: Vacancy) -> None:
        await asyncio.to_thread(self._acknowledge, tracking_id, vacancy)

    def _acknowledge(self, tracking_id: int, vacancy: Vacancy) -> None:
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute("BEGIN")
            connection.execute(
                "UPDATE tracked_matches SET payload = NULL "
                "WHERE tracking_id = ? AND source = ? AND source_id = ?",
                (tracking_id, vacancy.source, vacancy.source_id),
            )

    async def defer(self, tracking_id: int, now: datetime) -> None:
        await asyncio.to_thread(self._defer, tracking_id, now)

    def _defer(self, tracking_id: int, now: datetime) -> None:
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute("BEGIN")
            connection.execute(
                "UPDATE tracked_searches SET next_check_at = ? WHERE id = ?",
                ((now + TRACK_INTERVAL).astimezone(UTC).isoformat(), tracking_id),
            )
