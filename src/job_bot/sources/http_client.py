"""Conservative public-page HTTP shared by the vacancy source adapters."""

import asyncio
import logging
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)
MIN_REQUEST_INTERVAL = 2.0


class SourceError(RuntimeError):
    """A source could not provide usable search results."""


class SourceAccessError(SourceError):
    """A source denied access or its robots rules prohibit collection."""


class SourceFetchError(SourceError):
    """A public page could not be fetched after bounded attempts."""


class SourceMarkupError(SourceError):
    """A source returned unexpected content or changed markup."""


def retry_after(value: str | None) -> float | None:
    """Interpret a Retry-After delay or timezone-aware HTTP date."""
    if value is None:
        return None
    if value.isascii() and value.isdigit():
        return float(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except ValueError, TypeError, OverflowError:
        return None
    if retry_at.utcoffset() is None:
        return None
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


def log_response(
    source: str, response: httpx.Response, attempt: int, elapsed: float
) -> None:
    """Log allowlisted metadata and fixed body hints, without raw response text."""
    content_type = response.headers.get("Content-Type", "").partition(";")[0].lower()
    headers: dict[str, str | float] = {}
    if len(content_type) <= 100 and re.fullmatch(
        r"[a-z0-9.+-]+/[a-z0-9.+-]+", content_type
    ):
        headers["content-type"] = content_type
    server = response.headers.get("Server", "").lower()
    for known in ("cloudflare", "nginx", "apache", "envoy", "microsoft-iis"):
        if server.startswith(known):
            headers["server"] = known
            break
    ray = response.headers.get("CF-Ray", "")
    if re.fullmatch(r"[0-9a-f]{16,32}(?:-[a-z]{3})?", ray, re.IGNORECASE):
        headers["cf-ray"] = ray
    if response.headers.get("CF-Mitigated", "").lower() == "challenge":
        headers["cf-mitigated"] = "challenge"
    delay = retry_after(response.headers.get("Retry-After"))
    if delay is not None:
        headers["retry-after-seconds"] = round(delay, 1)
    body = response.text[:65536].lower()
    hints = [
        label
        for marker, label in (
            ("cloudflare", "cloudflare"),
            ("just a moment", "browser_check"),
            ("verify you are human", "human_verification"),
            ("captcha", "captcha"),
            ("access denied", "access_denied"),
            ("forbidden", "forbidden"),
        )
        if marker in body
    ]
    logger.log(
        logging.WARNING if response.status_code >= 300 else logging.INFO,
        "%s response attempt=%d/3 status=%d elapsed_ms=%.0f bytes=%d "
        "headers=%s body_hints=%s",
        source,
        attempt,
        response.status_code,
        elapsed * 1000,
        len(response.content),
        headers,
        hints,
    )


class PublicSearchHttp:
    """Serialize requests and honor throttling, timeouts, and access denials."""

    def __init__(self, client: httpx.AsyncClient, source_name: str) -> None:
        self._client = client
        self._source_name = source_name
        self._lock = asyncio.Lock()
        self._next_request_at = 0.0
        self._minimum_interval = MIN_REQUEST_INTERVAL

    def respect_robots_interval(self, seconds: float) -> None:
        """Apply a source's crawl-delay or conservative request-rate interval."""
        self._minimum_interval = max(MIN_REQUEST_INTERVAL, seconds)
        self._next_request_at = max(
            self._next_request_at, monotonic() + self._minimum_interval
        )

    async def get_text(self, url: str, *, content_type: str = "text/html") -> str:
        """Read one public page with a minimum interval and three bounded attempts."""
        async with self._lock:
            for attempt in range(3):
                delay = self._next_request_at - monotonic()
                if delay > 60:
                    raise SourceFetchError("The source requested a longer cooldown.")
                if delay > 0:
                    await asyncio.sleep(delay)
                self._next_request_at = monotonic() + self._minimum_interval
                # Omit query strings and credentials from request diagnostics.
                logger.info(
                    "%s request attempt=%d/3 path=%s",
                    self._source_name,
                    attempt + 1,
                    urlsplit(url).path,
                )
                started_at = monotonic()
                try:
                    response = await self._client.get(url, follow_redirects=False)
                except httpx.TransportError as exc:
                    logger.warning(
                        "%s request failed attempt=%d/3 error=%s elapsed_ms=%.0f",
                        self._source_name,
                        attempt + 1,
                        type(exc).__name__,
                        (monotonic() - started_at) * 1000,
                    )
                    if attempt == 2:
                        raise SourceFetchError(
                            "The source could not be reached."
                        ) from exc
                    self._next_request_at = monotonic() + max(
                        self._minimum_interval, 2 ** (attempt + 1)
                    )
                    continue

                log_response(
                    self._source_name, response, attempt + 1, monotonic() - started_at
                )
                retry_delay = retry_after(response.headers.get("Retry-After"))
                if retry_delay is not None:
                    self._next_request_at = max(
                        self._next_request_at, monotonic() + retry_delay
                    )
                if response.status_code in (401, 403) or response.is_redirect:
                    raise SourceAccessError(
                        "The source refused or redirected the request."
                    )
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    if attempt == 2:
                        raise SourceFetchError("The source is temporarily unavailable.")
                    self._next_request_at = max(
                        self._next_request_at,
                        monotonic() + max(self._minimum_interval, 2 ** (attempt + 1)),
                    )
                    continue
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise SourceFetchError(
                        "The source returned an unsuccessful response."
                    ) from exc
                media_type = (
                    response.headers.get("Content-Type", "")
                    .partition(";")[0]
                    .strip()
                    .lower()
                )
                if media_type != content_type:
                    raise SourceMarkupError(
                        "The source returned an unexpected content type."
                    )
                return response.text
        raise SourceFetchError("The source could not be reached.")

    async def aclose(self) -> None:
        """Close the reusable HTTP client."""
        await self._client.aclose()
