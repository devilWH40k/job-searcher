# job-searcher

A Python Telegram bot project for searching job vacancies, starting with Work.ua.

The bot runs with Telegram long polling and responds to `/start` and `/help`.
Unsupported commands receive a help prompt. `/search`, Work.ua fetching and
parsing, and SQLite persistence are not implemented yet.

## Setup

Use Python **3.14.2** and [uv](https://docs.astral.sh/uv/). The Python pin is in
`.python-version`; the supported range is Python 3.14.2 through 3.14.x.

If uv is not installed:

```powershell
python -m pip install --user uv
```

Install the project and all runtime and development dependencies:

```powershell
uv sync --locked
```

If `uv` is not on your PATH, use `python -m uv` in place of `uv` in these commands.
uv creates `.venv`; activating it is optional when using `uv run`.
Commit `uv.lock` with dependency changes so installations remain reproducible.

If `python -m uv` reports `No module named uv` while `.venv` is activated,
run `deactivate` first, then retry the command. The user-installed uv belongs to
the base Python installation and is not available as a module inside `.venv`.
Run uv from outside the virtual environment; it still runs project commands
inside `.venv` automatically.

To run the already-installed bot directly, regardless of which environment
is activated:

```powershell
.\.venv\Scripts\python.exe -m job_bot
```

Runtime packages: `httpx`, `beautifulsoup4`, `python-telegram-bot`, and
`python-dotenv`. Development packages: `ruff` and `pytest`.
SQLite is provided by Python's built-in `sqlite3` module.

Create `.env` if it does not already exist:

```powershell
Copy-Item .env.example .env
```

Replace the placeholder with the token from BotFather:

```dotenv
TELEGRAM_BOT_TOKEN=your_actual_botfather_token
```

The bot reads `.env` from the working directory. An existing
`TELEGRAM_BOT_TOKEN` environment variable takes precedence over `.env`.
`.env`, database files, environments, caches, and logs are ignored by Git.
Never commit or share a real bot token.

## Commands

```powershell
uv run job-bot
uv run job-bot --help
uv run python -m job_bot --version
```

Run the first command from the project directory, keep the terminal open, then
send `/start` or `/help` in your bot's Telegram chat. Stop the bot with **Ctrl+C**.
Help and version commands work without a token or network access.

If uv is unavailable in your terminal, run directly with the installed environment:

```powershell
.\.venv\Scripts\python.exe -m job_bot
```

Long polling needs an internet connection and no public server or webhook URL.
Only one polling process should use a bot token at a time. Starting polling
removes any existing webhook for that bot and preserves pending updates.
The application uses explicit HTTP timeouts, retries startup failures up to three
times, and retries polling failures with the Telegram library's backoff and
`RetryAfter` handling. Command replies wait on rate limits and retry once.
Shutdown closes the Telegram HTTP clients and event loop.

Missing or malformed configuration stops startup with a helpful message. If
Telegram rejects the token, check `.env` and whether an environment variable is
overriding it. For a polling conflict, stop other copies of the bot before
restarting. Application logs omit tokens, exception details, and private messages;
third-party logs are suppressed because they can contain credential-bearing URLs.

## Development

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

The default tests run offline without a real Telegram token or Work.ua requests.
They cover configuration, command replies, rate limits, safe error reporting,
and the polling lifecycle using mocked Telegram HTTP responses, including a
connection failure followed by recovery and clean shutdown.

## Structure

```text
src/job_bot/
    __init__.py
    __main__.py       # CLI and safe startup diagnostics
    config.py         # Environment and .env configuration
    telegram/
        __init__.py
        application.py # Polling lifecycle and handler registration
        handlers.py    # Commands and error reporting
tests/
    test_cli.py
    test_config.py
    test_handlers.py
    test_polling.py
    fixtures/         # Future saved HTML fixtures
```
