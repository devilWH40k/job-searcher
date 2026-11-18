"""Grouped, paged category selection for Telegram inline keyboards."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from job_bot.sources.djinni_categories import CATEGORIES, CATEGORY_GROUPS
from job_bot.telegram.search_state import SearchSession

PAGE_SIZE = 10
CATEGORY_LABEL_WIDTH = 44


def _category_label(text: str) -> str:
    """Visually shift centered button text left with nonbreaking padding."""
    return text[:60].ljust(CATEGORY_LABEL_WIDTH, "\u00a0")


def category_picker(state: SearchSession) -> tuple[str, InlineKeyboardMarkup]:
    """Render a source category snapshot without making network requests."""
    selected = set(state.categories)
    labels = [category.label for category in CATEGORIES if category.key in selected]
    summary = "; ".join(labels) or "None selected"
    if len(summary) > 1400:
        summary = summary[:1399] + "…"
    rows = []
    action_label = "Save search" if state.intent == "save" else "Search"
    if state.intent == "track":
        action_label = "Save & track"
    title = "Choose one or more categories"
    if state.category_group is None:
        for index, group in enumerate(CATEGORY_GROUPS):
            count = sum(
                category.key in selected
                for category in CATEGORIES
                if category.group == group
            )
            label = f"{group} ({count})" if count else group
            rows.append(
                [
                    InlineKeyboardButton(
                        label, callback_data=state.category_callback("g", index)
                    )
                ]
            )
    else:
        group = CATEGORY_GROUPS[state.category_group]
        items = [
            (index, category)
            for index, category in enumerate(CATEGORIES)
            if category.group == group
        ]
        pages = (len(items) + PAGE_SIZE - 1) // PAGE_SIZE
        title = f"{group} — page {state.category_page + 1}/{pages}"
        start = state.category_page * PAGE_SIZE
        for index, category in items[start : start + PAGE_SIZE]:
            mark = "✓" if category.key in selected else "□"
            indent = "\u00a0\u00a0\u21b3 " if category.parent is not None else ""
            label = f"{indent}{mark} {category.label}"
            rows.append(
                [
                    InlineKeyboardButton(
                        _category_label(label),
                        callback_data=state.category_callback("t", index),
                    )
                ]
            )
        navigation = []
        if state.category_page > 0:
            navigation.append(
                InlineKeyboardButton(
                    "← Previous",
                    callback_data=state.category_callback("p", state.category_page - 1),
                )
            )
        if state.category_page + 1 < pages:
            navigation.append(
                InlineKeyboardButton(
                    "Next →",
                    callback_data=state.category_callback("p", state.category_page + 1),
                )
            )
        if navigation:
            rows.append(navigation)
        rows.append(
            [
                InlineKeyboardButton(
                    "← Category groups", callback_data=state.category_callback("b")
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                f"{action_label} ({len(selected)} selected)",
                callback_data=state.category_callback("d"),
            )
        ]
    )
    if selected:
        rows.append(
            [
                InlineKeyboardButton(
                    "Clear selections", callback_data=state.category_callback("c")
                )
            ]
        )
    text = (
        f"{title}\nSelected: {summary}\n\n"
        f"Select multiple items across groups, then tap {action_label}."
    )
    return text, InlineKeyboardMarkup(rows)
