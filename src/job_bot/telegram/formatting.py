"""Bounded Telegram HTML formatting for untrusted vacancy text."""

import re
from html import escape

from job_bot.models import SavedSearch, Vacancy
from job_bot.sources.djinni_categories import CATEGORIES


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _english_update(text: str | None) -> str | None:
    """Translate source-relative update labels without inventing a timestamp."""
    if text is None:
        return None
    special = {
        "оновлено щойно": "Updated just now",
        "оновлено сьогодні": "Updated today",
        "оновлено вчора": "Updated yesterday",
    }
    if text in special:
        return special[text]
    match = re.fullmatch(
        r"оновлено ([0-9]{1,6}) (хв\.|год\.|дн\.|тиж\.|міс\.|р\.) тому", text
    )
    if match is None:
        return None
    count = int(match[1])
    unit = {
        "хв.": "minute",
        "год.": "hour",
        "дн.": "day",
        "тиж.": "week",
        "міс.": "month",
        "р.": "year",
    }[match[2]]
    return f"Updated {count} {unit}{'' if count == 1 else 's'} ago"


def format_vacancy(vacancy: Vacancy) -> str:
    """Format one card, with its original URL supplied separately as a button."""
    # These budgets fit Telegram's 4096 limit even after HTML escaping and
    # UTF-16 expansion. The stored source text remains unchanged.
    lines = [f"<b>{escape(_clip(vacancy.title, 200))}</b>"]
    if vacancy.company:
        lines.append(escape(_clip(vacancy.company, 120)))
    if vacancy.location:
        lines.append(f"Location: {escape(_clip(vacancy.location, 100))}")
    if vacancy.salary_text:
        is_band = vacancy.source == "djinni" and set(vacancy.salary_text) == {"$"}
        label = "Salary band (relative)" if is_band else "Salary"
        lines.append(f"{label}: {escape(_clip(vacancy.salary_text, 180))}")
    if vacancy.source == "djinni":
        statistics = []
        if vacancy.views is not None:
            statistics.append(
                f"{vacancy.views:,} {'view' if vacancy.views == 1 else 'views'}"
            )
        if vacancy.applications is not None:
            applications = f"{vacancy.applications:,} " + (
                "application" if vacancy.applications == 1 else "applications"
            )
            if vacancy.applications_period_days is not None:
                days = vacancy.applications_period_days
                applications += f" in the last {days} {'day' if days == 1 else 'days'}"
            statistics.append(applications)
        updated = _english_update(vacancy.updated_text)
        if updated is not None:
            statistics.append(updated)
        if statistics:
            lines.append(" · ".join(statistics))
    source_name = {"work.ua": "Work.ua", "djinni": "Djinni"}.get(
        vacancy.source, vacancy.source
    )
    lines.append(f"Source: {escape(_clip(source_name, 64))}")
    return "\n".join(lines)


def format_saved_search(search: SavedSearch) -> str:
    """Render bounded HTML cards without exposing the owner's Telegram ID."""
    labels = {category.key: category.label for category in CATEGORIES}
    categories = "; ".join(labels.get(key, key) for key in search.categories)
    return "\n".join(
        [
            f"<b>💾 Saved search #{search.id}</b>",
            f"Source: {escape(search.source.capitalize())}",
            f"Keyword: {escape(search.keyword or 'Any keyword')}",
            f"Categories: {escape(_clip(categories or 'All categories', 1400))}",
            f"Scope: {'Remote only' if search.remote_only else 'All public jobs'}",
            f"Created: {search.created_at.strftime('%Y-%m-%d %H:%M')} UTC",
        ]
    )
