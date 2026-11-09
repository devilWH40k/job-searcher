"""Public, sanitized HTML fixtures shared by offline source tests."""

from pathlib import Path

import pytest


@pytest.fixture
def work_ua_html() -> str:
    return (Path(__file__).parent / "fixtures/work_ua_remote_front_end.html").read_text(
        encoding="utf-8"
    )


@pytest.fixture
def djinni_html() -> str:
    return (Path(__file__).parent / "fixtures/djinni_remote_frontend.html").read_text(
        encoding="utf-8"
    )


@pytest.fixture
def djinni_empty_html() -> str:
    return (Path(__file__).parent / "fixtures/djinni_empty.html").read_text(
        encoding="utf-8"
    )
