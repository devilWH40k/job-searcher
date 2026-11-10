"""Source selection, per-user cursors, pagination, stale clicks, and input errors."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import CallbackQuery, Message, Update

from job_bot.models import VacancyPage
from job_bot.sources.djinni import parse_search_page
from job_bot.sources.http_client import SourceAccessError, SourceFetchError
from job_bot.telegram import handlers


def make_update(
    text: str | None = None, data: str | None = None, chat: int = 42
) -> MagicMock:
    update = MagicMock(spec=Update)
    update.effective_chat.id = chat
    update.effective_message = MagicMock(spec=Message)
    update.effective_message.text = text
    update.effective_message.reply_text = AsyncMock()
    update.callback_query = None
    if data is not None:
        update.callback_query = MagicMock(spec=CallbackQuery)
        update.callback_query.data = data
        update.callback_query.answer = AsyncMock()
    return update


def make_context(page: VacancyPage) -> MagicMock:
    context = MagicMock()
    context.user_data = {}
    source = MagicMock()
    source.search = AsyncMock(return_value=page)
    context.application.bot_data = {"job_search": source}
    return context


@pytest.fixture
def no_card_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handlers, "CARD_INTERVAL_SECONDS", 0)


def last_more(update: MagicMock) -> str:
    markup = update.effective_message.reply_text.await_args_list[-1].kwargs[
        "reply_markup"
    ]
    return next(
        b.callback_data
        for row in markup.inline_keyboard
        for b in row
        if b.callback_data and b.callback_data.startswith("more:")
    )


def test_source_then_keyword_then_remaining_cards(
    djinni_html: str, no_card_delay: None
) -> None:
    context = make_context(parse_search_page(djinni_html))
    start = make_update("/start")
    source = make_update(data="source:djinni")
    keyword = make_update("Frontend")

    async def scenario() -> None:
        await handlers.start(start, context)
        context.application.bot_data["job_search"].search.assert_not_called()
        picker = start.effective_message.reply_text.await_args.kwargs["reply_markup"]
        assert picker.inline_keyboard[0][0].text == "Djinni"
        await handlers.select_source(source, context)
        source.callback_query.answer.assert_awaited_once()
        await submit_keyword(keyword, context)
        calls = keyword.effective_message.reply_text.await_args_list
        assert len(calls) == 7  # Searching status plus six cards.
        assert all(call.kwargs["parse_mode"] == "HTML" for call in calls[1:])
        callback = last_more(keyword)
        more = make_update(data=callback)
        await handlers.load_more(more, context)
        assert more.effective_message.reply_text.await_count == 3
        assert all(
            len(call.kwargs["reply_markup"].inline_keyboard) == (2 if i == 2 else 1)
            for i, call in enumerate(more.effective_message.reply_text.await_args_list)
        )
        duplicate = make_update(data=callback)
        await handlers.load_more(duplicate, context)
        assert "no longer current" in duplicate.callback_query.answer.await_args.args[0]
        duplicate.effective_message.reply_text.assert_not_called()
        context.application.bot_data["job_search"].search.assert_awaited_once_with(
            "Frontend", 1, categories=()
        )

    asyncio.run(scenario())


def test_more_crosses_source_pages_without_duplicates(no_card_delay: None) -> None:
    root = Path(__file__).parent / "fixtures"
    first = parse_search_page(
        (root / "djinni_python_page1.html").read_text(encoding="utf-8")
    )
    second = parse_search_page(
        (root / "djinni_python_page2.html").read_text(encoding="utf-8"), 2
    )
    context = make_context(first)
    context.application.bot_data["job_search"].search.side_effect = [first, second]
    keyword = make_update("Python")

    async def scenario() -> None:
        await select_source(context)
        await submit_keyword(keyword, context)
        updates = [keyword]
        for _ in range(2):
            more = make_update(data=last_more(updates[-1]))
            await handlers.load_more(more, context)
            updates.append(more)
        links = [
            call.kwargs["reply_markup"].inline_keyboard[0][0].url
            for update in updates
            for call in update.effective_message.reply_text.await_args_list
            if call.kwargs["reply_markup"] is not None
        ]
        expected = list(
            dict.fromkeys(v.url for v in (*first.vacancies, *second.vacancies))
        )[:18]
        assert links == expected
        assert len(set(links)) == 18
        assert [
            call.args
            for call in context.application.bot_data[
                "job_search"
            ].search.await_args_list
        ] == [("Python", 1), ("Python", 2)]

    asyncio.run(scenario())


def test_keyword_requires_source_and_invalid_input_never_fetches() -> None:
    context = make_context(VacancyPage(()))

    async def scenario() -> None:
        update = make_update("Python")
        await handlers.search_keyword(update, context)
        assert "/start" in update.effective_message.reply_text.await_args.args[0]
        await select_source(context)
        await handlers.search_keyword(make_update("!" * 101), context)
        context.application.bot_data["job_search"].search.assert_not_called()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (VacancyPage(()), "No vacancies"),
        (SourceAccessError("private details"), "access is unavailable"),
        (SourceFetchError("private details"), "couldn't load Djinni"),
    ],
)
def test_empty_and_failed_keyword_search(result: object, expected: str) -> None:
    context = make_context(VacancyPage(()))
    search = context.application.bot_data["job_search"].search
    if isinstance(result, Exception):
        search.side_effect = result
    else:
        search.return_value = result
    update = make_update("Python")

    async def scenario() -> None:
        await select_source(context)
        await submit_keyword(update, context)

    asyncio.run(scenario())
    calls = update.effective_message.reply_text.await_args_list
    assert expected in calls[-1].args[0]
    assert "private details" not in calls[-1].args[0]


def test_sessions_are_isolated_and_old_search_buttons_expire(
    djinni_html: str, no_card_delay: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context(parse_search_page(djinni_html))

    async def scenario() -> None:
        await select_source(context)
        first = make_update("Python")
        await submit_keyword(first, context)
        old_button = last_more(first)
        other_user = make_context(parse_search_page(djinni_html))
        await handlers.load_more(make_update(data=old_button), other_user)
        other_user.application.bot_data["job_search"].search.assert_not_called()
        other_chat = make_update("Java", chat=99)
        await handlers.search_keyword(other_chat, context)
        assert "/start" in other_chat.effective_message.reply_text.await_args.args[0]
        await select_source(context)
        await submit_keyword(make_update("Java"), context)
        stale = make_update(data=old_button)
        await handlers.load_more(stale, context)
        stale.effective_message.reply_text.assert_not_called()
        state = context.user_data["search_sessions"][42]
        current_button = state.more_callback
        state.touched_at = 0
        monkeypatch.setattr(handlers, "monotonic", lambda: handlers.SESSION_SECONDS + 1)
        expired = make_update(data=current_button)
        await handlers.load_more(expired, context)
        assert "no longer current" in expired.callback_query.answer.await_args.args[0]

    asyncio.run(scenario())


def test_page_fetch_failure_keeps_load_button_retryable(no_card_delay: None) -> None:
    root = Path(__file__).parent / "fixtures"
    first = parse_search_page(
        (root / "djinni_python_page1.html").read_text(encoding="utf-8")
    )
    second = parse_search_page(
        (root / "djinni_python_page2.html").read_text(encoding="utf-8"), 2
    )
    context = make_context(first)
    context.application.bot_data["job_search"].search.side_effect = [
        first,
        SourceFetchError("offline"),
        second,
    ]

    async def scenario() -> None:
        await select_source(context)
        keyword = make_update("Python")
        await submit_keyword(keyword, context)
        more = make_update(data=last_more(keyword))
        await handlers.load_more(more, context)
        callback = last_more(more)
        failed = make_update(data=callback)
        await handlers.load_more(failed, context)
        assert "couldn't load" in failed.effective_message.reply_text.await_args.args[0]
        state = context.user_data["search_sessions"][42]
        assert state.more_callback == callback
        assert len(state.pending) == 3
        retry = make_update(data=callback)
        await handlers.load_more(retry, context)
        assert retry.effective_message.reply_text.await_count == 6

    asyncio.run(scenario())


def test_a_click_has_a_bounded_page_scan() -> None:
    context = make_context(VacancyPage(()))
    context.application.bot_data["job_search"].search.side_effect = [
        VacancyPage((), 2),
        VacancyPage((), 3),
        VacancyPage((), 4),
    ]

    async def scenario() -> None:
        await select_source(context)
        keyword = make_update("Python")
        await submit_keyword(keyword, context)
        assert last_more(keyword).startswith("more:")
        assert context.application.bot_data["job_search"].search.await_count == 3

    asyncio.run(scenario())


async def select_source(context: MagicMock) -> None:
    await handlers.select_source(make_update(data="source:djinni"), context)


async def category_answer(context: MagicMock, answer: str) -> MagicMock:
    state = context.user_data["search_sessions"][42]
    update = make_update(data=f"categories:{state.token}:{answer}")
    await handlers.choose_categories(update, context)
    return update


async def submit_keyword(update: MagicMock, context: MagicMock) -> None:
    await handlers.search_keyword(update, context)
    state = context.user_data["search_sessions"][42]
    callback = make_update(data=f"categories:{state.token}:no")
    # Keep result assertions attached to the simulated conversation's message.
    callback.effective_message = update.effective_message
    update.effective_message.reply_text.reset_mock()
    await handlers.choose_categories(callback, context)


async def open_categories(context: MagicMock, keyword: str = "") -> MagicMock:
    await select_source(context)
    if keyword:
        await handlers.search_keyword(make_update(keyword), context)
    else:
        state = context.user_data["search_sessions"][42]
        await handlers.skip_keyword(make_update(data=f"skip:{state.token}"), context)
    return await category_answer(context, "yes")


@pytest.mark.parametrize("keyword", ["", "Python"])
def test_no_categories_starts_only_after_confirmation(keyword: str) -> None:
    context = make_context(VacancyPage(()))
    search = context.application.bot_data["job_search"].search

    async def scenario() -> None:
        await select_source(context)
        state = context.user_data["search_sessions"][42]
        skip = make_update(data=f"skip:{state.token}")
        if keyword:
            await handlers.search_keyword(make_update(keyword), context)
        else:
            await handlers.skip_keyword(skip, context)
        assert state.keyword == keyword
        assert state.stage == "category_choice"
        search.assert_not_called()
        await handlers.skip_keyword(skip, context)
        assert "no longer current" in skip.callback_query.answer.await_args.args[0]
        answer = await category_answer(context, "no")
        search.assert_awaited_once_with(keyword or None, 1, categories=())
        assert state.stage == "results"
        assert (
            answer.effective_message.reply_text.await_args.kwargs["reply_markup"]
            .inline_keyboard[-1][0]
            .text
            == "Finish"
        )
        await handlers.choose_categories(answer, context)
        assert search.await_count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("use_command", [False, True])
def test_finish_invalidates_buttons_and_keeps_other_chats(
    use_command: bool, djinni_html: str, no_card_delay: None
) -> None:
    context = make_context(parse_search_page(djinni_html))

    async def scenario() -> None:
        await select_source(context)
        update = make_update("Python")
        await submit_keyword(update, context)
        markup = update.effective_message.reply_text.await_args.kwargs["reply_markup"]
        assert markup.inline_keyboard[-2][0].text == "Load 6 more"
        assert markup.inline_keyboard[-1][0].text == "Finish"
        state = context.user_data["search_sessions"][42]
        old_more = make_update(data=state.more_callback)
        finish_data = f"finish:{state.token}"
        await handlers.select_source(
            make_update(data="source:djinni", chat=99), context
        )
        foreign = make_context(VacancyPage(()))
        foreign_click = make_update(data=finish_data)
        await handlers.finish(foreign_click, foreign)
        foreign_click.effective_message.reply_text.assert_not_called()
        assert context.user_data["search_sessions"][42] is state
        ending = (
            make_update("/finish") if use_command else make_update(data=finish_data)
        )
        await handlers.finish(ending, context)
        assert 42 not in context.user_data["search_sessions"]
        assert 99 in context.user_data["search_sessions"]
        assert (
            handlers.HELP_TEXT in ending.effective_message.reply_text.await_args.args[0]
        )
        await handlers.load_more(old_more, context)
        old_more.effective_message.reply_text.assert_not_called()
        stale = make_update(data=finish_data)
        await handlers.finish(stale, context)
        stale.effective_message.reply_text.assert_not_called()
        assert context.application.bot_data["job_search"].search.await_count == 1

    asyncio.run(scenario())


def test_finish_during_setup_and_without_session() -> None:
    context = make_context(VacancyPage(()))

    async def scenario() -> None:
        await select_source(context)
        await handlers.finish(make_update("/finish"), context)
        assert context.user_data["search_sessions"] == {}
        empty = make_update("/finish")
        await handlers.finish(empty, context)
        assert "/start" in empty.effective_message.reply_text.await_args.args[0]
        context.application.bot_data["job_search"].search.assert_not_called()

    asyncio.run(scenario())
