"""Ephemeral search state, isolated by Telegram user and chat."""

from dataclasses import dataclass, field
from secrets import token_hex
from time import monotonic
from typing import Literal

from job_bot.models import Vacancy

SESSION_SECONDS = 1800


@dataclass(slots=True)
class SearchSession:
    """A selected source, unsent cards, and a version for stale-button checks."""

    source: str = "djinni"
    intent: Literal["search", "save"] = "search"
    stage: Literal[
        "source", "keyword", "category_choice", "categories", "results", "ready_to_save"
    ] = "keyword"
    keyword: str = ""
    categories: tuple[str, ...] = ()
    category_group: int | None = None
    category_page: int = 0
    category_version: int = 0
    token: str = field(default_factory=lambda: token_hex(6))
    version: int = 0
    pending: list[Vacancy] = field(default_factory=list)
    seen_ids: set[str] = field(default_factory=set)
    next_page: int | None = 1
    touched_at: float = field(default_factory=monotonic)

    @property
    def more_callback(self) -> str:
        """Bind a pagination button to this search and its current batch."""
        return f"more:{self.token}:{self.version}"

    def category_callback(self, action: str, value: int = 0) -> str:
        """Use short numeric category IDs so callbacks fit Telegram's byte limit."""
        return f"cat:{self.token}:{self.category_version}:{action}:{value}"
