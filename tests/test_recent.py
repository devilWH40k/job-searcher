"""Private discovery history from manual searches and tracking, entirely offline."""

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_saved_searches import private_update, saved_context
from test_tracking import subscription, tracking_context, vacancy

from job_bot.models import VacancyPage
from job_bot.sources.http_client import SourceFetchError
from job_bot.storage import TRACK_INTERVAL, RecentVacancyStorage
from job_bot.telegram import handlers
from job_bot.telegram.search_state import SearchSession


def test_recent_storage_orders_discoveries_deduplicates_and_checks_owner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data/jobs.sqlite3"

    async def scenario() -> None:
        store = RecentVacancyStorage(path)
        assert await store.list_for_user(42) == []
        original = tuple(vacancy(str(i)) for i in range(8))
        await store.record(42, original)
        # Preserve source order within each newly discovered batch.
        assert [v.source_id for v in await store.list_for_user(42)] == [
            str(i) for i in range(6)
        ]
        await store.record(99, (vacancy("other-user"),))
        newest = vacancy("new")
        await store.record(42, (newest, original[0], newest))
        updated = replace(original[0], title="Updated & still known", remote=None)
        await store.record(42, (updated,))
        restarted = RecentVacancyStorage(path)
        recent = await restarted.list_for_user(42)
        assert [v.source_id for v in recent] == ["new", "0", "1", "2", "3", "4"]
        assert recent[1] == updated
        assert [v.source_id for v in await restarted.list_for_user(99)] == [
            "other-user"
        ]
        assert await restarted.list_for_user(123) == []
        # Source participates in uniqueness, even if numeric IDs match.
        other_source = replace(newest, source="work.ua")
        await restarted.record(42, (other_source,))
        recent = await restarted.list_for_user(42)
        assert [(v.source, v.source_id) for v in recent[:2]] == [
            ("work.ua", "new"),
            ("djinni", "new"),
        ]

    asyncio.run(scenario())
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute("SELECT found_at FROM recent_vacancies").fetchall()
    assert rows and all(datetime.fromisoformat(row[0]).tzinfo == UTC for row in rows)


def test_recent_roundtrip_preserves_fields_and_normalizes_timestamps(
    tmp_path: Path,
) -> None:
    store = RecentVacancyStorage(tmp_path / "jobs.sqlite3")
    local_time = datetime(2026, 11, 18, 15, tzinfo=timezone(timedelta(hours=2)))
    original = replace(
        vacancy("123"),
        company="Компанія <R&D>",
        location="Україна",
        salary_text="50 000 – 75 000 грн",
        remote=None,
        published_at=local_time,
        first_seen_at=local_time,
        views=0,
        applications=4,
        applications_period_days=30,
        updated_text="оновлено сьогодні",
    )

    async def scenario() -> None:
        await store.record(42, (original,))
        restored = (await store.list_for_user(42))[0]
        assert restored == original
        assert restored.published_at.tzinfo == UTC
        assert restored.first_seen_at.tzinfo == UTC

    asyncio.run(scenario())


@pytest.mark.parametrize("with_keyword", [False, True])
def test_search_command_finds_results_for_recent_and_recent_preserves_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_keyword: bool,
) -> None:
    context = saved_context(tmp_path / "jobs.sqlite3")
    context.args = ["Python", "Developer"] if with_keyword else []
    matches = tuple(vacancy(str(i)) for i in range(8))
    context.application.bot_data["job_search"].search.return_value = VacancyPage(
        matches
    )
    monkeypatch.setattr(handlers, "CARD_INTERVAL_SECONDS", 0)

    async def scenario() -> None:
        await handlers.search_command(private_update("/search"), context)
        if not with_keyword:
            context.application.bot_data["job_search"].search.assert_not_called()
            await handlers.select_source(private_update(data="source:djinni"), context)
            await handlers.search_keyword(private_update("Python Developer"), context)
            state = context.user_data["search_sessions"][42]
            await handlers.choose_categories(
                private_update(data=f"categories:{state.token}:no"), context
            )
        state = context.user_data["search_sessions"][42]
        pending = list(state.pending)
        version = state.version
        source = context.application.bot_data["job_search"]
        source.search.assert_awaited_once_with("Python Developer", 1, categories=())
        context.args = []
        update = private_update("/recent")
        await handlers.recent_vacancies(update, context)
        assert update.effective_message.reply_text.await_count == 6
        links = [
            call.kwargs["reply_markup"].inline_keyboard[0][0].url
            for call in update.effective_message.reply_text.await_args_list
        ]
        assert links == [v.url for v in matches[:6]]
        for call in update.effective_message.reply_text.await_args_list:
            assert "&lt;Developer&gt; &amp; SQL" in call.args[0]
            assert call.kwargs["parse_mode"] == "HTML"
        assert state.pending == pending and state.version == version
        assert source.search.await_count == 1

    asyncio.run(scenario())


def test_cached_results_belong_to_each_searching_user_and_load_more_is_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = saved_context(tmp_path / "jobs.sqlite3")
    context.args = ["Python"]
    source = context.application.bot_data["job_search"]
    first = tuple(vacancy(str(i)) for i in range(6))
    source.search.return_value = VacancyPage(first, 2)
    monkeypatch.setattr(handlers, "CARD_INTERVAL_SECONDS", 0)

    async def scenario() -> None:
        await handlers.search_command(private_update("/search Python"), context)
        # The same cached page still needs an association with its next user.
        await handlers.search_command(
            private_update("/search Python", owner=99), context
        )
        store = context.application.bot_data["recent_vacancies"]
        assert await store.list_for_user(99) == list(first)
        state = context.user_data["search_sessions"][42]
        later = vacancy("later-page")
        source.search.return_value = VacancyPage((later,))
        await handlers.load_more(private_update(data=state.more_callback), context)
        assert (await store.list_for_user(42))[0] == later
        assert await store.list_for_user(99) == list(first)

    asyncio.run(scenario())


def test_recent_combines_baseline_tracking_and_manual_discoveries(
    tmp_path: Path,
) -> None:
    context = tracking_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        tracked = await subscription(context)
        service = context.application.bot_data["tracking"]
        old = vacancy("baseline")
        service.search.search.return_value = VacancyPage((old,))
        notify = AsyncMock()
        await service.check(tracked, notify)
        notify.assert_not_called()
        history = context.application.bot_data["recent_vacancies"]
        assert await history.list_for_user(42) == [old]
        manual = vacancy("manual")
        await history.record(42, (manual,))
        tracked = (await service.storage.due(datetime.now(UTC) + TRACK_INTERVAL))[0]
        new = vacancy("tracked-new")
        service.search.search.return_value = VacancyPage((new, old, manual))
        await service.check(tracked, notify)
        assert [v.source_id for v in await history.list_for_user(42)] == [
            "tracked-new",
            "manual",
            "baseline",
        ]
        # Untracking and deleting filters do not remove discovery history.
        await service.storage.disable(42, tracked.search.id)
        await context.application.bot_data["saved_searches"].delete_for_user(
            42, tracked.search.id
        )
        assert len(await history.list_for_user(42)) == 3

    asyncio.run(scenario())


def test_recent_empty_private_only_and_helpful_storage_failure(tmp_path: Path) -> None:
    context = saved_context(tmp_path / "jobs.sqlite3")
    context.args = []

    async def scenario() -> None:
        update = private_update("/recent")
        await handlers.recent_vacancies(update, context)
        assert (
            "No recent vacancies"
            in update.effective_message.reply_text.await_args.args[0]
        )
        context.application.bot_data["job_search"].search.assert_not_called()
        failing = MagicMock()
        failing.list_for_user = AsyncMock(
            side_effect=sqlite3.OperationalError("private SQL")
        )
        context.application.bot_data["recent_vacancies"] = failing
        update = private_update("/recent")
        update.effective_chat.type = "supergroup"
        await handlers.recent_vacancies(update, context)
        assert "private chat" in update.effective_message.reply_text.await_args.args[0]
        failing.list_for_user.assert_not_called()
        update = private_update("/recent")
        await handlers.recent_vacancies(update, context)
        text = update.effective_message.reply_text.await_args.args[0]
        assert "Try /recent again" in text and "private SQL" not in text

    asyncio.run(scenario())


def test_failed_search_does_not_change_recent_or_active_setup_on_invalid_input(
    tmp_path: Path,
) -> None:
    context = saved_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        history = context.application.bot_data["recent_vacancies"]
        original = vacancy("previous")
        await history.record(42, (original,))
        state = SearchSession(intent="track", stage="keyword")
        context.user_data["search_sessions"] = {42: state}
        context.args = ["!!!"]
        await handlers.search_command(private_update("/search !!!"), context)
        assert context.user_data["search_sessions"][42] is state
        context.args = ["Python"]
        context.application.bot_data[
            "job_search"
        ].search.side_effect = SourceFetchError("offline")
        await handlers.search_command(private_update("/search Python"), context)
        assert await history.list_for_user(42) == [original]
        context.args = ["extra"]
        update = private_update("/recent extra")
        await handlers.recent_vacancies(update, context)
        assert (
            "without arguments"
            in update.effective_message.reply_text.await_args.args[0]
        )

    asyncio.run(scenario())
