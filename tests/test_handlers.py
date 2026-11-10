"""Offline command, rate limit, cancellation, and error handling tests."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Update
from telegram.error import Conflict, NetworkError, RetryAfter

from job_bot.telegram import handlers


@pytest.mark.parametrize(
    ("callback", "expected"),
    [
        (handlers.help_command, handlers.HELP_TEXT),
        (handlers.unknown_command, handlers.UNKNOWN_COMMAND_TEXT),
    ],
)
def test_commands_reply_with_plain_text(
    callback: Callable[..., Awaitable[None]], expected: str
) -> None:
    update = MagicMock(spec=Update)
    update.effective_message.reply_text = AsyncMock()

    asyncio.run(callback(update, MagicMock()))

    update.effective_message.reply_text.assert_awaited_once_with(
        expected, parse_mode=None, reply_markup=None
    )
    assert len(expected) < 4096


def test_update_without_message_is_ignored() -> None:
    update = MagicMock(spec=Update)
    update.effective_message = None
    asyncio.run(handlers.start(update, MagicMock()))


@pytest.mark.parametrize("delay", [2, timedelta(seconds=2)])
def test_rate_limit_waits_before_retry(
    delay: int | timedelta, monkeypatch: pytest.MonkeyPatch
) -> None:
    update = MagicMock(spec=Update)
    update.effective_message.reply_text = AsyncMock(
        side_effect=[RetryAfter(delay), None]
    )
    sleep = AsyncMock()
    monkeypatch.setattr(handlers.asyncio, "sleep", sleep)

    asyncio.run(handlers.help_command(update, MagicMock()))

    sleep.assert_awaited_once_with(2)
    assert update.effective_message.reply_text.await_count == 2


def test_cancellation_is_not_swallowed() -> None:
    update = MagicMock(spec=Update)
    update.effective_message.reply_text = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(handlers.help_command(update, MagicMock()))


def test_network_error_does_not_log_private_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    update = MagicMock(spec=Update)
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()
    context.error = NetworkError(
        "https://api.telegram.org/bot123456:secret/private-message"
    )

    with caplog.at_level(logging.WARNING, logger="job_bot"):
        asyncio.run(handlers.on_error(update, context))

    update.effective_message.reply_text.assert_awaited_once_with(
        handlers.ERROR_TEXT, parse_mode=None, reply_markup=None
    )
    assert "NetworkError" in caplog.text
    assert "secret" not in caplog.text
    assert "private-message" not in caplog.text


def test_polling_failure_has_no_chat_reply(caplog: pytest.LogCaptureFixture) -> None:
    context = MagicMock()
    context.error = NetworkError("private network details")

    asyncio.run(handlers.on_error(None, context))

    assert "retrying" in caplog.text
    assert "private network details" not in caplog.text
    context.application.stop_running.assert_not_called()


def test_conflicting_poller_is_stopped() -> None:
    context = MagicMock()
    context.error = Conflict("private error details")

    asyncio.run(handlers.on_error(None, context))

    context.application.stop_running.assert_called_once_with()
