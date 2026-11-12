"""Normalized vacancy data shared by sources, storage, and presentation."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from unicodedata import category


class SearchInputError(ValueError):
    """A keyword is empty, too long, or contains unsupported characters."""


def normalize_keyword(value: str) -> str:
    """Normalize spacing without changing the user's position or language name."""
    keyword = " ".join(value.split())
    if not keyword or len(keyword) > 100 or not any(c.isalnum() for c in keyword):
        raise SearchInputError(
            "Send a position or keyword of 1–100 characters, "
            "such as Python or Frontend."
        )
    if any(category(char).startswith("C") for char in keyword):
        raise SearchInputError(
            "Please remove control or invisible characters from the keyword."
        )
    return keyword


@dataclass(frozen=True, slots=True)
class Vacancy:
    """A source vacancy with original text and timezone-aware timestamps."""

    source: str
    source_id: str
    url: str
    title: str
    company: str | None = None
    location: str | None = None
    salary_text: str | None = None
    remote: bool | None = None
    published_at: datetime | None = None
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    views: int | None = None
    applications: int | None = None
    applications_period_days: int | None = None
    updated_text: str | None = None

    def __post_init__(self) -> None:
        for value in (self.first_seen_at, self.published_at):
            if value is not None and value.utcoffset() is None:
                raise ValueError("Vacancy timestamps must be timezone-aware.")
        for value in (self.views, self.applications, self.applications_period_days):
            if value is not None and value < 0:
                raise ValueError("Vacancy statistics must be nonnegative.")


@dataclass(frozen=True, slots=True)
class VacancyPage:
    """An immutable source page with the next verified source page number."""

    vacancies: tuple[Vacancy, ...]
    next_page: int | None = None


@dataclass(frozen=True, slots=True)
class SavedSearch:
    """A reusable set of filters owned by one Telegram numeric user ID."""

    id: int
    user_id: int
    source: str
    keyword: str
    categories: tuple[str, ...]
    remote_only: bool
    created_at: datetime
