"""Async Telegram commands and safe error reporting."""

import asyncio
import logging
from datetime import timedelta

from telegram import Message, Update
from telegram.error import Conflict, Forbidden, InvalidToken, RetryAfter, TelegramError
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

START_TEXT = (
    "Hello! I'm your job search bot.\n"
    "Telegram commands are ready; vacancy search is coming next.\n"
    "Send /help to see the available commands."
)
HELP_TEXT = (
    "Available commands:\n"
    "/start - Welcome message\n"
    "/help - Show this help\n\n"
    "Work.ua vacancy search is not available yet."
)
UNKNOWN_COMMAND_TEXT = "Unknown command. Send /help to see the available commands."
ERROR_TEXT = "Sorry, I couldn't handle that command. Please try again later."


async def _reply(message: Message, text: str) -> None:
    """Send plain text, honoring a Telegram rate limit with one bounded retry."""
    try:
        await message.reply_text(text, parse_mode=None)
    except RetryAfter as exc:
        delay = exc.retry_after
        await asyncio.sleep(
            delay.total_seconds() if isinstance(delay, timedelta) else delay
        )
        await message.reply_text(text, parse_mode=None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome the user without echoing or recording personal information."""
    if update.effective_message is not None:
        await _reply(update.effective_message, START_TEXT)


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
