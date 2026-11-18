"""Offline subscription ownership, scheduling, restart, and alert delivery tests."""

import asyncio
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import Forbidden, NetworkError, RetryAfter
from test_saved_searches import private_update, saved_context

from job_bot.models import TrackedSearch, Vacancy, VacancyPage
from job_bot.services.tracking import PAGES_PER_TURN, TrackingService
from job_bot.sources.http_client import SourceFetchError, SourceMarkupError
from job_bot.storage import TRACK_INTERVAL, SavedSearchStorage, TrackingStorage
from job_bot.telegram import handlers
from job_bot.telegram import tracking as alerts
from job_bot.telegram.categories import category_picker


def vacancy(identifier: str, title: str = "Python <Developer> & SQL") -> Vacancy:
    return Vacancy(
        "djinni",
        identifier,
        f"https://djinni.co/jobs/{identifier}/",
        title,
        remote=True,
    )


def tracking_context(path: Path) -> MagicMock:
    context = saved_context(path)
    context.args = []
    context.application.bot = MagicMock()
    context.application.bot.send_message = AsyncMock()
    context.application.bot_data["tracking"] = TrackingService(
        context.application.bot_data["job_search"], TrackingStorage(path)
    )
    return context


async def subscription(
    context: MagicMock, *, owner: int = 42, keyword: str = "Python"
) -> TrackedSearch:
    saved = await context.application.bot_data["saved_searches"].save(
        owner, "djinni", keyword, ("Python",)
    )
    storage = context.application.bot_data["tracking"].storage
    await storage.enable(owner, saved.id)
    return next(
        t for t in await storage.due(datetime.now(UTC)) if t.search.id == saved.id
    )


def test_enable_is_owned_idempotent_and_persistent(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    context = tracking_context(path)

    async def scenario() -> None:
        first = await subscription(context)
        storage = TrackingStorage(path)
        assert await storage.enable(99, first.search.id) is None
        assert not await storage.disable(99, first.search.id)
        assert await storage.enable(42, first.search.id) == first.search
        assert await storage.due(datetime.now(UTC)) == [first]
        saved = await SavedSearchStorage(path).list_for_user(42)
        assert saved[0].tracked
        assert await storage.disable(42, first.search.id)
        assert not await storage.disable(42, first.search.id)
        assert await storage.due(datetime.now(UTC)) == []
        saved = await SavedSearchStorage(path).get_for_user(42, first.search.id)
        assert saved is not None and not saved.tracked
        await storage.enable(42, saved.id)
        restarted = (await storage.due(datetime.now(UTC)))[0]
        assert restarted.id != first.id
        assert not restarted.initialized
        assert not await storage.disable(42, saved.id, tracking_id=first.id)
        assert await storage.active(restarted.id)
        # An old in-flight check must not affect a newly enabled subscription.
        await storage.record_page(first, (vacancy("1"),), None, datetime.now(UTC))
        assert await storage.pending(restarted.id) == []

    asyncio.run(scenario())


def test_baseline_empty_results_new_matches_and_restart_dedup(tmp_path: Path) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        tracked = await subscription(context)
        service = context.application.bot_data["tracking"]
        notify = AsyncMock()
        await service.check(tracked, notify)  # Empty initial baseline is successful.
        notify.assert_not_called()
        assert await service.storage.due(datetime.now(UTC)) == []
        assert (
            await service.storage.due(datetime.now(UTC) + timedelta(minutes=29)) == []
        )
        due = await service.storage.due(datetime.now(UTC) + TRACK_INTERVAL)
        assert len(due) == 1 and due[0].initialized
        service.search.search.return_value = VacancyPage((vacancy("1"), vacancy("1")))
        await service.check(due[0], notify)
        assert notify.await_count == 1
        service.search.search.assert_awaited_with("Python", 1, categories=("Python",))
        service = TrackingService(service.search, TrackingStorage(service.storage.path))
        due = await service.storage.due(datetime.now(UTC) + TRACK_INTERVAL)
        await service.check(due[0], notify)
        assert notify.await_count == 1
        assert await service.storage.pending(tracked.id) == []

    asyncio.run(scenario())


def test_paginated_baseline_resumes_then_detects_new_ids_on_later_pages(
    tmp_path: Path,
) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        tracked = await subscription(context)
        service = context.application.bot_data["tracking"]
        notify = AsyncMock()
        service.search.search.side_effect = [
            VacancyPage((vacancy(str(i)),), i + 1) for i in range(1, PAGES_PER_TURN + 1)
        ]
        await service.check(tracked, notify)
        notify.assert_not_called()
        service = TrackingService(service.search, TrackingStorage(service.storage.path))
        continuation = (await service.storage.due(datetime.now(UTC)))[0]
        assert continuation.next_page == PAGES_PER_TURN + 1
        assert not continuation.initialized
        service.search.search.side_effect = None
        service.search.search.return_value = VacancyPage((vacancy("end"),))
        await service.check(continuation, notify)
        notify.assert_not_called()
        assert await service.storage.due(datetime.now(UTC)) == []
        due = (await service.storage.due(datetime.now(UTC) + TRACK_INTERVAL))[0]
        service.search.search.side_effect = [
            VacancyPage((vacancy("1"), vacancy("1")), 2),
            VacancyPage((vacancy("end"), vacancy("new"))),
        ]
        await service.check(due, notify)
        assert notify.await_count == 1
        assert notify.await_args.args[0].next_page == 2
        assert notify.await_args.args[1].source_id == "new"

    asyncio.run(scenario())


def test_source_failure_does_not_become_baseline_or_block_other_searches(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        first = await subscription(context)
        second = await subscription(context, owner=99)
        service = context.application.bot_data["tracking"]
        service.search.search.side_effect = [
            SourceFetchError("private filter or credential"),
            VacancyPage(()),
        ]
        await alerts.check_tracked_searches(context.application)
        due = await service.storage.due(datetime.now(UTC) + TRACK_INTERVAL)
        assert [(t.id, t.initialized) for t in due] == [
            (first.id, False),
            (second.id, True),
        ]
        assert await service.storage.due(datetime.now(UTC)) == []
        assert "private filter" not in caplog.text

    asyncio.run(scenario())


def test_failed_delivery_is_retried_after_restart_without_losing_other_alerts(
    tmp_path: Path,
) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        tracked = await subscription(context)
        service = context.application.bot_data["tracking"]
        now = datetime.now(UTC)
        await service.storage.record_page(tracked, (), None, now - TRACK_INTERVAL)
        tracked = (await service.storage.due(now))[0]
        matches = tuple(vacancy(str(i)) for i in range(8))
        service.search.search.return_value = VacancyPage(matches)
        notify = AsyncMock(side_effect=[None, NetworkError("offline")])
        with pytest.raises(NetworkError):
            await service.check(tracked, notify)
        assert [
            v.source_id for v in await service.storage.pending(tracked.id, limit=10)
        ] == [str(i) for i in range(1, 8)]
        restarted = TrackingService(
            service.search, TrackingStorage(service.storage.path)
        )
        notify = AsyncMock()
        due = (await restarted.storage.due(datetime.now(UTC) + TRACK_INTERVAL))[0]
        await restarted.check(due, notify)
        assert [call.args[1].source_id for call in notify.await_args_list] == [
            str(i) for i in range(1, 8)
        ]
        assert await restarted.storage.pending(tracked.id) == []

    asyncio.run(scenario())


def test_untrack_and_delete_discard_queued_alerts_and_stop_inflight_scan(
    tmp_path: Path,
) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        tracked = await subscription(context)
        service = context.application.bot_data["tracking"]
        now = datetime.now(UTC)
        await service.storage.record_page(tracked, (), None, now - TRACK_INTERVAL)
        tracked = (await service.storage.due(now))[0]
        await service.storage.record_page(tracked, (vacancy("1"),), None, now)
        await context.application.bot_data["saved_searches"].delete_for_user(
            42, tracked.search.id
        )
        assert not await service.storage.active(tracked.id)
        assert await service.storage.pending(tracked.id) == []
        service.search.search.reset_mock()
        await service.check(tracked, AsyncMock())
        service.search.search.assert_not_called()
        tracked = await subscription(context)
        await service.storage.disable(42, tracked.search.id)
        await service.storage.record_page(tracked, (vacancy("2"),), None, now)
        assert await service.storage.pending(tracked.id) == []

    asyncio.run(scenario())
    with closing(sqlite3.connect(tmp_path / "jobs.sqlite3")) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM tracked_matches"
        ).fetchone() == (0,)


@pytest.mark.parametrize("categories", [False, True])
def test_track_new_saves_first_and_reuses_wizard(
    tmp_path: Path,
    categories: bool,
) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")
    context.args = ["new"]

    async def scenario() -> None:
        await handlers.track_search(private_update("/track new"), context)
        state = context.user_data["search_sessions"][42]
        assert state.intent == "track"
        await handlers.select_source(
            private_update(data=f"source:djinni:{state.token}"), context
        )
        await handlers.search_keyword(private_update("<Python> & SQL"), context)
        update = private_update(
            data=f"categories:{state.token}:{'yes' if categories else 'no'}"
        )
        await handlers.choose_categories(update, context)
        if categories:
            assert "Save & track" in category_picker(state)[0]
            for action in ("g", "t", "d"):
                state = context.user_data["search_sessions"][42]
                update = private_update(data=state.category_callback(action, 0))
                await handlers.select_categories(update, context)
        saved = await context.application.bot_data["saved_searches"].list_for_user(42)
        assert len(saved) == 1 and saved[0].tracked
        assert saved[0].keyword == "<Python> & SQL"
        assert saved[0].categories == (("JavaScript",) if categories else ())
        assert 42 not in context.user_data["search_sessions"]
        context.application.bot_data["job_search"].search.assert_not_called()
        text = update.effective_message.reply_text.await_args.args[0]
        assert "saved and tracked" in text and "30 minutes" in text
        assert "&lt;Python&gt; &amp; SQL" in text

    asyncio.run(scenario())


def test_track_saved_and_untrack_commands_and_buttons(tmp_path: Path) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        store = context.application.bot_data["saved_searches"]
        saved = await store.save(42, "djinni", "Python", ())
        context.args = [str(saved.id)]
        await handlers.track_search(private_update("/track"), context)
        assert (await store.get_for_user(42, saved.id)).tracked
        other = private_update(data=f"untrack:{saved.id}", owner=99)
        await handlers.untrack_search(other, context)
        assert "unavailable" in other.effective_message.reply_text.await_args.args[0]
        assert (await store.get_for_user(42, saved.id)).tracked
        await handlers.untrack_search(
            private_update(data=f"untrack:{saved.id}"), context
        )
        assert not (await store.get_for_user(42, saved.id)).tracked
        await handlers.track_search(private_update(data=f"track:{saved.id}"), context)
        await handlers.untrack_search(private_update("/untrack"), context)
        assert not (await store.get_for_user(42, saved.id)).tracked

    asyncio.run(scenario())


def test_tracking_failure_after_save_keeps_wizard_retryable(tmp_path: Path) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")
    context.args = ["new"]

    async def scenario() -> None:
        await handlers.track_search(private_update("/track new"), context)
        state = context.user_data["search_sessions"][42]
        await handlers.select_source(
            private_update(data=f"source:djinni:{state.token}"), context
        )
        await handlers.skip_keyword(private_update(data=f"skip:{state.token}"), context)
        service = context.application.bot_data["tracking"]
        storage = service.storage
        service.storage = MagicMock()
        service.storage.enable = AsyncMock(
            side_effect=sqlite3.OperationalError("private")
        )
        update = private_update(data=f"categories:{state.token}:no")
        await handlers.choose_categories(update, context)
        assert context.user_data["search_sessions"][42].stage == "ready_to_save"
        saved = await context.application.bot_data["saved_searches"].list_for_user(42)
        assert len(saved) == 1 and not saved[0].tracked
        assert "Try again" in update.effective_message.reply_text.await_args.args[0]
        service.storage = storage
        await handlers.retry_save(
            private_update(data=f"savesearch:{state.token}"), context
        )
        saved = await context.application.bot_data["saved_searches"].list_for_user(42)
        assert len(saved) == 1 and saved[0].tracked
        assert 42 not in context.user_data["search_sessions"]

    asyncio.run(scenario())


def test_check_is_due_exactly_30_minutes_after_scan_completion(tmp_path: Path) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        tracked = await subscription(context)
        storage = context.application.bot_data["tracking"].storage
        completed = datetime(2026, 11, 17, 12, tzinfo=UTC)
        await storage.record_page(tracked, (), None, completed)
        assert (
            await storage.due(completed + TRACK_INTERVAL - timedelta(microseconds=1))
            == []
        )
        due = await storage.due(completed + TRACK_INTERVAL)
        assert len(due) == 1 and due[0].initialized and due[0].next_page == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("argument", ["0", "-1", "abc", "９", str(2**63), "9" * 100])
def test_tracking_rejects_invalid_ids(
    tmp_path: Path, enabled: bool, argument: str
) -> None:
    context = tracking_context(tmp_path / "unused.sqlite3")
    context.args = [argument]
    callback = handlers.track_search if enabled else handlers.untrack_search
    update = private_update("/track")
    asyncio.run(callback(update, context))
    assert "saved search ID" in update.effective_message.reply_text.await_args.args[0]
    assert not (tmp_path / "unused.sqlite3").exists()


def test_tracking_menu_and_private_only(tmp_path: Path) -> None:
    context = tracking_context(tmp_path / "unused.sqlite3")
    update = private_update("/track")
    asyncio.run(handlers.track_search(update, context))
    markup = update.effective_message.reply_text.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[1][0].callback_data == "track:new"
    update.effective_chat.type = "group"
    context.args = ["new"]
    asyncio.run(handlers.track_search(update, context))
    assert "private chat" in update.effective_message.reply_text.await_args.args[0]
    assert not context.user_data


def test_repeated_pagination_is_a_failure(tmp_path: Path) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        tracked = await subscription(context)
        service = context.application.bot_data["tracking"]
        service.search.search.return_value = VacancyPage((), 1)
        with pytest.raises(SourceMarkupError):
            await service.check(tracked, AsyncMock())
        assert not (await service.storage.due(datetime.now(UTC)))[0].initialized

    asyncio.run(scenario())


def test_alert_formatting_retry_after_and_blocked_bot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")
    sleep = AsyncMock()
    monkeypatch.setattr(alerts.asyncio, "sleep", sleep)

    async def scenario() -> None:
        tracked = await subscription(context)
        context.application.bot.send_message.side_effect = [
            RetryAfter(timedelta(seconds=2)),
            None,
        ]
        await alerts.send_alert(context.application, tracked, vacancy("1"))
        call = context.application.bot.send_message.await_args
        assert call.args[0] == 42
        assert "&lt;Developer&gt; &amp; SQL" in call.args[1]
        assert call.kwargs["reply_markup"].inline_keyboard[0][0].url == vacancy("1").url
        assert any(call.args == (2,) for call in sleep.await_args_list)
        service = context.application.bot_data["tracking"]
        now = datetime.now(UTC)
        await service.storage.record_page(tracked, (), None, now - TRACK_INTERVAL)
        service.search.search.return_value = VacancyPage((vacancy("new"),))
        context.application.bot.send_message.side_effect = Forbidden("bot blocked")
        await alerts.check_tracked_searches(context.application)
        assert not await service.storage.active(tracked.id)
        assert await context.application.bot_data["saved_searches"].get_for_user(
            42, tracked.search.id
        )

    asyncio.run(scenario())


def test_cancellation_propagates_from_check(tmp_path: Path) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        await subscription(context)
        context.application.bot_data[
            "job_search"
        ].search.side_effect = asyncio.CancelledError
        with pytest.raises(asyncio.CancelledError):
            await alerts.check_tracked_searches(context.application)

    asyncio.run(scenario())
