"""Bounded Telegram HTML formatting for untrusted vacancy text."""

from html import escape

from job_bot.models import Vacancy


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


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
    source_name = {"work.ua": "Work.ua", "djinni": "Djinni"}.get(
        vacancy.source, vacancy.source
    )
    lines.append(f"Source: {escape(_clip(source_name, 64))}")
    return "\n".join(lines)
