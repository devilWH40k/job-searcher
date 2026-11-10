# job-searcher

A Python Telegram bot for learning how to search public Djinni job listings.

The bot runs with Telegram long polling. Send `/start`, select **Djinni**, then
enter a keyword or tap **Skip**, and choose whether to add categories.
It returns up to **six matches** as separate cards with original links.
The last card has **Load 6 more** when additional results are available.
Djinni's `$`–`$$$$` indicators are relative salary bands, not salary amounts.
`/help` describes the flow. Djinni is currently the only available source;
keyword/category searches remain remote-only. Skip + No searches all public jobs.
A `/search` command and other filters are
not implemented.

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

In Telegram:

1. Send `/start` and tap **Djinni**.
2. Send a position or keyword using 1-100 characters, or tap **Skip**.
   Skip stores an empty keyword.
3. Answer **Would you like to add categories?**:
   - **No** starts the search immediately using the keyword, if provided.
   - **Yes** opens the grouped category picker. Select multiple categories and
     tap **Search**. Previous/Next browse longer groups; Clear resets selections.
4. Read the first six cards and tap **Load 6 more** to continue.
5. Tap **Finish**, below Load 6 more, to end the search and see available commands.
   Finish is also available on the final batch, empty results, and errors.
   Send `/start` to begin another search.

Skipping the keyword and choosing No requests Djinni's basic `/jobs/` listing
without keyword, category, or remote filters. Searches with a keyword or categories
retain the existing remote-only behavior. Source and keyword entry make no vacancy
requests until No or Search is pressed. If Yes is selected, choose at least one
category before pressing Search. Failed searches offer Try again.

A persistent reply keyboard provides **Find a job**, **Help**, and
**Finish search** as large buttons in Telegram's keyboard area. Send `/start`
to display it. If hidden, use the keyboard toggle beside the message input to
reopen it. Buttons work during setup and results; they are handled as commands,
not search keywords. Source selection and search filters remain inline buttons.

Telegram's command menu beside the message input is also configured at startup with
`/start` (🔍 Find a job), `/help` (💡 Help & commands), and `/finish`
(✅ Finish search). `/finish` also ends a search during setup. Menu
visibility can vary by Telegram client; typing `/` also shows registered commands.
Restart the bot after updating to register the new commands. If registration fails,
a warning is logged and the commands still work when entered manually.

The picker includes all 157 categories in 11 groups from the supplied Djinni tree.
It supports up to 50 selected items, matching the inspected site's limit. Broad
parent categories and specific subcategories use their original Djinni keys.
Searches use the verified `all_keywords`, `employment=remote`, `primary_keyword`,
and `page` fields. Multiple categories are sent as repeated `primary_keyword`
parameters, preserving them when requesting later pages.
Results retain Djinni's order. Entries not explicitly marked `Тільки віддалено`
are excluded. Duplicate vacancy IDs are skipped across batches. The final batch
may contain fewer than six cards, and no further button is shown once results end.
Cards are paced to reduce Telegram rate limits.

Successful source pages, including empty results, are cached in memory for five
minutes by normalized keyword, category combination, and page, with at most 128
cached pages. Equivalent case/spacing and category-order variants reuse the cache;
different keywords, category combinations, and pages stay separate. Basic, category-only,
keyword-only, and combined queries have separate cache entries.
The cache is shared across chats. Load-more uses buffered results before fetching
another source page. At most three source pages are scanned per interaction;
if more scanning is needed, a continuation button is offered.

Finish discards the current cursor and invalidates its buttons without deleting
saved vacancies or shared cached pages. Search cursors and buttons are isolated per Telegram user and chat. Old buttons
are rejected after a new search, a completed batch, a restart, or 30 minutes of
inactivity. Failed next-page fetches leave the current button retryable.
Live listings can change between page requests; duplicate IDs are suppressed.

Each successful fetch also upserts vacancies into
`data/vacancies.sqlite3`, uniquely by source and vacancy ID, preserving when each
vacancy was first seen. SQLite runs in a worker thread and stores no Telegram
user data, search keywords, or selected filters. Restarting the bot clears the in-memory cache and
search sessions, while saved vacancies remain available in SQLite.
Existing Work.ua records remain in the same database. Djinni records use a
different source key, so matching numeric IDs do not overwrite Work.ua data.

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

## Djinni access and parsing

Source diagnostics appear in the terminal automatically: request attempt,
URL path (without query strings or credentials), response status, elapsed milliseconds,
body size, and a small
allowlist of headers (content type, recognized server, Cloudflare request ID and
challenge flag, and parsed retry delay). Fixed body hints such as `access_denied`,
`cloudflare`, or `browser_check` help identify error pages. Raw HTML, arbitrary
body snippets, cookies, authorization headers, and redirect URLs are not logged.
Parsed vacancy counts and cache hits are also logged. Cached searches make no
new HTTP request, so they do not produce a new response log.

The adapter uses ordinary async HTTP with a reusable client, explicit timeouts,
a minimum two-second interval between requests, and at most three attempts per
fetch. It respects numeric and HTTP-date `Retry-After` values. Long cooldowns fail
the current search instead of retrying early. HTTP 401/403 and redirects are not
retried or bypassed. Failed requests and unexpected HTML are reported as errors,
never as empty search results. The client also honors robots `Crawl-delay` and
uses a conservative single-request interval for `Request-rate`, if present.

Before fetching jobs, the adapter retrieves and checks Djinni's robots.txt with
Python's robots parser. A verified permission decision is cached for one hour.
If robots.txt cannot be verified or disallows the search URL, the search stops.
The five-minute result cache avoids additional collection between repeated commands.
The bot reads only robots.txt and public search-results pages requested by the
optional keyword/category and load-more flow. Cached robots rules are applied to every new URL,
including subsequent pages. It does
not fetch candidate profiles, contacts, full job descriptions, or private pages,
and does not log in or send applications. No proxy rotation, copied browser
cookies, CAPTCHA bypass, or browser impersonation is used.

On 2026-11-09, [Djinni's robots.txt](https://djinni.co/robots.txt) did not disallow
`/jobs/`; it disallowed `/jobs2`, `/q`, `/developers`, `/free-jobs`, and `/set_lang`.
The [terms reviewed](https://djinni.co/pricing) explicitly list obtaining candidates'
contacts and personal data through parsing as grounds for account blocking.
The demo excludes that information. An official public vacancy-search API was
not verified. Robots rules and public accessibility do not establish a
content-reuse license or guarantee legal compliance: this demo is scoped to
personal learning, brief public facts, and original links. Before wider
redistribution, confirm permission with Djinni and review its current terms.

Actual anonymous HTML was inspected before selectors were chosen:
`main#jobs_main`, `ul.list-jobs`, `.job-item[id]`, `.job_item__header-link`,
and `h2.job-item__position`. The genuine empty-results message was also saved.
Numbered pagination links and their active-page markers were inspected on
2026-11-10 before source pagination was added. Link targets are validated, and
requests are rebuilt from the selected keyword and verified page number.
Original Ukrainian text and relative salary indicators are preserved. Source
publication timestamps are left unknown because the observed dates indicate
updates without timezone information; application timestamps are stored in UTC.

Djinni returned HTTP 200 during inspection. Access can change: a future denial
or changed markup produces an understandable error rather than a bypass attempt
or a silent fallback. Work.ua's adapter and offline regression tests remain in
the repository, but the Telegram demo makes no Work.ua requests.

## Inspecting SQLite

After a search completes successfully, the database is at
`data/vacancies.sqlite3`. From the project directory, inspect counts with
Python's built-in SQLite CLI (no extra package is required):

```powershell
.\.venv\Scripts\python.exe -X utf8 -m sqlite3 data/vacancies.sqlite3 "SELECT source, COUNT(*) FROM vacancies GROUP BY source;"
```

View the latest saved vacancies:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m sqlite3 data/vacancies.sqlite3 "SELECT title, company, salary_text, url FROM vacancies WHERE source='djinni' ORDER BY first_seen_at DESC LIMIT 10;"
```

These are read-only SQL queries. The CLI creates an empty database if the path
does not exist, so complete a successful bot search first. The database contains
vacancy records; the five-minute query cache and per-user pagination state live
only in memory. A `salary_text` value such as `$$` remains a relative band.

## Development

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

The default tests run offline without a real Telegram token or live source requests.
They cover saved-HTML parsing, missing fields, duplicates, explicit empty results,
changed markup, safe Telegram formatting, SQLite persistence, cache behavior,
HTTP timeouts/retries/access denials, and the full mocked polling-to-six-cards
flow. Telegram connection failures and shutdown are also tested.
Djinni tests additionally cover robots restrictions, unavailable policies,
policy rechecks, and crawl-delay/request-rate handling.
Workflow tests cover the source picker, keyword validation, callbacks, subsequent
source pages, user/chat isolation, stale buttons, and retryable page failures.
Category tests cover group/page navigation, multiple selections, clear/toggle-off,
official key encoding, category-aware caching, stale pickers, and category retention
when loading more results. The category catalog is a dated snapshot; it is not
downloaded dynamically or inferred from display names.

## Structure

```text
src/job_bot/
    __init__.py
    __main__.py       # CLI and safe startup diagnostics
    config.py         # Environment and .env configuration
    models.py         # Normalized vacancy dataclass
    storage.py        # SQLite upserts in worker threads
    sources/
        djinni.py     # Active source: public listings and robots policy
        djinni_categories.py # Official category keys and hierarchy snapshot
        http_client.py # Shared conservative requests and safe diagnostics
        work_ua.py    # Inactive adapter and retained parser
    services/
        job_search.py # Search coordination and cache
    telegram/
        __init__.py
        application.py # Polling lifecycle and handler registration
        handlers.py    # Commands and error reporting
        formatting.py  # Escaped vacancy card text
        search_state.py # Ephemeral per-user/chat paging state
        categories.py # Grouped category multi-select keyboards
tests/
    test_cli.py
    test_config.py
    test_handlers.py
    test_polling.py
    test_work_ua.py
    test_djinni.py
    test_storage.py
    test_job_search.py
    test_formatting.py
    fixtures/         # Sanitized source HTML and Djinni robots.txt
```
