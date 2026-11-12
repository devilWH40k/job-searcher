"""Category multi-selection, URL encoding, cache separation, and button safety."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from test_search_flow import last_more, make_context, make_update, open_categories

from job_bot.models import SearchInputError, VacancyPage
from job_bot.services.job_search import JobSearchService
from job_bot.sources.djinni import build_search_url, parse_search_page
from job_bot.sources.djinni_categories import (
    CATEGORIES,
    CATEGORY_GROUPS,
    normalize_categories,
)
from job_bot.storage import VacancyStorage
from job_bot.telegram import handlers
from job_bot.telegram.categories import category_picker
from job_bot.telegram.search_state import SearchSession


def test_catalog_preserves_supplied_tree() -> None:
    supplied = json.loads(
        (Path(__file__).parent / "fixtures/djinni_categories.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(CATEGORIES) == 157
    assert len(CATEGORY_GROUPS) == 11
    assert len({c.key for c in CATEGORIES}) == 157
    assert [(c.key, c.label, c.group, c.parent) for c in CATEGORIES] == [
        (c["key"], c["label"], c["group"], c["parent"]) for c in supplied
    ]
    for item in CATEGORIES:
        assert item.parent is None or item.parent in {c.key for c in CATEGORIES}


def test_url_encodes_repeated_keys_and_keeps_page_filters() -> None:
    query = parse_qs(
        urlsplit(
            build_search_url(
                "C++ & UI", 2, categories=("Python", "JavaScript", "C++", "Python")
            )
        ).query
    )
    assert query == {
        "all_keywords": ["C++ & UI"],
        "employment": ["remote"],
        "primary_keyword": ["C++", "JavaScript", "Python"],
        "page": ["2"],
    }


def test_unknown_categories_and_excess_selection_are_rejected() -> None:
    with pytest.raises(SearchInputError):
        normalize_categories(("not-an-official-category",))
    with pytest.raises(SearchInputError):
        normalize_categories(tuple(c.key for c in CATEGORIES[:51]))
    assert len(normalize_categories(tuple(c.key for c in CATEGORIES[:50]))) == 50


def test_every_category_is_reachable_with_short_callbacks() -> None:
    seen = set()
    for group_index, group in enumerate(CATEGORY_GROUPS):
        size = sum(c.group == group for c in CATEGORIES)
        for page in range((size + 9) // 10):
            state = SearchSession(category_group=group_index, category_page=page)
            text, keyboard = category_picker(state)
            assert len(text.encode("utf-16-le")) // 2 < 4096
            for row in keyboard.inline_keyboard:
                for button in row:
                    assert len(button.callback_data.encode("utf-8")) <= 64
                    action, value = button.callback_data.split(":")[-2:]
                    if action == "t":
                        seen.add(int(value))
    assert seen == set(range(len(CATEGORIES)))


def test_category_combinations_have_separate_caches(tmp_path: Path) -> None:
    source = MagicMock()
    source.search = AsyncMock(return_value=VacancyPage(()))
    service = JobSearchService(source, VacancyStorage(tmp_path / "jobs.sqlite3"))

    async def scenario() -> None:
        await service.search("Python", categories=("Python", "JavaScript"))
        await service.search("python", categories=("JavaScript", "Python", "Python"))
        await service.search("Python", categories=("Python",))
        await service.search("Python")
        await service.search("Python", 2, categories=("JavaScript", "Python"))

    asyncio.run(scenario())
    assert source.search.await_count == 4
    assert [c.kwargs["categories"] for c in source.search.await_args_list] == [
        ("JavaScript", "Python"),
        ("Python",),
        (),
        ("JavaScript", "Python"),
    ]


def test_multi_select_across_groups_and_pages_survives_keyword_and_more(
    djinni_html: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context(parse_search_page(djinni_html))
    context.application.bot_data["job_search"].search.side_effect = [
        VacancyPage(parse_search_page(djinni_html).vacancies, 2),
        VacancyPage(()),
    ]
    monkeypatch.setattr(handlers, "CARD_INTERVAL_SECONDS", 0)

    async def click(action: str, value: int = 0) -> MagicMock:
        state = context.user_data["search_sessions"][42]
        update = make_update(data=state.category_callback(action, value))
        update.callback_query.edit_message_text = AsyncMock()
        await handlers.select_categories(update, context)
        return update

    async def scenario() -> None:
        await open_categories(context, "Developer")
        await click("g", 0)
        await click("t", 0)  # JavaScript parent category.
        await click("p", 2)
        python_index = next(i for i, c in enumerate(CATEGORIES) if c.key == "Python")
        await click("t", python_index)
        await click("b")
        await click("g", 1)
        qa_index = next(i for i, c in enumerate(CATEGORIES) if c.key == "QA")
        await click("t", qa_index)
        state = context.user_data["search_sessions"][42]
        assert state.categories == ("JavaScript", "Python", "QA")
        text, keyboard = category_picker(state)
        assert "JavaScript / Front-End" in text
        assert any(
            "✓" in b.text and b.callback_data.endswith(f":t:{qa_index}")
            for row in keyboard.inline_keyboard
            for b in row
        )
        done = await click("d")
        assert (
            done.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
            is None
        )
        context.application.bot_data["job_search"].search.assert_awaited_once_with(
            "Developer", 1, categories=("JavaScript", "Python", "QA")
        )
        assert context.user_data["search_sessions"][42].categories == (
            "JavaScript",
            "Python",
            "QA",
        )
        more = make_update(data=last_more(done))
        await handlers.load_more(more, context)
        assert more.effective_message.reply_text.await_count == 3
        latest = context.application.bot_data["job_search"].search.await_args
        assert latest.args == ("Developer", 2)
        assert latest.kwargs["categories"] == ("JavaScript", "Python", "QA")

    asyncio.run(scenario())


def test_toggle_off_clear_and_stale_or_foreign_buttons() -> None:
    context = make_context(VacancyPage(()))

    async def click(action: str, value: int = 0) -> MagicMock:
        state = context.user_data["search_sessions"][42]
        update = make_update(data=state.category_callback(action, value))
        update.callback_query.edit_message_text = AsyncMock()
        await handlers.select_categories(update, context)
        return update

    async def scenario() -> None:
        await open_categories(context, "Developer")
        await click("g", 0)
        old = await click("t", 0)
        await handlers.select_categories(old, context)
        assert "no longer current" in old.callback_query.answer.await_args.args[0]
        assert context.user_data["search_sessions"][42].categories == ("JavaScript",)
        foreign = make_context(VacancyPage(()))
        await handlers.select_categories(old, foreign)
        foreign.application.bot_data["job_search"].search.assert_not_called()
        await click("t", 0)
        assert context.user_data["search_sessions"][42].categories == ()
        await click("t", 1)
        await click("c")
        assert context.user_data["search_sessions"][42].categories == ()
        empty = await click("d")
        assert "at least one" in empty.callback_query.answer.await_args.args[0]
        await click("t", 0)
        await click("d")
        await handlers.select_categories(old, context)
        assert context.user_data["search_sessions"][42].stage == "results"

    asyncio.run(scenario())


@pytest.mark.parametrize("keyword", ["", "Python"])
def test_categories_run_after_keyword_or_skip(keyword: str) -> None:
    context = make_context(VacancyPage(()))

    async def scenario() -> None:
        menu = await open_categories(context, keyword)
        search = context.application.bot_data["job_search"].search
        search.assert_not_called()
        await handlers.choose_categories(menu, context)
        assert "no longer current" in menu.callback_query.answer.await_args.args[0]
        await handlers.search_keyword(make_update("unexpected"), context)
        search.assert_not_called()
        for action in ("g", "t", "d"):
            state = context.user_data["search_sessions"][42]
            update = make_update(data=state.category_callback(action, 0))
            update.callback_query.edit_message_text = AsyncMock()
            await handlers.select_categories(update, context)
        search.assert_awaited_once_with(keyword or None, 1, categories=("JavaScript",))

    asyncio.run(scenario())


def test_category_only_failure_can_retry_and_load_buffered_cards(
    djinni_html: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from job_bot.sources.http_client import SourceFetchError

    context = make_context(parse_search_page(djinni_html))
    search = context.application.bot_data["job_search"].search
    search.side_effect = [SourceFetchError("offline"), parse_search_page(djinni_html)]
    monkeypatch.setattr(handlers, "CARD_INTERVAL_SECONDS", 0)

    async def scenario() -> None:
        await open_categories(context)
        for action in ("g", "t", "d"):
            state = context.user_data["search_sessions"][42]
            update = make_update(data=state.category_callback(action, 0))
            update.callback_query.edit_message_text = AsyncMock()
            await handlers.select_categories(update, context)
        retry = make_update(data=last_more(update))
        await handlers.load_more(retry, context)
        assert retry.effective_message.reply_text.await_count == 6
        more = make_update(data=last_more(retry))
        await handlers.load_more(more, context)
        assert more.effective_message.reply_text.await_count == 3
        assert search.await_count == 2
        assert all(c.args == (None, 1) for c in search.await_args_list)
        assert all(
            c.kwargs == {"categories": ("JavaScript",)} for c in search.await_args_list
        )

    asyncio.run(scenario())


def test_category_only_url_and_cache_are_distinct(tmp_path: Path) -> None:
    assert parse_qs(urlsplit(build_search_url(categories=("Python",))).query) == {
        "employment": ["remote"],
        "primary_keyword": ["Python"],
    }
    assert build_search_url() == "https://djinni.co/jobs/"
    assert build_search_url(page=2) == "https://djinni.co/jobs/?page=2"
    source = MagicMock()
    source.search = AsyncMock(return_value=VacancyPage(()))
    service = JobSearchService(source, VacancyStorage(tmp_path / "jobs.sqlite3"))

    async def scenario() -> None:
        await service.search(categories=("Python",))
        await service.search(categories=("Python", "Python"))
        await service.search("Python", categories=("Python",))
        await service.search("Python")
        await service.search()
        await service.search()

    asyncio.run(scenario())
    assert [c.args for c in source.search.await_args_list] == [
        (None, 1),
        ("Python", 1),
        ("Python", 1),
        (None, 1),
    ]


def test_basic_search_retains_nonremote_records_and_has_own_cache(
    tmp_path: Path, djinni_html: str
) -> None:
    from dataclasses import replace

    vacancy = replace(parse_search_page(djinni_html).vacancies[0], remote=None)
    source = MagicMock()
    source.search = AsyncMock(return_value=VacancyPage((vacancy,), 2))
    service = JobSearchService(source, VacancyStorage(tmp_path / "basic.sqlite3"))

    async def scenario() -> None:
        basic = await service.search()
        assert len(basic.vacancies) == 1
        assert basic.next_page == 2
        assert await service.search() == basic
        remote = await service.search("Python")
        assert remote.vacancies == ()
        await service.search(page=2)
        assert source.search.await_count == 3

    asyncio.run(scenario())
