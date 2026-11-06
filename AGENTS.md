## Project goal

Build a Python Telegram bot that searches job vacancies.
The first source is Work.ua.

Initial workflow:
1. The user sends `/search <keywords>`.
2. The application fetches a Work.ua search results page.
3. It parses and stores vacancy records.
4. The bot returns up to five results with original links.

City and remote filters, subscriptions, scheduled alerts, and additional
sources are future features unless explicitly requested.

## Runtime and dependencies

- Target Python 3.14.2.
- Use uv for environment and dependency management.
- Declare dependencies in pyproject.toml and commit uv.lock.
- Verify dependency compatibility with Python 3.14 before adding packages.
- Do not change the Python version without explaining why.

Preferred tools:
- httpx for HTTP requests.
- beautifulsoup4 for HTML parsing.
- python-telegram-bot for Telegram, using long polling initially.
- Python's built-in sqlite3 for storage.
- python-dotenv for loading local development configuration.
- Ruff for formatting and linting.
- pytest for tests.

Use Playwright only if inspecting the source shows that browser rendering
is necessary. Do not add frameworks or services without a concrete need.

## Project structure

Use the following layout as the application grows. Do not create empty
modules solely to match this tree.

src/job_bot/
    __init__.py
    __main__.py
    config.py
    models.py
    sources/
        __init__.py
        work_ua.py
    storage.py
    services/
        __init__.py
        job_search.py
    telegram/
        __init__.py
        handlers.py
        formatting.py
tests/
    fixtures/

- Source adapters fetch and parse vacancies.
- Models describe normalized application data.
- Storage owns SQL and database connections.
- Services coordinate searches, caching, and persistence.
- Telegram handlers handle commands and presentation.
- Keep Telegram-specific objects out of source adapters and storage.

## Vacancy data

Represent vacancies with a typed dataclass or an equally simple model:

- source
- source_id
- url
- title
- company
- location
- salary_text
- remote
- published_at
- first_seen_at

Allow missing source fields rather than inventing values.
Use remote = None when remote status is unknown.
Preserve the original salary text.
Use timezone-aware timestamps; store application timestamps in UTC.
Enforce uniqueness on (source, source_id).

## Work.ua integration

- Check current terms, robots.txt, and official access options before
  implementing live collection.
- Inspect actual HTML before choosing selectors or URL parameters.
- Do not invent selectors or assume the page structure is stable.
- Separate fetching from parsing so parsing can be tested offline.
- Use explicit timeouts, bounded retries, and conservative request rates.
- Honor Retry-After when provided.
- Cache repeated searches to reduce requests.
- Do not bypass authentication, CAPTCHAs, or access restrictions.
- Distinguish empty search results from a failed fetch or changed markup.
- Preserve original vacancy links and identify the source.

## Telegram behavior

- Validate search input and provide helpful usage messages.
- Return concise summaries: title, company, location, salary if present,
  and a link.
- Escape scraped text before using Telegram HTML or Markdown formatting.
- Respect Telegram message limits and rate limits.
- Show understandable errors without exposing internal exceptions.
- Do not block the async event loop with synchronous network or lengthy
  database operations.

## Storage and configuration

- Use SQLite initially; no database server is required.
- Use parameterized SQL and explicit transactions.
- Keep schema initialization repeatable.
- Preserve existing data when changing the schema.
- Keep secrets in environment variables.
- Load local secrets from .env and commit only .env.example placeholders.
- Ignore .env, database files, virtual environments, caches, and logs in Git.
- Never log bot tokens, credential-bearing URLs, or private user messages.
- Store only Telegram user data needed for implemented features.

## Development approach

- Implement small, working increments.
- Prefer readable functions, clear names, and type hints.
- Use async HTTP with a reusable httpx.AsyncClient.
- Close HTTP clients and database connections cleanly.
- Catch specific exceptions at appropriate boundaries.
- Use logging instead of print for application diagnostics.
- Avoid unrelated refactors and premature abstractions.
- Update README.md when setup, commands, or configuration changes.
- Do not add future features unless requested.

## Verification

After the relevant tools are configured, run:

    uv run ruff format --check .
    uv run ruff check .
    uv run pytest

Write meaningful tests for:
- Parsing representative saved HTML.
- Missing optional fields and empty results.
- Duplicate vacancy handling.
- Telegram formatting and escaping.
- Network failure handling, using mocks.

Keep automated tests offline. Never require a real Telegram token or
live Work.ua requests for the default test suite.

Do not claim checks passed unless they were run. Report any checks that
could not run and explain the reason.

## Completion criteria

For each change:
- Implement the requested behavior.
- Run checks appropriate to the change.
- Explain what changed and any remaining limitations.
- Never commit credentials or claim unfinished features are complete.

## Python 3.14.2 coding practices

### Types and data models
- Use modern annotations: list[str], dict[str, int], and str | None.
- Use the `type` statement for type aliases when useful.
- Annotate public functions, return values, and model fields.
- Prefer dataclasses for vacancy records; avoid passing unstructured
  dictionaries across application layers.
- Remember that annotations are lazily evaluated in Python 3.14.
  Use typing.get_type_hints() when runtime type resolution is needed.
- Do not add `from __future__ import annotations` automatically;
  use it only for a specific compatibility requirement.

### Functions and state
- Keep functions focused and make dependencies explicit.
- Never use mutable default arguments; use None or default_factory.
- Use pathlib.Path for filesystem paths.
- Use context managers for resources.
- Avoid mutable global state and work performed during imports.
- Use `if __name__ == "__main__":` for executable entry points.

### Async programming
- Use async/await for HTTP and Telegram operations.
- Reuse an httpx.AsyncClient with explicit timeouts.
- Limit concurrent requests; do not launch unbounded tasks.
- Prefer asyncio.TaskGroup for related concurrent operations.
- Never swallow asyncio.CancelledError; allow clean cancellation.
- Move blocking SQLite operations to asyncio.to_thread when needed,
  keeping each connection's creation and use in the same thread.
- Do not assume async code makes CPU-heavy work faster.

### Errors and logging
- Catch specific exceptions instead of broad Exception handlers,
  except at deliberate application boundaries.
- Preserve causes when translating errors: raise ... from exc.
- Avoid silently returning empty results after failures.
- Use parameterized logging, for example:
  logger.info("Parsed %d vacancies", len(vacancies))
- Redact secrets and avoid logging sensitive user data.

### Dates and text
- Use datetime.now(UTC), not datetime.utcnow().
- Use timezone-aware datetimes throughout the application.
- Specify encoding="utf-8" when reading or writing text files.
- Preserve Ukrainian text and original source values.
- Treat scraped content as untrusted input.

### Python 3.14 features and compatibility
- Prefer established features unless a newer feature clearly helps.
- Do not use experimental free-threaded execution or multiple
  interpreters without a demonstrated need and compatibility checks.
- Do not treat Python 3.14 template strings as automatic protection
  against SQL injection or Telegram formatting issues.
- Verify dependencies and checks under Python 3.14.2.

### Tooling
- Set Ruff's target-version to "py314".
- Keep the Python version requirement in pyproject.toml consistent
  with the project's supported versions.
- Use a static type checker such as ty or Pyright once configured.
- Resolve substantive type errors; avoid blanket suppression.