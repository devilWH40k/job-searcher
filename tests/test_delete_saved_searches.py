"""Owned deletion, persistent removal, stale cards, and safe failure handling."""

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest
from test_saved_searches import private_update, saved_context

from job_bot.storage import SavedSearchStorage
from job_bot.telegram import handlers
from job_bot.telegram.search_state import SearchSession


def test_deletion_is_persistent_scoped_and_repeatable(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"

    async def scenario() -> None:
        store = SavedSearchStorage(path)
        mine = await store.save(42, "djinni", "Python", ())
        other = await store.save(99, "djinni", "QA", ())
        assert not await store.delete_for_user(99, mine.id)
        assert await store.get_for_user(42, mine.id) == mine
        assert await store.delete_for_user(42, mine.id)
        assert not await store.delete_for_user(42, mine.id)
        restarted = SavedSearchStorage(path)
        assert await restarted.list_for_user(42) == []
        assert await restarted.list_for_user(99) == [other]

    asyncio.run(scenario())


def test_delete_card_then_list_empty_and_old_run_unavailable(tmp_path: Path) -> None:
    context = saved_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        saved = await context.application.bot_data["saved_searches"].save(
            42, "djinni", "Python", ()
        )
        state = SearchSession(keyword="Python", stage="results")
        context.user_data["search_sessions"] = {42: state}
        update = private_update(data=f"saveddelete:{saved.id}")
        await handlers.delete_saved_search(update, context)
        edit = update.callback_query.edit_message_text.await_args
        assert "deleted" in edit.args[0]
        assert (
            edit.kwargs["reply_markup"].inline_keyboard[0][0].callback_data
            == "savedlist:0"
        )
        assert context.user_data["search_sessions"][42] is state
        run = private_update(data=f"savedrun:{saved.id}")
        await handlers.run_saved_search(run, context)
        assert "unavailable" in run.effective_message.reply_text.await_args.args[0]
        listing = private_update("/list")
        await handlers.list_searches(listing, context)
        assert (
            "No saved searches"
            in listing.effective_message.reply_text.await_args.args[0]
        )
        await handlers.delete_saved_search(update, context)
        assert (
            "already deleted" in update.effective_message.reply_text.await_args.args[0]
        )
        context.application.bot_data["job_search"].search.assert_not_called()

    asyncio.run(scenario())


@pytest.mark.parametrize("group", [False, True])
def test_other_user_and_group_cannot_delete(tmp_path: Path, group: bool) -> None:
    context = saved_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        store = context.application.bot_data["saved_searches"]
        saved = await store.save(42, "djinni", "Python", ())
        update = private_update(
            data=f"saveddelete:{saved.id}", owner=42 if group else 99
        )
        if group:
            update.effective_chat.type = "group"
        await handlers.delete_saved_search(update, context)
        assert await store.get_for_user(42, saved.id) == saved
        update.callback_query.edit_message_text.assert_not_called()

    asyncio.run(scenario())


def test_failed_delete_keeps_record_and_does_not_expose_errors(tmp_path: Path) -> None:
    context = saved_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        store = context.application.bot_data["saved_searches"]
        saved = await store.save(42, "djinni", "Python", ())
        failing = MagicMock()
        failing.delete_for_user = AsyncMock(
            side_effect=sqlite3.OperationalError("private database details")
        )
        context.application.bot_data["saved_searches"] = failing
        update = private_update(data=f"saveddelete:{saved.id}")
        await handlers.delete_saved_search(update, context)
        text = update.effective_message.reply_text.await_args.args[0]
        assert "couldn't delete" in text and "private database" not in text
        assert await store.get_for_user(42, saved.id) == saved
        update.callback_query.edit_message_text.assert_not_called()

    asyncio.run(scenario())


def test_edit_failure_still_reports_successful_deletion(tmp_path: Path) -> None:
    context = saved_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        store = context.application.bot_data["saved_searches"]
        saved = await store.save(42, "djinni", "Python", ())
        update = private_update(data=f"saveddelete:{saved.id}")
        update.callback_query.edit_message_text.side_effect = BadRequest(
            "message can't be edited"
        )
        await handlers.delete_saved_search(update, context)
        assert await store.get_for_user(42, saved.id) is None
        assert "deleted" in update.effective_message.reply_text.await_args.args[0]

    asyncio.run(scenario())


@pytest.mark.parametrize("suffix", ["", "abc", "-1", "9" * 30, str(2**63)])
def test_invalid_delete_callbacks_do_not_touch_storage(suffix: str) -> None:
    context = MagicMock()
    update = private_update(data=f"saveddelete:{suffix}")
    asyncio.run(handlers.delete_saved_search(update, context))
    assert "unavailable" in update.callback_query.answer.await_args.args[0]
    context.application.bot_data.__getitem__.assert_not_called()
