"""Exercise real polling and shutdown with Telegram HTTP fully mocked."""

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from job_bot.config import Config
from job_bot.sources import http_client
from job_bot.sources.djinni import ROBOTS_URL, build_search_url, parse_search_results
from job_bot.telegram import application as telegram_app
from job_bot.telegram import handlers, search_state
from job_bot.telegram.categories import category_picker
from job_bot.telegram.formatting import format_vacancy
from job_bot.telegram.handlers import (
    CATEGORY_CHOICE_TEXT,
    HELP_TEXT,
    KEYWORD_TEXT,
    START_TEXT,
    UNKNOWN_COMMAND_TEXT,
)


@pytest.mark.parametrize("fail_first_poll", [False, True])
@pytest.mark.parametrize("djinni_status", [200, 403])
def test_polling_dispatches_commands_and_closes_clients(
    fail_first_poll: bool,
    djinni_status: int,
    djinni_html: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_client = httpx.AsyncClient
    original_create = telegram_app.create_application
    clients = []
    applications = []
    loops = []
    replies = []
    buttons = []
    djinni_requests = []
    polls = []
    callback_answers = []
    category_edits = []
    poll_count = 0
    delivered = False
    bot_user = {
        "id": 123456,
        "is_bot": True,
        "first_name": "Bot",
        "username": "test_bot",
    }
    chat = {"id": 42, "type": "private"}

    def message_update(index: int, content: str, command: bool = False) -> dict:
        message = {
            "message_id": index,
            "date": 0,
            "chat": chat,
            "from": {"id": 42, "is_bot": False, "first_name": "Private"},
            "text": content,
        }
        if command:
            message["entities"] = [
                {"type": "bot_command", "offset": 0, "length": len(content)}
            ]
        return {"update_id": index, "message": message}

    def callback_update(index: int, query_id: str, data: str) -> dict:
        return {
            "update_id": index,
            "callback_query": {
                "id": query_id,
                "chat_instance": "test-chat",
                "from": {"id": 42, "is_bot": False, "first_name": "Private"},
                "data": data,
                "message": {
                    "message_id": index,
                    "date": 0,
                    "chat": chat,
                    "from": bot_user,
                    "text": "Previous bot message",
                },
            },
        }

    updates = [
        message_update(1, "/start", True),
        callback_update(2, "source-cb", "source:djinni"),
        message_update(3, "frontend"),
        callback_update(4, "yes-cb", "categories:aaaaaaaaaaaa:yes"),
        callback_update(5, "group-cb", "cat:aaaaaaaaaaaa:0:g:0"),
        callback_update(6, "toggle-cb", "cat:aaaaaaaaaaaa:1:t:0"),
        callback_update(7, "done-cb", "cat:aaaaaaaaaaaa:2:d:0"),
        callback_update(8, "more-cb", "more:aaaaaaaaaaaa:1"),
        callback_update(9, "duplicate-cb", "more:aaaaaaaaaaaa:1"),
        callback_update(10, "finish-cb", "finish:aaaaaaaaaaaa"),
        message_update(11, "/help@test_bot", True),
        message_update(12, "/unknown", True),
    ]
    commands = []
    menu_buttons = []

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal delivered, poll_count
        if str(request.url) == ROBOTS_URL:
            return httpx.Response(
                200,
                text="User-agent: *\nDisallow: /developers\n",
                headers={"Content-Type": "text/plain"},
            )
        if request.url.host == "djinni.co":
            assert str(request.url) == build_search_url(
                "frontend", categories=("JavaScript",)
            )
            djinni_requests.append(request)
            return httpx.Response(
                djinni_status, text=djinni_html, headers={"Content-Type": "text/html"}
            )
        method = request.url.path.rsplit("/", 1)[-1]
        data = parse_qs(request.content.decode())
        if method == "getMe":
            result = bot_user
        elif method == "setMyCommands":
            commands.extend(json.loads(data["commands"][0]))
            result = True
        elif method == "setChatMenuButton":
            menu_buttons.append(json.loads(data["menu_button"][0]))
            result = True
        elif method == "deleteWebhook":
            assert data.get("drop_pending_updates") == ["false"]
            result = True
        elif method == "answerCallbackQuery":
            callback_answers.append(data)
            result = True
        elif method == "editMessageText":
            category_edits.append(data)
            result = True
        elif method == "getUpdates":
            poll_count += 1
            polls.append(data)
            if fail_first_poll and poll_count == 1:
                raise httpx.ConnectError("synthetic offline failure", request=request)
            if not delivered:
                result = updates
                delivered = True
            else:
                await asyncio.sleep(0.01)
                result = []
        elif method == "sendMessage":
            replies.append(data["text"][0])
            if "reply_markup" in data:
                buttons.append(json.loads(data["reply_markup"][0]))
            result = {
                "message_id": len(replies),
                "date": 0,
                "chat": chat,
                "text": replies[-1],
            }
            if len(replies) == (16 if djinni_status == 200 else 8):
                applications[0].stop_running()
        else:
            raise AssertionError(f"Unexpected Telegram method: {method}")
        return httpx.Response(200, json={"ok": True, "result": result})

    def make_client(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(respond)
        client = original_client(**kwargs)
        clients.append(client)
        return client

    def capture_application(config: Config) -> Any:
        application = original_create(config)
        applications.append(application)
        loop = asyncio.get_event_loop()
        loops.append(loop)
        # Bound this test even if command dispatch fails to stop the application.
        loop.call_later(10, application.stop_running)
        return application

    monkeypatch.setattr(httpx, "AsyncClient", make_client)
    monkeypatch.setattr(telegram_app, "create_application", capture_application)
    monkeypatch.setattr(handlers, "CARD_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(http_client, "MIN_REQUEST_INTERVAL", 0)
    monkeypatch.setattr(search_state, "token_hex", lambda size: "a" * 12)

    telegram_app.run_bot(
        Config(
            telegram_bot_token="123456:offline-token",
            database_path=tmp_path / "jobs.sqlite3",
        )
    )

    if djinni_status == 200:
        matches = [v for v in parse_search_results(djinni_html) if v.remote is True]
        assert replies == [
            START_TEXT,
            KEYWORD_TEXT,
            CATEGORY_CHOICE_TEXT,
            category_picker(search_state.SearchSession())[0],
            *[format_vacancy(v) for v in matches],
            "Search finished.\n\n" + HELP_TEXT,
            HELP_TEXT,
            UNKNOWN_COMMAND_TEXT,
        ]
        assert [
            markup["inline_keyboard"][0][0]["url"]
            for markup in buttons
            if "url" in markup["inline_keyboard"][0][0]
        ] == [v.url for v in matches]
    else:
        assert "access is unavailable" in replies[4]
        assert replies[5:] == [
            "Search finished.\n\n" + HELP_TEXT,
            HELP_TEXT,
            UNKNOWN_COMMAND_TEXT,
        ]
        assert len(buttons) == 5  # Source and category pickers.
        assert not (tmp_path / "jobs.sqlite3").exists()
    assert len(djinni_requests) == 1
    assert polls[0]["timeout"] == ["30"]
    assert json.loads(polls[0]["allowed_updates"][0]) == ["message", "callback_query"]
    assert polls[-1]["offset"] == ["13"]
    assert len(callback_answers) == 8
    assert len(category_edits) == 3
    assert "no longer current" in callback_answers[-2]["text"][0]
    assert [c["command"] for c in commands] == ["start", "help", "finish"]
    assert menu_buttons == [{"type": "commands"}]
    assert clients and all(client.is_closed for client in clients)
    assert all(loop.is_closed() for loop in loops)
    assert not applications[0].running
