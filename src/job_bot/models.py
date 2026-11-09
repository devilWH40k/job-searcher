"""Normalized vacancy data shared by sources, storage, and presentation."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


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

    def __post_init__(self) -> None:
        for value in (self.first_seen_at, self.published_at):
            if value is not None and value.utcoffset() is None:
                raise ValueError("Vacancy timestamps must be timezone-aware.")
