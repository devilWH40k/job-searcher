"""Offline smoke tests for the installed package entry point."""

import subprocess
import sys
from importlib.metadata import version

import pytest


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ([], "usage: job-bot"),
        (["--help"], "usage: job-bot"),
        (["--version"], f"job-bot {version('job-searcher')}"),
    ],
)
def test_module_entry_point(arguments: list[str], expected: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "job_bot", *arguments],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )

    assert expected in result.stdout
    assert result.stderr == ""
