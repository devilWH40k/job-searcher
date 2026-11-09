"""Exercise real polling and shutdown with Telegram HTTP fully mocked."""

import asyncio
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from job_bot.config import Config
from job_bot.telegram import application as telegram_app
from job_bot.telegram.handlers import HELP_TEXT, START_TEXT, UNKNOWN_COMMAND_TEXT


@pytest.mark.parametrize("fail_first_poll", [False, True])
def test_polling_dispatches_commands_and_closes_clients(
    fail_first_poll: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_client = httpx.AsyncClient
    original_create = telegram_app.create_application
    clients = []
    applications = []
    loops = []
    replies = []
    polls = []
    poll_count = 0
    delivered = False
    bot_user = {
        "id": 123456,
        "is_bot": True,
        "first_name": "Bot",
        "username": "test_bot",
    }
    chat = {"id": 42, "type": "private"}
    commands = ["/start", "/help@test_bot", "/unknown"]
    updates = [
        {
            "update_id": index,
            "message": {
                "message_id": index,
                "date": 0,
                "chat": chat,
                "from": {"id": 42, "is_bot": False, "first_name": "Private"},
                "text": command,
                "entities": [
                    {"type": "bot_command", "offset": 0, "length": len(command)}
                ],
            },
        }
        for index, command in enumerate(commands, start=1)
    ]

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal delivered, poll_count
        method = request.url.path.rsplit("/", 1)[-1]
        data = parse_qs(request.content.decode())
        if method == "getMe":
            result = bot_user
        elif method == "deleteWebhook":
            assert data.get("drop_pending_updates") == ["false"]
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
            result = {
                "message_id": len(replies),
                "date": 0,
                "chat": chat,
                "text": replies[-1],
            }
            if len(replies) == 3:
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

    telegram_app.run_bot(Config(telegram_bot_token="123456:offline-token"))

    assert replies == [START_TEXT, HELP_TEXT, UNKNOWN_COMMAND_TEXT]
    assert polls[0]["timeout"] == ["30"]
    assert polls[0]["allowed_updates"] == ['["message"]']
    assert polls[-1]["offset"] == ["4"]
    assert clients and all(client.is_closed for client in clients)
    assert all(loop.is_closed() for loop in loops)
    assert not applications[0].running
