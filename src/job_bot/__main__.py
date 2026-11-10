"""Command-line entry point for the Telegram bot."""

import logging
from argparse import ArgumentParser
from importlib.metadata import version

from telegram.error import Conflict, InvalidToken, NetworkError, TelegramError

from job_bot.config import ConfigurationError, load_config
from job_bot.telegram.application import run_bot


def configure_logging() -> None:
    """Emit only application diagnostics; library logs can contain private data."""
    handler = logging.StreamHandler()
    handler.addFilter(logging.Filter("job_bot"))
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def main() -> int:
    """Validate configuration and start polling, or show help/version offline."""
    parser = ArgumentParser(
        prog="job-bot",
        description="Run the Telegram job bot using long polling. Stop with Ctrl+C.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('job-searcher')}"
    )
    parser.parse_args()
    configure_logging()
    logger = logging.getLogger("job_bot")
    try:
        config = load_config()
        run_bot(config)
    except ConfigurationError as exc:
        logger.error("%s", exc)
        return 1
    except InvalidToken:
        logger.error("Telegram rejected the token. Check TELEGRAM_BOT_TOKEN in .env.")
        return 1
    except Conflict:
        logger.error("Telegram polling conflict. Stop other instances of this bot.")
        return 1
    except NetworkError:
        logger.error(
            "Could not connect to Telegram. Check your internet and try again."
        )
        return 1
    except TelegramError:
        logger.error(
            "Telegram could not start the bot. Check its configuration and retry."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
