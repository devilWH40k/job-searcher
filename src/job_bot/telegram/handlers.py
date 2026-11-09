"""Async Telegram commands and safe error reporting."""

import asyncio
import logging
import sqlite3
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.error import Conflict, Forbidden, InvalidToken, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from job_bot.sources.http_client import SourceAccessError, SourceError
from job_bot.telegram.formatting import format_vacancy

logger = logging.getLogger(__name__)
CARD_INTERVAL_SECONDS = 1.1

START_TEXT = "Looking for the first six remote front-end vacancies on Djinni…"
HELP_TEXT = (
    "Available commands:\n"
    "/start - Find six remote front-end vacancies on Djinni\n"
    "/help - Show this help\n\n"
    "This demo uses a fixed search. Repeat /start to search again."
)
UNKNOWN_COMMAND_TEXT = "Unknown command. Send /help to see the available commands."
ERROR_TEXT = "Sorry, I couldn't handle that command. Please try again later."


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
    """Search immediately and send up to six separate vacancy card messages."""
    message = update.effective_message
    if message is None:
        return
    await _reply(message, START_TEXT)
    try:
        vacancies = await context.application.bot_data[
            "job_search"
        ].search_remote_frontend()
    except SourceAccessError:
        await _reply(
            message,
            "Djinni access is unavailable or its robots rules prevent this search. "
            "Please try the search on its website.",
        )
        return
    except SourceError:
        logger.warning("Djinni search is temporarily unavailable.")
        await _reply(
            message, "I couldn't load Djinni vacancies. Please try again later."
        )
        return
    except sqlite3.Error, OSError:
        logger.error("Vacancies could not be saved.")
        await _reply(message, "I couldn't save the vacancies. Please try again later.")
        return
    if not vacancies:
        await _reply(message, "No remote front-end vacancies were found on Djinni.")
        return
    for vacancy in vacancies[:6]:
        # Pace messages in this chat instead of sending a six-message burst.
        await asyncio.sleep(CARD_INTERVAL_SECONDS)
        await _reply(
            message,
            format_vacancy(vacancy),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("View on Djinni", url=vacancy.url)]]
            ),
        )


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
