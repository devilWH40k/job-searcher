# job-searcher

A Python Telegram bot project for searching job vacancies, starting with Work.ua.

The initial scaffold includes packaging, dependencies, development tools, and an
offline CLI smoke test. Telegram polling, `/search`, fetching, parsing, and SQLite
persistence are not implemented yet. No token or live service is needed to run
the scaffold or its tests.

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

Runtime packages: `httpx`, `beautifulsoup4`, `python-telegram-bot`, and
`python-dotenv`. Development packages: `ruff` and `pytest`.
SQLite is provided by Python's built-in `sqlite3` module.

For future Telegram configuration, copy the placeholder file locally and replace
the token in `.env` when Telegram support is implemented:

```powershell
Copy-Item .env.example .env
```

The scaffold does not load `.env` yet. `.env`, database files, environments,
caches, and logs are ignored by Git. Never commit a real bot token.

## Commands

```powershell
uv run job-bot --help
uv run python -m job_bot --version
```

The CLI currently displays help and version information only.

## Development

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

The default tests run offline without a real Telegram token or Work.ua requests.

## Structure

```text
src/job_bot/
    __init__.py
    __main__.py       # CLI scaffold
tests/
    test_cli.py       # Installed-package smoke tests
    fixtures/         # Future saved HTML fixtures
```
