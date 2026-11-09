"""Build the Telegram application and run its polling lifecycle."""

import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from job_bot.config import Config
from job_bot.telegram.handlers import help_command, on_error, start, unknown_command

logger = logging.getLogger(__name__)


def create_application(config: Config) -> Application:
    """Build sequential command handling with explicit HTTP timeouts."""
    application = (
        Application.builder()
        .token(config.telegram_bot_token)
        .connect_timeout(10)
        .read_timeout(10)
        .write_timeout(10)
        .pool_timeout(10)
        .get_updates_connect_timeout(10)
        .get_updates_read_timeout(10)
        .get_updates_write_timeout(10)
        .get_updates_pool_timeout(10)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    application.add_error_handler(on_error)
    return application


def run_bot(config: Config) -> None:
    """Poll until interrupted, closing HTTP clients and the event loop on exit."""
    # Python 3.14 no longer implicitly creates an event loop for run_polling.
    # Runner owns the loop while python-telegram-bot owns application shutdown.
    with asyncio.Runner() as runner:
        asyncio.set_event_loop(runner.get_loop())
        application = create_application(config)
        logger.info("Starting Telegram long polling. Press Ctrl+C to stop.")
        application.run_polling(
            timeout=30,
            bootstrap_retries=3,
            allowed_updates=[Update.MESSAGE],
            drop_pending_updates=False,
            close_loop=False,
        )
    logger.info("Telegram bot stopped.")
