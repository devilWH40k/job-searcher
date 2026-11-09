# Offline source fixtures

`djinni_remote_frontend.html` contains public listing markup fetched anonymously
on 2026-11-09 from:

https://djinni.co/jobs/?all_keywords=frontend&employment=remote

Expanded descriptions, scripts, forms, input fields, and tracking/event
attributes were removed. No candidate profiles or private/account data were
collected. Company names, public job titles, geography, relative salary bands,
and original vacancy links are retained for parser tests.

`djinni_empty.html` is the public results container from an actual no-match
search using the same `all_keywords` and `employment` fields.
`djinni_robots.txt` records the public rules observed on that date. Runtime code
checks the live policy instead of relying on this fixture.

`work_ua_remote_front_end.html` contains sanitized public excerpts from HTML
supplied by the user on 2026-11-09. It remains for offline regression tests;
Work.ua is not the Telegram bot's active source.

Fixtures are only test inputs, never a runtime fallback.
