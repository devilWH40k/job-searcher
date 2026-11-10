"""Async Telegram commands and safe error reporting."""

import asyncio
import logging
import sqlite3
from dataclasses import replace
from datetime import timedelta
from time import monotonic

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.error import Conflict, Forbidden, InvalidToken, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from job_bot.models import SearchInputError, normalize_keyword
from job_bot.sources.djinni_categories import (
    CATEGORIES,
    CATEGORY_GROUPS,
    normalize_categories,
)
from job_bot.sources.http_client import SourceAccessError, SourceError
from job_bot.telegram.categories import PAGE_SIZE, category_picker
from job_bot.telegram.formatting import format_vacancy
from job_bot.telegram.search_state import SESSION_SECONDS, SearchSession

logger = logging.getLogger(__name__)
CARD_INTERVAL_SECONDS = 1.1

START_TEXT = "Choose a vacancy source:"
KEYWORD_TEXT = (
    "Send a position or keyword, such as Python, QA, or Frontend, or tap Skip."
)
CATEGORY_CHOICE_TEXT = "Would you like to add categories?"
SEARCHING_TEXT = "Searching Djinni for vacancies..."
HELP_TEXT = (
    "Available commands:\n"
    "/start - Start a new search\n"
    "/help - Show this help\n"
    "/finish - Finish the current search\n\n"
    "Choose Djinni, enter a keyword or Skip, then choose whether to add categories.\n"
    "Skip + No searches all public jobs without filters. "
    "Other searches are remote-only.\n"
    "Use Load 6 more for the next batch or Finish to end the search."
)
UNKNOWN_COMMAND_TEXT = "Unknown command. Send /help to see the available commands."
ERROR_TEXT = "Sorry, I couldn't handle that request. Send /start to try again."


async def _reply(
    message: Message,
    text: str,
    *,
    parse_mode: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Send a message, honoring a Telegram rate limit with one bounded retry."""
    try:
        await message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except RetryAfter as exc:
        delay = exc.retry_after
        await asyncio.sleep(
            delay.total_seconds() if isinstance(delay, timedelta) else delay
        )
        await message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a fresh source selection without making source requests."""
    message = update.effective_message
    if message is None:
        return
    if context.user_data is not None and update.effective_chat is not None:
        context.user_data.get("search_sessions", {}).pop(update.effective_chat.id, None)
    await _reply(
        message,
        START_TEXT,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Djinni", callback_data="source:djinni")]]
        ),
    )


def _get_session(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> SearchSession | None:
    if context.user_data is None or update.effective_chat is None:
        return None
    sessions = context.user_data.get("search_sessions", {})
    state = sessions.get(update.effective_chat.id)
    if not isinstance(state, SearchSession):
        return None
    if monotonic() - state.touched_at > SESSION_SECONDS:
        sessions.pop(update.effective_chat.id, None)
        return None
    return state


def _set_session(
    update: Update, context: ContextTypes.DEFAULT_TYPE, state: SearchSession
) -> None:
    if context.user_data is not None and update.effective_chat is not None:
        sessions = context.user_data.setdefault("search_sessions", {})
        sessions[update.effective_chat.id] = state


async def select_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Accept the available source and ask for a keyword."""
    query = update.callback_query
    if query is None:
        return
    if query.data != "source:djinni":
        await query.answer("That source is not available.")
        return
    await query.answer()
    if update.effective_message is None or context.user_data is None:
        return
    state = SearchSession()
    _set_session(update, context, state)
    await _reply(
        update.effective_message,
        KEYWORD_TEXT,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Skip", callback_data=f"skip:{state.token}")]]
        ),
    )


async def _ask_categories(message: Message, state: SearchSession) -> None:
    state.stage = "category_choice"
    state.touched_at = monotonic()
    await _reply(
        message,
        CATEGORY_CHOICE_TEXT,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        label, callback_data=f"categories:{state.token}:{answer}"
                    )
                    for label, answer in (("Yes", "yes"), ("No", "no"))
                ]
            ]
        ),
    )


async def skip_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """An explicit Skip stores an empty keyword and asks about categories."""
    query = update.callback_query
    if query is None:
        return
    state = _get_session(update, context)
    if state is None or state.stage != "keyword" or query.data != f"skip:{state.token}":
        await query.answer(
            "This button is no longer current. Send /start to search again."
        )
        return
    await query.answer()
    if update.effective_message is not None:
        state.keyword = ""
        await _ask_categories(update.effective_message, state)


async def choose_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the multi-select picker or search with the keyword already entered."""
    query = update.callback_query
    if query is None:
        return
    state = _get_session(update, context)
    parts = query.data.split(":") if isinstance(query.data, str) else []
    if (
        state is None
        or state.stage != "category_choice"
        or len(parts) != 3
        or parts[0] != "categories"
        or parts[1] != state.token
        or parts[2] not in ("yes", "no")
    ):
        await query.answer(
            "This button is no longer current. Send /start to search again."
        )
        return
    await query.answer()
    if update.effective_message is None:
        return
    state.touched_at = monotonic()
    if parts[2] == "yes":
        state.stage = "categories"
        text, markup = category_picker(state)
        await _reply(update.effective_message, text, reply_markup=markup)
    else:
        state.stage = "results"
        await _reply(update.effective_message, SEARCHING_TEXT)
        await _send_next_batch(update.effective_message, context, state)


async def select_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle categories and navigate their groups without fetching vacancies."""
    query = update.callback_query
    if query is None:
        return
    state = _get_session(update, context)
    parts = query.data.split(":") if isinstance(query.data, str) else []
    if (
        state is None
        or state.stage != "categories"
        or len(parts) != 5
        or parts[0] != "cat"
        or parts[1] != state.token
        or parts[2] != str(state.category_version)
        or not parts[4].isascii()
        or not parts[4].isdigit()
        or len(parts[4]) > 3
    ):
        await query.answer(
            "This category picker is no longer current. Send /start to choose again."
        )
        return
    action, value = parts[3], int(parts[4])
    candidate = replace(state)
    if action == "g" and value < len(CATEGORY_GROUPS):
        candidate.category_group, candidate.category_page = value, 0
    elif action == "b":
        candidate.category_group, candidate.category_page = None, 0
    elif action == "p" and state.category_group is not None:
        count = sum(
            c.group == CATEGORY_GROUPS[state.category_group] for c in CATEGORIES
        )
        if value * PAGE_SIZE >= count:
            await query.answer("That category page is unavailable.")
            return
        candidate.category_page = value
    elif (
        action == "t"
        and value < len(CATEGORIES)
        and state.category_group is not None
        and CATEGORIES[value].group == CATEGORY_GROUPS[state.category_group]
    ):
        selected = set(state.categories)
        key = CATEGORIES[value].key
        if key in selected:
            selected.remove(key)
        else:
            selected.add(key)
        try:
            candidate.categories = normalize_categories(tuple(selected))
        except SearchInputError as exc:
            await query.answer(str(exc))
            return
    elif action == "c":
        candidate.categories = ()
    elif action == "d":
        if not state.categories:
            await query.answer("Select at least one category first.")
            return
        candidate.stage = "results"
    else:
        await query.answer("That category option is unavailable.")
        return
    candidate.category_version += 1
    candidate.touched_at = monotonic()
    await query.answer()
    text, markup = (
        (SEARCHING_TEXT, None) if action == "d" else category_picker(candidate)
    )
    try:
        await query.edit_message_text(text, parse_mode=None, reply_markup=markup)
    except RetryAfter as exc:
        delay = exc.retry_after
        await asyncio.sleep(
            delay.total_seconds() if isinstance(delay, timedelta) else delay
        )
        await query.edit_message_text(text, parse_mode=None, reply_markup=markup)
    _set_session(update, context, candidate)
    if action == "d" and update.effective_message is not None:
        await _send_next_batch(update.effective_message, context, candidate)


async def search_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Validate the optional keyword before asking about category filters."""
    message = update.effective_message
    if message is None:
        return
    previous = _get_session(update, context)
    if previous is None:
        await _reply(
            message, "Send /start and choose Djinni before entering a keyword."
        )
        return
    if previous.stage != "keyword":
        await _reply(
            message, "Use the buttons above to continue, or /start for a new search."
        )
        return
    try:
        keyword = normalize_keyword(message.text or "")
    except SearchInputError as exc:
        await _reply(message, str(exc))
        return
    previous.keyword = keyword
    await _ask_categories(message, previous)


async def load_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Acknowledge clicks immediately and reject old or another user's buttons."""
    query = update.callback_query
    if query is None:
        return
    state = _get_session(update, context)
    if state is None or state.stage != "results" or query.data != state.more_callback:
        await query.answer(
            "This button is no longer current. Send /start to search again."
        )
        return
    await query.answer()
    if update.effective_message is not None:
        state.touched_at = monotonic()
        await _send_next_batch(update.effective_message, context, state)


async def _send_next_batch(
    message: Message, context: ContextTypes.DEFAULT_TYPE, state: SearchSession
) -> None:
    """Use buffered cards first, fetching at most three source pages per click."""
    pending = list(state.pending)
    seen_ids = set(state.seen_ids)
    next_page = state.next_page
    retry_markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Try again", callback_data=state.more_callback)],
            [InlineKeyboardButton("Finish", callback_data=f"finish:{state.token}")],
        ]
    )
    try:
        for _ in range(3):
            if len(pending) >= 6 or next_page is None:
                break
            page = await context.application.bot_data["job_search"].search(
                state.keyword or None,
                next_page,
                categories=state.categories,
            )
            for vacancy in page.vacancies:
                if vacancy.source_id not in seen_ids:
                    seen_ids.add(vacancy.source_id)
                    pending.append(vacancy)
            next_page = page.next_page
    except SourceAccessError:
        await _reply(
            message,
            "Djinni access is unavailable or its robots rules prevent this search. "
            "Please try the search on its website.",
            reply_markup=retry_markup,
        )
        return
    except SourceError:
        logger.warning("Djinni search is temporarily unavailable.")
        await _reply(
            message,
            "I couldn't load Djinni vacancies. Please try again later.",
            reply_markup=retry_markup,
        )
        return
    except sqlite3.Error, OSError:
        logger.error("Vacancies could not be saved.")
        await _reply(
            message,
            "I couldn't save the vacancies. Please try again later.",
            reply_markup=retry_markup,
        )
        return
    state.pending = pending
    state.seen_ids = seen_ids
    state.next_page = next_page
    state.version += 1
    state.touched_at = monotonic()
    batch = state.pending[:6]
    has_more = len(state.pending) > len(batch) or state.next_page is not None
    finish_button = [
        InlineKeyboardButton("Finish", callback_data=f"finish:{state.token}")
    ]
    more_button = [
        InlineKeyboardButton("Load 6 more", callback_data=state.more_callback)
    ]
    if not batch:
        text = (
            "No vacancies found for this search."
            if not state.seen_ids
            else "No more results for this search."
        )
        if has_more:
            text = "No new matches on these pages. Load more to continue."
        await _reply(
            message,
            text,
            reply_markup=InlineKeyboardMarkup(
                [*([more_button] if has_more else []), finish_button]
            ),
        )
        return
    for index, vacancy in enumerate(batch):
        # Pace messages in this chat instead of sending a six-message burst.
        await asyncio.sleep(CARD_INTERVAL_SECONDS)
        await _reply(
            message,
            format_vacancy(vacancy),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("View on Djinni", url=vacancy.url)],
                    *([more_button] if has_more and index == len(batch) - 1 else []),
                    *([finish_button] if index == len(batch) - 1 else []),
                ]
            ),
        )
        state.pending.pop(0)


async def finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Discard this chat's cursor and show commands, invalidating old controls."""
    query = update.callback_query
    if query is not None:
        state = _get_session(update, context)
        if state is None or query.data != f"finish:{state.token}":
            await query.answer(
                "This button is no longer current. Send /start to search again."
            )
            return
        await query.answer()
    if context.user_data is not None and update.effective_chat is not None:
        context.user_data.get("search_sessions", {}).pop(update.effective_chat.id, None)
    if update.effective_message is not None:
        await _reply(update.effective_message, "Search finished.\n\n" + HELP_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain the commands currently supported by the bot."""
    if update.effective_message is not None:
        await _reply(update.effective_message, HELP_TEXT)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Direct unsupported commands to the help message."""
    if update.effective_message is not None:
        await _reply(update.effective_message, UNKNOWN_COMMAND_TEXT)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Report failures without logging exceptions, tokens, or update contents."""
    error = context.error
    if isinstance(error, Conflict):
        logger.error(
            "Telegram polling conflict. Stop other instances using this bot token, "
            "then restart this process."
        )
        context.application.stop_running()
        return
    if isinstance(error, InvalidToken):
        logger.error(
            "Telegram rejected the token. Check TELEGRAM_BOT_TOKEN and restart."
        )
        context.application.stop_running()
        return
    if update is None:
        logger.warning("Telegram polling failed (%s); retrying.", type(error).__name__)
        return

    logger.error("Could not process a Telegram command (%s).", type(error).__name__)
    if (
        isinstance(update, Update)
        and update.effective_message is not None
        and not isinstance(error, (Forbidden, RetryAfter))
    ):
        try:
            await _reply(update.effective_message, ERROR_TEXT)
        except TelegramError:
            logger.warning("Could not send the command error message.")
