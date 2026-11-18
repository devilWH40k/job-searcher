"""A single cancellable background worker for persistent vacancy alerts."""

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import Application

from job_bot.models import TrackedSearch, Vacancy
from job_bot.services.tracking import TrackingService
from job_bot.sources.http_client import SourceError
from job_bot.telegram.formatting import format_vacancy

logger = logging.getLogger(__name__)
WORKER_INTERVAL_SECONDS = 10
ALERT_INTERVAL_SECONDS = 1.1


async def send_alert(
    application: Application, tracking: TrackedSearch, vacancy: Vacancy
) -> None:
    """Send bounded escaped cards, pacing all recipients through one worker."""
    await asyncio.sleep(ALERT_INTERVAL_SECONDS)
    if not await application.bot_data["tracking"].storage.active(tracking.id):
        return
    text = f"New match for saved search #{tracking.search.id}\n\n" + format_vacancy(
        vacancy
    )
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Open vacancy", url=vacancy.url)],
            [
                InlineKeyboardButton(
                    "Stop tracking", callback_data=f"untrack:{tracking.search.id}"
                )
            ],
        ]
    )
    try:
        await application.bot.send_message(
            tracking.search.user_id,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    except RetryAfter as exc:
        delay = exc.retry_after
        await asyncio.sleep(
            delay.total_seconds() if isinstance(delay, timedelta) else delay
        )
        if await application.bot_data["tracking"].storage.active(tracking.id):
            await application.bot.send_message(
                tracking.search.user_id,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )


async def check_tracked_searches(application: Application) -> None:
    """Isolate failures so an unavailable search or blocked bot cannot stop others."""
    service: TrackingService = application.bot_data["tracking"]

    async def notify(tracking: TrackedSearch, vacancy: Vacancy) -> None:
        await send_alert(application, tracking, vacancy)

    for tracking in await service.storage.due(datetime.now(UTC)):
        try:
            await service.check(tracking, notify)
        except Forbidden:
            await service.storage.disable(
                tracking.search.user_id, tracking.search.id, tracking_id=tracking.id
            )
            logger.info("Tracking stopped because Telegram delivery is forbidden.")
        except SourceError, TelegramError, sqlite3.Error, OSError:
            logger.warning("Tracked search failed; retrying in 30 minutes.")
            await service.storage.defer(tracking.id, datetime.now(UTC))


async def tracking_worker(application: Application) -> None:
    """Resume due work after startup; only completed scans wait another 30 minutes."""
    while True:
        try:
            await check_tracked_searches(application)
        except sqlite3.Error, OSError:
            logger.warning("Tracking storage is unavailable; the worker will retry.")
        except Exception:
            # Deliberate task boundary: keep scheduling after unexpected failures,
            # without logging exceptions that may contain credentials or filters.
            logger.error("Unexpected tracking worker failure; the worker will retry.")
        await asyncio.sleep(WORKER_INTERVAL_SECONDS)
