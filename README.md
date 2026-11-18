# job-searcher

A Python Telegram bot for learning how to search public Djinni job listings.

The bot runs with Telegram long polling. Send `/start`, select **Djinni**, then
enter a keyword or tap **Skip**, and choose whether to add categories.
It returns up to **six matches** as separate cards with original links.
The last card has **Load 6 more** when additional results are available.
Djinni's `$`–`$$$$` indicators are relative salary bands, not salary amounts.
`/help` describes the flow. Djinni is currently the only available source;
keyword/category searches remain remote-only. Skip + No searches all public jobs.
`/search` opens the same wizard; `/search Python Developer` immediately searches
Djinni for that keyword with the existing remote-only behavior.
`/recent` shows up to six vacancies most recently discovered for you through manual
searches or tracking, without making a new source request.

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

A persistent reply keyboard provides **Find a job**, **Create search**,
**Saved searches**, **Help**, **Track**, and **Finish search** as large buttons in Telegram's
keyboard area. **Track** opens the same saved-search / create-and-track menu as
`/track`. Send `/start` to display it. If hidden, use the keyboard toggle beside the message input to
reopen it. Buttons work during setup and results; they are handled as commands,
not search keywords. Source selection and search filters remain inline buttons.

Telegram's command menu beside the message input is also configured at startup with
`/start` (🔍 Find a job), `/search`, `/recent`,
`/createsearch` (💾 Save search filters),
`/list` (📋 Your saved searches), `/track`, `/untrack`,
`/help` (💡 Help & commands), and `/finish`
(✅ Finish search). `/finish` also ends a search during setup. Menu
visibility can vary by Telegram client; typing `/` also shows registered commands.
Restart the bot after updating to register the new commands. If registration fails,
a warning is logged and the commands still work when entered manually.

Saved searches are available in a **private chat** with the bot:

1. Send `/createsearch` (or tap **Create search**).
2. Choose Djinni, enter a keyword or Skip, and choose Yes/No for categories.
3. With categories, tap **Save search** after selecting them. With No, the
   filters are saved immediately. Creation makes no requests to Djinni.
4. Send `/list` (or tap **Saved searches**) to see cards with source, keyword,
   categories, scope, and creation time in UTC. An empty list points to
   `/createsearch`. Lists show six cards at a time, with **More saved searches**
   when needed.
5. Tap **Run search** on a card to fetch results using the saved filters. The
   existing six-vacancy batches, cache, and Finish controls then apply.
6. Tap **Delete** on a saved-search card to remove it immediately. The card shows
   a deletion confirmation with **Refresh saved searches**, which reloads the list
   from the beginning. Older copies of deleted cards can no longer run the search.

Saved filters persist in the same SQLite database across restarts. Ownership uses
Telegram's stable numeric user ID, so changing a username does not affect access.
Every lookup checks the requesting user's ID. Identical normalized filters reuse
an existing saved search rather than creating duplicates. No username, phone
number, or email is stored. `/finish` or `/start` cancels unfinished creation
without deleting saved searches. Saving failures keep filters available for retry.
`/list` does not interrupt an unfinished wizard; running a card starts a new search.
Deletion checks the owner's Telegram ID in the database. Existing vacancy
records, cached results, and a search already
running are preserved. Deleting a saved search also stops its tracking and removes
its queued alerts. Editing saved filters is not implemented.

### Recent vacancies

Send `/recent` in a **private chat** to see up to six distinct vacancies discovered
for you through the manual search wizard, `/search <keywords>`, running saved
searches, or `/track` checks. Cards include the usual details and original links.
Newer discovery batches appear first, with source order preserved within a batch.
Finding the same vacancy again updates its snapshot without promoting it ahead of
new discoveries. Identity uses both source and vacancy ID.

History includes all matches on successfully fetched result pages, including
buffered results and tracking's initial baseline. Cached results are attributed
separately to each user who searches for them. `/recent` does not fetch live pages,
change tracking, or interrupt a wizard or active pagination cursor. Fewer than six
discoveries produce fewer cards; an empty history explains how to start searching.

History persists across restarts and remains after `/finish`, `/untrack`, or
deleting saved filters. Collection begins with this version; older global vacancy
records have no reliable user attribution and are not retroactively added. Manual
searches in group chats do not populate private history. The `recent_vacancies`
table stores the numeric owner ID, source identity, UTC discovery time, and card
snapshot; existing data is preserved without a database reset.

### Tracking vacancies

Tracking is available in private chats and uses the current Djinni source:

1. Send `/track` and choose **Saved searches**, then tap **Track every 30 min**
   on a card. You can also send `/track <saved search ID>` directly.
2. To start from new filters, choose **Create & track** or send `/track new`.
   The existing source/keyword/category wizard saves the search first, then
   enables tracking. With categories, finish with **Save & track**.
3. The first successful complete scan establishes a baseline without sending old
   vacancies. Later scans send each newly observed vacancy once per tracked search,
   with its original link. A vacancy already found by a manual search can still be
   new to a subscription. Repeated tracking commands keep the existing baseline.
4. Checks run automatically every **30 minutes**, with no interval configuration.
   The bot must remain running. `/list` shows tracking status and **Stop tracking**;
   `/untrack <saved search ID>` stops alerts and keeps the saved filters. `/untrack`
   opens a shortcut to these controls. `/finish` ends only the interactive wizard
   or results; it does not stop subscriptions.

Subscriptions, scanned vacancy IDs, pagination cursors, due times, and unsent alerts
persist in SQLite across restarts. Overdue work resumes at startup, without
replaying each interval missed while offline. Turning tracking off removes its
baseline and pending alerts; tracking it again establishes a fresh baseline.
Blocking the bot disables that subscription on the next attempted delivery.

One background worker shares the existing five-minute result cache and conservative
source request limits with interactive searches. It wakes every ten seconds to
process due work and scans at most three pages per search per turn, resuming the
remaining pages on subsequent turns. The next 30-minute interval starts when a
complete scan finishes. Large searches, Telegram rate limits, and source failures
can delay completion. Changed markup and source/network errors retain progress
and retry after 30 minutes; they never establish a false empty baseline. Initial
baseline vacancies appearing while a long scan is in progress may be included in
that baseline. Changes to an already observed vacancy do not trigger another alert.

Alerts are paced and queued until Telegram accepts them. A network failure with an
uncertain delivery outcome, or a process interruption between sending and recording
success, can produce a duplicate on retry. A message already being sent when
tracking stops may still arrive. No extra scheduler package or environment setting
is required, and shutdown cancels the worker before closing its HTTP clients.

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
Djinni cards also show available view and application counts and an English
relative update label, for example **63 views · 9 applications · Updated 2 hours
ago**. Application reporting windows such as "in the last 30 days" are preserved.
Missing counters are omitted; zero is displayed when the source explicitly reports
it. Relative times describe the fetched snapshot and are not inferred publication
timestamps. The original update label and counters are saved in SQLite; new columns
are added automatically while preserving existing records.

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
vacancy was first seen. SQLite operations run in a worker thread. The separate
`saved_searches` table stores the numeric Telegram owner ID, source, keyword,
categories, scope, and UTC creation time when `/createsearch` or the new-filter
tracking wizard is completed.
Ordinary search criteria remain in memory. Restarting clears the result cache and
active wizard/cursor state; saved filters, tracking, recent history, and vacancies
remain in SQLite.
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
optional keyword/category and load-more flow or explicitly tracked saved searches.
Cached robots rules are applied to every new URL,
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
vacancy records and explicitly saved filters; the five-minute result cache and
per-user pagination state live only in memory. A `salary_text` value such as `$$` remains a relative band.

Inspect the saved-search table locally (these filters are private user data):

```powershell
.\.venv\Scripts\python.exe -X utf8 -m sqlite3 data/vacancies.sqlite3 "SELECT id, source, keyword, categories, remote_only, created_at FROM saved_searches ORDER BY id DESC LIMIT 10;"
```

The `saved_searches` table is created lazily on first use of saving or listing.
Existing vacancy data is preserved; no database reset or manual migration is needed.
The `tracked_searches` and `tracked_matches` tables are initialized alongside saved
searches. They contain only subscriptions and delivery state tied to saved filters;
alerts use the existing numeric owner ID as the private-chat destination.

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

## GitHub Actions and Lightsail deployment

The **Checks** workflow runs formatting, linting and offline tests on every push
and pull request, using Python 3.14.2 and `uv.lock`. Set its **Python checks** job
as a required branch protection check for `main` if desired.

The **Deploy to Lightsail** workflow is manually started from GitHub's Actions
tab, with `main` selected. It reruns the checks and deploys that exact commit;
merging code alone does not restart production. Deployments run one at a time.

One-time setup:

1. In repository **Settings → Environments**, create `production` and restrict
   deployment branches to `main`.
2. Add these environment secrets:

   | Secret | Value |
   | --- | --- |
   | `LIGHTSAIL_HOST` | Instance public IPv4 address or hostname (prefer a static IP) |
   | `LIGHTSAIL_SSH_KEY` | Private SSH key for the `ubuntu` account, without a passphrase |
   | `LIGHTSAIL_KNOWN_HOSTS` | Verified OpenSSH known_hosts entry for that host |

   Prefer a dedicated deployment key: put its public key in the server's
   `/home/ubuntu/.ssh/authorized_keys` and keep the private key only in GitHub's
   environment secret. This key grants access to the server; restrict who can
   edit workflows or deploy. Never put it in the repository.

3. Obtain the host key through your trusted Lightsail browser SSH session:

   ```bash
   cat /etc/ssh/ssh_host_ed25519_key.pub
   ```

   Build the secret as `YOUR_HOST ssh-ed25519 AAAA...`, using the key type and
   base64 key from that command and exactly the host in `LIGHTSAIL_HOST`.
   The workflow requires host verification and will fail if it does not match.

4. Ensure the Lightsail firewall permits SSH from the runner's network.
   Standard GitHub-hosted runners use changing public IPs; a rule allowing only
   your laptop will block deployment. Use controlled runner/network access if
   you need a fixed allowlisted source. Do not disable host verification to fix
   connectivity. CI works independently of this SSH setup.
5. Confirm the existing server setup matches the deployment script:
   `/home/ubuntu/job-searcher` is a clean Git checkout with the public GitHub
   repository as `origin`; uv is `/home/ubuntu/.local/bin/uv`; the `ubuntu` user
   can run `sudo -n systemctl start/stop/is-active job-searcher` and write
   `/var/lib/job-searcher/backups`.

The existing systemd service must run
`/home/ubuntu/job-searcher/.venv/bin/python -m job_bot` with
`WorkingDirectory=/var/lib/job-searcher` and its production token loaded from
`/etc/job-searcher/bot.env`. The workflow does not copy your local `.env`, token,
or database. Adapt `scripts/deploy-lightsail.sh` before use if your paths differ.

Development flow: make a feature locally with the test bot, push a branch, open
a pull request, wait for checks, merge into `main`, then choose **Actions → Deploy
to Lightsail → Run workflow → main**. No AWS API credentials are needed.

Deployment stops the bot briefly, backs up SQLite, checks out the tested commit,
installs locked production dependencies and starts the service. A ten-second
systemd check confirms it stayed active; this is not an end-to-end Telegram test.
The server checkout becomes detached at the deployed commit; later deployments
fetch `main` explicitly. SQLite backups stay on the instance and accumulate;
periodically copy needed backups elsewhere and remove old ones.

If deployment fails after stopping the bot, it leaves the service stopped.
Read the failed Actions step and recover via your trusted SSH session:

```bash
cd /home/ubuntu/job-searcher
# Use the previous commit printed in the deployment log.
git checkout --detach PREVIOUS_COMMIT_SHA
/home/ubuntu/.local/bin/uv sync --locked --no-dev --python 3.14.2
sudo systemctl start job-searcher
sudo systemctl status job-searcher --no-pager
```

Review schema compatibility before rolling back code. Database backups are under
`/var/lib/job-searcher/backups`; restoring one is a separate, deliberate operation
while the bot is stopped because it replaces data saved since that backup.

## Structure

```text
src/job_bot/
    __init__.py
    __main__.py       # CLI and safe startup diagnostics
    config.py         # Environment and .env configuration
    models.py         # Normalized vacancy dataclass
    storage.py        # Vacancies, saved filters, and tracking state in worker threads
    sources/
        djinni.py     # Active source: public listings and robots policy
        djinni_categories.py # Official category keys and hierarchy snapshot
        http_client.py # Shared conservative requests and safe diagnostics
        work_ua.py    # Inactive adapter and retained parser
    services/
        job_search.py # Search coordination and cache
        tracking.py   # Resumable subscription checks and deduplication
    telegram/
        __init__.py
        application.py # Polling lifecycle and handler registration
        handlers.py    # Commands and error reporting
        formatting.py  # Escaped vacancy card text
        search_state.py # Ephemeral per-user/chat paging state
        categories.py # Grouped category multi-select keyboards
        tracking.py   # Background worker and Telegram alerts
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
