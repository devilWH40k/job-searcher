"""Persistent owned filters, the shared wizard, list cards, and saved-search reuse."""

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import closing
from datetime import UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_search_flow import make_context, make_update

from job_bot.models import Vacancy, VacancyPage
from job_bot.storage import SavedSearchStorage, VacancyStorage
from job_bot.telegram import handlers
from job_bot.telegram.formatting import format_saved_search


def private_update(
    text: str | None = None, data: str | None = None, *, owner: int = 42
) -> MagicMock:
    update = make_update(text, data, chat=owner)
    update.effective_chat.type = "private"
    update.effective_user.id = owner
    if update.callback_query is not None:
        update.callback_query.edit_message_text = AsyncMock()
    return update


def saved_context(path: Path) -> MagicMock:
    context = make_context(VacancyPage(()))
    context.application.bot_data["saved_searches"] = SavedSearchStorage(path)
    return context


async def begin_saved(context: MagicMock, keyword: str = "") -> str:
    await handlers.create_search(private_update("/createsearch"), context)
    state = context.user_data["search_sessions"][42]
    token = state.token
    await handlers.select_source(private_update(data=f"source:djinni:{token}"), context)
    if keyword:
        await handlers.search_keyword(private_update(keyword), context)
    else:
        await handlers.skip_keyword(private_update(data=f"skip:{token}"), context)
    return token


def test_storage_persistence_deduplication_and_owner_scope(tmp_path: Path) -> None:
    path = tmp_path / "existing.sqlite3"

    async def scenario() -> None:
        await VacancyStorage(path).save(
            [Vacancy("djinni", "1", "https://djinni.co/jobs/1/", "Existing")]
        )
        store = SavedSearchStorage(path)
        first = await store.save(
            42, "djinni", "  Python   Developer ", ("Python", "JavaScript")
        )
        duplicate = await store.save(
            42, "djinni", "python developer", ("JavaScript", "Python", "Python")
        )
        assert duplicate == first
        other = await store.save(
            99, "djinni", "Python Developer", ("Python", "JavaScript")
        )
        assert first.id != other.id
        restarted = SavedSearchStorage(path)
        assert await restarted.list_for_user(42) == [first]
        assert await restarted.get_for_user(99, first.id) is None
        assert await restarted.get_for_user(42, other.id) is None
        assert first.created_at.tzinfo == UTC
        assert first.remote_only
        basic = await restarted.save(42, "djinni", "", ())
        assert basic.keyword == "" and not basic.remote_only
        assert await restarted.list_for_user(123) == []

    asyncio.run(scenario())
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM vacancies").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM saved_searches").fetchone() == (
            3,
        )


@pytest.mark.parametrize("keyword", ["", "<Python> & SQL"])
@pytest.mark.parametrize("with_categories", [False, True])
def test_create_wizard_saves_filters_without_fetching(
    tmp_path: Path, keyword: str, with_categories: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = saved_context(tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(handlers, "CARD_INTERVAL_SECONDS", 0)

    async def scenario() -> None:
        token = await begin_saved(context, keyword)
        confirmation = private_update(
            data=f"categories:{token}:{'yes' if with_categories else 'no'}"
        )
        await handlers.choose_categories(confirmation, context)
        if with_categories:
            for action in ("g", "t", "d"):
                state = context.user_data["search_sessions"][42]
                confirmation = private_update(data=state.category_callback(action, 0))
                await handlers.select_categories(confirmation, context)
        context.application.bot_data["job_search"].search.assert_not_called()
        assert 42 not in context.user_data["search_sessions"]
        saved = await context.application.bot_data["saved_searches"].list_for_user(42)
        assert len(saved) == 1
        assert saved[0].keyword == keyword
        assert saved[0].categories == (("JavaScript",) if with_categories else ())
        text = confirmation.effective_message.reply_text.await_args.args[0]
        assert "Search saved" in text
        assert "<Python>" not in text
        if keyword:
            assert "&lt;Python&gt; &amp; SQL" in text
        assert (
            confirmation.effective_message.reply_text.await_args.kwargs["parse_mode"]
            == "HTML"
        )

    asyncio.run(scenario())


def test_empty_list_has_create_command_and_no_source_requests(tmp_path: Path) -> None:
    context = saved_context(tmp_path / "empty.sqlite3")
    update = private_update("/list")
    asyncio.run(handlers.list_searches(update, context))
    text = update.effective_message.reply_text.await_args.args[0]
    assert "No saved searches" in text and "/createsearch" in text
    context.application.bot_data["job_search"].search.assert_not_called()


def test_list_paginates_and_only_shows_own_cards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = saved_context(tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(handlers, "CARD_INTERVAL_SECONDS", 0)

    async def scenario() -> None:
        store = context.application.bot_data["saved_searches"]
        for i in range(8):
            await store.save(42, "djinni", f"Python {i}", ())
        await store.save(99, "djinni", "Private other-user search", ())
        update = private_update("/list")
        await handlers.list_searches(update, context)
        assert update.effective_message.reply_text.await_count == 6
        last = update.effective_message.reply_text.await_args
        actions = last.kwargs["reply_markup"].inline_keyboard[0]
        assert actions[0].callback_data.startswith("savedrun:")
        assert actions[1].callback_data.startswith("saveddelete:")
        assert "Python 2" in last.args[0]
        assert "Created:" in last.args[0]
        markup = last.kwargs["reply_markup"]
        page = private_update(data=markup.inline_keyboard[-1][0].callback_data)
        await handlers.list_searches(page, context)
        assert page.effective_message.reply_text.await_count == 2
        for call in (
            *update.effective_message.reply_text.await_args_list,
            *page.effective_message.reply_text.await_args_list,
        ):
            assert "Private other-user" not in call.args[0]
        context.application.bot_data["job_search"].search.assert_not_called()

    asyncio.run(scenario())


def test_run_after_restart_checks_owner_and_restores_filters(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    context = saved_context(path)

    async def scenario() -> None:
        saved = await context.application.bot_data["saved_searches"].save(
            42, "djinni", "Python", ("Python",)
        )
        restarted = saved_context(path)
        wrong_owner = private_update(data=f"savedrun:{saved.id}", owner=99)
        await handlers.run_saved_search(wrong_owner, restarted)
        restarted.application.bot_data["job_search"].search.assert_not_called()
        assert (
            "unavailable" in wrong_owner.effective_message.reply_text.await_args.args[0]
        )
        correct = private_update(data=f"savedrun:{saved.id}")
        await handlers.run_saved_search(correct, restarted)
        restarted.application.bot_data["job_search"].search.assert_awaited_once_with(
            "Python", 1, categories=("Python",)
        )
        state = restarted.user_data["search_sessions"][42]
        assert state.intent == "search" and state.stage == "results"
        assert state.keyword == "Python" and state.categories == ("Python",)

    asyncio.run(scenario())


@pytest.mark.parametrize("command", [handlers.create_search, handlers.list_searches])
def test_saved_commands_in_group_do_not_expose_or_store_filters(
    command: Callable[..., Awaitable[None]], tmp_path: Path
) -> None:
    context = saved_context(tmp_path / "unused.sqlite3")
    update = private_update("/list")
    update.effective_chat.type = "group"
    asyncio.run(command(update, context))
    assert "private chat" in update.effective_message.reply_text.await_args.args[0]
    assert not (tmp_path / "unused.sqlite3").exists()


def test_save_failure_keeps_filters_retryable_and_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    context = saved_context(tmp_path / "jobs.sqlite3")
    original = context.application.bot_data["saved_searches"]
    failing = MagicMock()
    failing.save = AsyncMock(
        side_effect=sqlite3.OperationalError("private SQL details")
    )

    async def scenario() -> None:
        token = await begin_saved(context, "Python")
        context.application.bot_data["saved_searches"] = failing
        update = private_update(data=f"categories:{token}:no")
        await handlers.choose_categories(update, context)
        state = context.user_data["search_sessions"][42]
        assert state.keyword == "Python" and state.stage == "ready_to_save"
        assert (
            "private SQL" not in update.effective_message.reply_text.await_args.args[0]
        )
        retry = private_update(data=f"savesearch:{token}")
        context.application.bot_data["saved_searches"] = original
        await handlers.retry_save(retry, context)
        await handlers.retry_save(retry, context)
        assert len(await original.list_for_user(42)) == 1
        context.application.bot_data["job_search"].search.assert_not_called()

    asyncio.run(scenario())


def test_finish_cancels_create_and_stale_source_cannot_save(tmp_path: Path) -> None:
    context = saved_context(tmp_path / "jobs.sqlite3")

    async def scenario() -> None:
        await handlers.create_search(private_update("/createsearch"), context)
        state = context.user_data["search_sessions"][42]
        await handlers.finish(private_update("/finish"), context)
        stale = private_update(data=f"source:djinni:{state.token}")
        await handlers.select_source(stale, context)
        stale.effective_message.reply_text.assert_not_called()
        assert (
            await context.application.bot_data["saved_searches"].list_for_user(42) == []
        )

    asyncio.run(scenario())


def test_saved_card_length_and_parameterized_keyword(tmp_path: Path) -> None:
    keyword = "Python'; DROP TABLE saved_searches; -- <&>"

    async def scenario() -> None:
        store = SavedSearchStorage(tmp_path / "jobs.sqlite3")
        saved = await store.save(42, "djinni", keyword, ())
        text = format_saved_search(saved)
        assert "&lt;&amp;&gt;" in text
        assert "Scope: Remote only" in text
        assert len(text.encode("utf-16-le")) // 2 < 4096
        assert await store.list_for_user(42) == [saved]

    asyncio.run(scenario())
