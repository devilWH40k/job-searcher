"""Offline smoke tests for the installed package entry point."""

import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from unittest.mock import Mock

import pytest
from telegram.error import InvalidToken, NetworkError

from job_bot import __main__ as cli
from job_bot.config import Config


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["--help"], "usage: job-bot"),
        (["--version"], f"job-bot {version('job-searcher')}"),
    ],
)
def test_module_entry_point(
    arguments: list[str], expected: str, tmp_path: Path
) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "job_bot", *arguments],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
        cwd=tmp_path,
    )

    assert expected in result.stdout
    assert result.stderr == ""


def test_missing_token_fails_without_network(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.pop("TELEGRAM_BOT_TOKEN", None)
    result = subprocess.run(
        [sys.executable, "-m", "job_bot"],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=tmp_path,
        env=environment,
    )

    assert result.returncode == 1
    assert "Set TELEGRAM_BOT_TOKEN" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("error", [InvalidToken("secret"), NetworkError("secret")])
def test_startup_failure_is_safe(
    error: Exception, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(sys, "argv", ["job-bot"])
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "load_config", lambda: Config("123456:secret"))
    monkeypatch.setattr(cli, "run_bot", Mock(side_effect=error))

    assert cli.main() == 1
    assert "secret" not in caplog.text
    assert "Traceback" not in caplog.text


def test_library_logs_are_suppressed(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import logging; from job_bot.__main__ import configure_logging; "
            "configure_logging(); "
            "logging.getLogger('httpx').info('token-secret'); "
            "logging.getLogger('telegram.ext').error('private-message'); "
            "logging.getLogger('job_bot').info('Safe diagnostic')",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=tmp_path,
        check=True,
    )

    assert "Safe diagnostic" in result.stderr
    assert "token-secret" not in result.stderr
    assert "private-message" not in result.stderr
