"""Thin client for the OpenAlex works API (https://docs.openalex.org/api-entities/works).

Works without a key, but as of OpenAlex's Feb 2026 usage-based pricing change,
anonymous callers share a much smaller per-day credit budget across every
caller on the same IP - trivially exhausted on a shared/NAT'd network (a
university campus, for instance). A free API key (from openalex.org/settings/api,
set on the Settings page) gets its own private per-day budget instead - set
via credentials.get_key("openalex"), same encrypted storage as the Anthropic
key. The older `mailto` "polite pool" param is deprecated and ignored by
OpenAlex as of the same Feb 2026 change, so it's not sent here at all.
"""

import time

import requests

import credentials
import source_http
from source_http import clean_title
from title_match import title_key

OPENALEX_WORKS_URL = "https://api.openalex.org/works"

# A 429 here means the caller's per-day credit budget (anonymous or keyed)
# is exhausted, not a short traffic burst - retrying after its Retry-After
# won't help if the day's budget is genuinely gone, so this is a single
# short retry (catches a real transient blip) rather than a long blind
# blocking wait; anything longer belongs to the frontend's explicit "Retry
# fetching papers" button, not a silent multi-minute hang inside one request.
MAX_RATE_LIMIT_RETRIES = 1
MAX_RETRY_WAIT_SECONDS = 15
DEFAULT_RETRY_WAIT_SECONDS = 5


def reconstruct_abstract(inverted_index):
    """OpenAlex stores abstracts as {word: [positions]} to dodge copyright reprint
    restrictions. Rebuild the plain-text abstract from that index."""
    if not inverted_index:
        return ""

    positions = {}
    for word, idxs in inverted_index.items():
        for idx in idxs:
            positions[idx] = word

    return " ".join(positions[i] for i in sorted(positions))


def _work_to_result(work):
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}

    return {
        "id": work.get("id"),
        "title": clean_title(work.get("title") or work.get("display_name")),
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
        "year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "citation_count": work.get("cited_by_count", 0),
        "doi": work.get("doi"),
        "url": primary_location.get("landing_page_url") or work.get("id"),
        "venue": source.get("display_name"),
        "authors": [
            (authorship.get("author") or {}).get("display_name")
            for authorship in work.get("authorships") or []
        ],
        "is_review": work.get("type") == "review",
        # OpenAlex says outright whether a work was retracted, and what kind of work it is.
        "is_retracted": bool(work.get("is_retracted")),
        "work_type": work.get("type"),
    }


MAX_PER_PAGE = 200


def _search_params(query, per_page, from_date, to_date):
    params = {
        "search": query,
        "per_page": min(per_page, MAX_PER_PAGE),
        "sort": "relevance_score:desc",
    }

    filters = []
    if from_date:
        filters.append(f"from_publication_date:{from_date}")
    if to_date:
        filters.append(f"to_publication_date:{to_date}")
    if filters:
        params["filter"] = ",".join(filters)

    api_key = credentials.get_key("openalex")
    if api_key:
        params["api_key"] = api_key
    return params


def _passing_problem(exc):
    """Whether a failed request may work if asked again: no connection, a timeout or a
    server error. Not a rejected key or an unreadable reply, and not a 429: that means
    the day's credit budget is gone (see MAX_RATE_LIMIT_RETRIES above), so asking again
    would only make the user wait longer for the same answer."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status is not None and status >= 500


def _fetch_page(params):
    """One page of results as JSON. A passing problem is retried a few times, so a
    hiccup partway through a long search does not discard the pages already read."""
    for attempt in range(source_http.PAGE_ATTEMPTS):
        try:
            return _read_page(params)
        except requests.RequestException as exc:
            if attempt == source_http.PAGE_ATTEMPTS - 1 or not _passing_problem(exc):
                raise
            time.sleep(source_http.PAGE_RETRY_SECONDS * (attempt + 1))


def _read_page(params):
    response = _get_with_retry(params)
    try:
        data = response.json()
    except ValueError as exc:
        # Covers json.JSONDecodeError (and simplejson's, if ever swapped in -
        # both subclass ValueError): a 200 with a non-JSON body (maintenance
        # page, truncated response, etc). Re-raised as a RequestException so
        # callers only need to handle one exception type for "OpenAlex call
        # didn't work", regardless of which stage failed.
        raise requests.RequestException(
            f"OpenAlex returned an unreadable response: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise requests.RequestException("OpenAlex returned an unreadable response.")
    return data


def search_all(query, from_date=None, to_date=None, max_results=10_000):
    """Every work matching a keyword search, most relevant first, read page by page
    (cursor paging, which has no depth limit) until they are all fetched or
    max_results have been. Returns (results, total): total is how many works
    OpenAlex says match, so a caller can tell when it stopped short."""
    # A page no bigger than what is wanted: a search keeping 50 papers asks for 50.
    params = _search_params(query, min(MAX_PER_PAGE, max_results), from_date, to_date)
    params["cursor"] = "*"
    results = []
    total = None
    seen_cursors = set()
    while len(results) < max_results:
        params["per_page"] = min(MAX_PER_PAGE, max_results - len(results))
        data = _fetch_page(params)
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        if isinstance(meta.get("count"), int):
            total = meta["count"]
        page = data.get("results") or []
        results.extend(_work_to_result(work) for work in page)
        cursor = meta.get("next_cursor")
        # A page with nothing in it, no next cursor, or a cursor already used is
        # the end (the last check stops a reply that never advances).
        if not page or not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        params["cursor"] = cursor
    return results[:max_results], total


def _get_with_retry(params):
    """GET the works endpoint, retrying a 429 up to MAX_RATE_LIMIT_RETRIES
    times by sleeping for whatever Retry-After OpenAlex sends back (capped
    at MAX_RETRY_WAIT_SECONDS so a misbehaving/huge value can't block the
    request indefinitely). Any other status is raised immediately via
    raise_for_status() - a retry can't fix a real 4xx/5xx."""
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        response = requests.get(OPENALEX_WORKS_URL, params=params, timeout=20)
        if response.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
            try:
                wait = min(float(response.headers.get("Retry-After")), MAX_RETRY_WAIT_SECONDS)
            except (TypeError, ValueError):
                wait = DEFAULT_RETRY_WAIT_SECONDS
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response


def dedupe_key(result):
    """What identifies a paper across sources: its DOI, else its normalized title
    and year. A paper with neither a DOI nor a usable title is never merged."""
    if result.get("doi"):
        return ("doi", result["doi"].lower())
    key = title_key(result.get("title"))
    if not key:
        return ("id", result.get("source", "openalex"), result.get("id"))
    return ("title", key, result.get("year"))


def dedupe(results_lists):
    """Merge several result lists (e.g. one per expanded query), deduplicating
    by DOI first, then by normalized title+year - the same matching plan
    calls for across sources (see PLAN.md's Core pipeline), kept here even
    though every list currently comes from OpenAlex so it doesn't need
    reworking when PubMed/Semantic Scholar are added.

    The same paper can appear in more than one expanded query's results in
    the same search - when a later duplicate has an abstract and the
    already-kept copy doesn't, backfill it onto the kept copy instead of
    just discarding the duplicate outright (reconstruct_abstract() returns
    '' rather than None for a missing abstract, so blank-ness is checked
    with .strip(), not an `is None` check). This mirrors the same backfill
    db.get_or_create_paper() does for duplicates seen across separate
    searches - without both, whichever occurrence happens to be encountered
    first keeps its (possibly missing) abstract forever."""
    seen = {}
    merged = []
    for results in results_lists:
        for result in results:
            key = dedupe_key(result)
            if key in seen:
                existing = seen[key]
                if not (existing.get("abstract") or "").strip() and (result.get("abstract") or "").strip():
                    existing["abstract"] = result["abstract"]
                continue
            seen[key] = result
            merged.append(result)
    return merged
