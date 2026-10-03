"""HTTP helpers shared by the scholarly-API modules (abstracts.py for abstract
lookup, search_sources.py for paper search).

A SourceError means a source can't be used right now (rejected key, quota or
rate limit reached, unreachable, unreadable reply); its message is written for
the user. Callers either stop using that source for the rest of the run
(abstract lookup) or report it and fail the search (paper search).
"""

import html
import re
import threading
import time
from urllib.parse import quote, urlparse

import requests

import credentials
from title_match import INLINE_TAG_RE

REQUEST_TIMEOUT = 20
USER_AGENT = "lit-review/0.1 (local research tool)"

# Semantic Scholar's unauthenticated pool is about one request per second,
# shared with everyone else; a saved key raises it.
_SEMANTIC_SCHOLAR_MIN_INTERVAL = 1.1
_last_semantic_scholar_call = 0.0


class SourceError(Exception):
    """This source can't be used right now."""


class SourceUnavailable(SourceError):
    """The source is having a passing problem (a rate limit, a server error, a
    dropped connection), so asking again a moment later can work."""


# A long search reads many pages. One passing problem partway through must not throw
# away the pages already read, so each page is asked for again a few times.
PAGE_ATTEMPTS = 3
PAGE_RETRY_SECONDS = 2


def retry_unavailable(fetch):
    """The result of fetch(), asked again (after a growing wait) when it raises
    SourceUnavailable, up to PAGE_ATTEMPTS times. Any other error is raised at once."""
    for attempt in range(PAGE_ATTEMPTS):
        try:
            return fetch()
        except SourceUnavailable:
            if attempt == PAGE_ATTEMPTS - 1:
                raise
            time.sleep(PAGE_RETRY_SECONDS * (attempt + 1))


def normalize_doi(doi):
    """Bare lowercase DOI, from either a bare DOI or a https://doi.org/ URL."""
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", (doi or "").strip(), flags=re.I).lower()


def quote_doi(doi):
    """A bare DOI made safe to put in a URL path. Some DOIs hold characters that
    mean something in a URL (older Wiley DOIs have <, > and #; some have ?), which
    would otherwise cut the path short or start a query string, so the lookup
    would ask about the wrong DOI and answer "not found"."""
    return quote(normalize_doi(doi), safe="/()")


def raise_if_unavailable(source_label, response):
    """Raise SourceError if the reply says the source is having trouble (a
    server error, or a rate limit not already handled), as opposed to a
    well-formed answer such as "no such paper". A lookup that ran into trouble
    must not be recorded as "asked and not found", or the paper would never be
    tried again."""
    status = response.status_code
    if status == 429 or status >= 500:
        raise SourceUnavailable(f"{source_label} is having trouble right now (HTTP {status}). Try again later.")


def doi_url(doi):
    """The https://doi.org/... form OpenAlex uses, which is what papers are
    deduped on, so every source should report its DOIs this way."""
    doi = normalize_doi(doi)
    return f"https://doi.org/{doi}" if doi else None


_SECRET_PARAM = re.compile(r"((?:api[_-]?key|apikey|key|token)=)[^&\s'\"]+", re.I)


def redact(text):
    """`text` with the value of any api_key/key/token query parameter hidden.
    requests puts the full URL, query string included, in its error messages,
    and some sources (OpenAlex, Springer Nature) take the key as a parameter, so
    anything that logs an exception must pass it through here first."""
    return _SECRET_PARAM.sub(r"\1REDACTED", str(text))


def safe_url(value):
    """`value` stripped if it is an http(s) URL with a host, else None. Paper
    links come from outside APIs or are typed in by the user, and are opened in
    the browser, so schemes like javascript: or data: must never be kept."""
    value = (value or "").strip() if isinstance(value, str) else ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    return value if parsed.scheme in ("http", "https") and parsed.netloc else None


def clean_text(text):
    """Plain text from an API's text field (which may carry JATS/HTML tags)."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    # Some publishers prefix an abstract with the word "Abstract".
    return re.sub(r"^abstract\s*[:.\-]?\s+(?=\S)", "", text, flags=re.I)


def clean_title(title):
    """A paper title without the inline markup (<i>, <sub>...) some APIs leave in
    it. Unlike clean_text it keeps a leading "Abstract", which can be a real word."""
    if not title:
        return title
    return re.sub(r"\s+", " ", html.unescape(INLINE_TAG_RE.sub("", title))).strip()


def get(source_label, url, **kwargs):
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    try:
        return requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise SourceUnavailable(f"Could not reach {source_label}.") from exc


def json_of(response, source_label):
    try:
        return response.json()
    except ValueError as exc:
        raise SourceError(f"{source_label} returned an unreadable response.") from exc


# NCBI allows 3 requests per second without an API key.
_NCBI_MIN_INTERVAL = 0.4
_last_ncbi_call = 0.0
_NCBI_LOCK = threading.Lock()


def ncbi_get(url, params):
    """GET an NCBI E-utilities URL, spaced out to the keyless rate limit and
    retried once on a 429. Returns the response (the caller handles other
    statuses); raises SourceError if it stays rate limited."""
    global _last_ncbi_call
    params = {"tool": "lit-review", **params}
    for attempt in range(2):
        with _NCBI_LOCK:
            wait = _NCBI_MIN_INTERVAL - (time.monotonic() - _last_ncbi_call)
            if wait > 0:
                time.sleep(wait)
            _last_ncbi_call = time.monotonic()
        response = get("PubMed", url, params=params)
        if response.status_code != 429:
            return response
        if attempt == 0:
            time.sleep(2)
    raise SourceUnavailable("PubMed's rate limit was reached. Try again in a moment.")


SEMANTIC_SCHOLAR_KEY_REJECTED = (
    "Semantic Scholar rejected the saved API key. Keys can be revoked after 60 days without "
    "use; request a new one at semanticscholar.org/product/api and save it in Settings."
)


def _semanticscholar_request(url, params, key):
    """One Semantic Scholar GET, with `key` (or none), spaced out to its rate
    limit when there's no key and retried once on a 429. Raises SourceError if
    it stays rate limited."""
    global _last_semantic_scholar_call
    headers = {}
    if key:
        headers["x-api-key"] = key
    else:
        wait = _SEMANTIC_SCHOLAR_MIN_INTERVAL - (time.monotonic() - _last_semantic_scholar_call)
        if wait > 0:
            time.sleep(wait)

    for attempt in range(2):
        _last_semantic_scholar_call = time.monotonic()
        response = get("Semantic Scholar", url, params=params, headers=headers)
        if response.status_code != 429:
            return response
        if attempt == 0:
            time.sleep(3)
    if key:
        raise SourceUnavailable("Semantic Scholar's rate limit was reached. Try again in a moment.")
    raise SourceUnavailable(
        "Semantic Scholar's rate limit was reached. A free Semantic Scholar API key in "
        "Settings raises it."
    )


def semanticscholar_get(url, params, keyless_fallback=False):
    """GET a Semantic Scholar Graph API URL with the saved key, if any.
    Returns the response (the caller handles other statuses); raises
    SourceError if it stays rate limited or the saved key is rejected.

    A rejected key (they're revoked after 60 days without use) is retried
    without it when keyless_fallback is set, which suits lookups that work,
    just more slowly, with no key; otherwise it raises, with a message saying
    how to get a new one."""
    key = credentials.get_key("semanticscholar")
    response = _semanticscholar_request(url, params, key)
    if key and response.status_code in (401, 403):
        if not keyless_fallback:
            raise SourceError(SEMANTIC_SCHOLAR_KEY_REJECTED)
        response = _semanticscholar_request(url, params, None)
    return response
