"""Load and validate local application configuration."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values


class ConfigurationError(ValueError):
    """Required application configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Config:
    """Application settings with secrets excluded from representations."""

    telegram_bot_token: str = field(repr=False)
    database_path: Path = Path("data/vacancies.sqlite3")


def load_config(env_file: Path = Path(".env")) -> Config:
    """Read a token from the environment, falling back to a local UTF-8 file."""
    try:
        local_values = dotenv_values(env_file, encoding="utf-8", interpolate=False)
    except (OSError, UnicodeError) as exc:
        raise ConfigurationError(
            "Could not read .env. Check its encoding and access."
        ) from exc

    token = os.environ.get("TELEGRAM_BOT_TOKEN", local_values.get("TELEGRAM_BOT_TOKEN"))
    token = token.strip() if token else ""
    if not token:
        raise ConfigurationError(
            "Set TELEGRAM_BOT_TOKEN in your environment or project .env file."
        )
    if not re.fullmatch(r"[0-9]{3,}:[A-Za-z0-9_-]+", token):
        raise ConfigurationError(
            "TELEGRAM_BOT_TOKEN must be the token supplied by BotFather. "
            "Replace the placeholder in .env."
        )
    return Config(telegram_bot_token=token)
