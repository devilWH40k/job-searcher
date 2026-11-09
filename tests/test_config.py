"""Configuration tests using temporary files and synthetic tokens only."""

from pathlib import Path

import pytest

from job_bot.config import ConfigurationError, load_config


def test_dotenv_token_and_secret_repr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# Локальна конфігурація\nTELEGRAM_BOT_TOKEN=" 123456:local-token "\n',
        encoding="utf-8",
    )

    config = load_config(env_file)

    assert config.telegram_bot_token == "123456:local-token"
    assert "local-token" not in repr(config)


def test_environment_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=123456:file-token\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:environment-token")

    assert load_config(env_file).telegram_bot_token == "123456:environment-token"


@pytest.mark.parametrize(
    "token", [None, "", " ", "your-telegram-bot-token", "invalid:secret"]
)
def test_invalid_or_missing_token_is_not_exposed(
    token: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    if token is not None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)

    with pytest.raises(ConfigurationError, match="TELEGRAM_BOT_TOKEN") as error:
        load_config(tmp_path / ".env")

    assert "invalid:secret" not in str(error.value)


def test_dotenv_values_are_not_interpolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("OTHER_SECRET", "123456:unrelated-secret")
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=${OTHER_SECRET}\n", encoding="utf-8")

    with pytest.raises(ConfigurationError):
        load_config(env_file)
