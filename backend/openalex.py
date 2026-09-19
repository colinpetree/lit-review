"""Thin client for the OpenAlex works API (https://docs.openalex.org/api-entities/works).

No API key required. OpenAlex asks polite-pool users to identify themselves via a
`mailto` query param for better rate limits/support - set OPENALEX_MAILTO to opt in.
"""

import os

import requests

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
DEFAULT_PER_PAGE = 25


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
        "title": work.get("title") or work.get("display_name"),
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
        "year": work.get("publication_year"),
        "citation_count": work.get("cited_by_count", 0),
        "doi": work.get("doi"),
        "url": primary_location.get("landing_page_url") or work.get("id"),
        "venue": source.get("display_name"),
        "authors": [
            (authorship.get("author") or {}).get("display_name")
            for authorship in work.get("authorships") or []
        ],
        "is_review": work.get("type") == "review",
    }


def search_works(query, per_page=DEFAULT_PER_PAGE, from_year=None, to_year=None):
    """Run a keyword search against OpenAlex and return a flat list of results."""
    params = {
        "search": query,
        "per_page": min(per_page, 200),
        "sort": "relevance_score:desc",
    }

    filters = []
    if from_year:
        filters.append(f"from_publication_date:{from_year}-01-01")
    if to_year:
        filters.append(f"to_publication_date:{to_year}-12-31")
    if filters:
        params["filter"] = ",".join(filters)

    mailto = os.environ.get("OPENALEX_MAILTO")
    if mailto:
        params["mailto"] = mailto

    response = requests.get(OPENALEX_WORKS_URL, params=params, timeout=20)
    response.raise_for_status()
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

    return [_work_to_result(work) for work in data.get("results", [])]


def dedupe(results_lists):
    """Merge several result lists (e.g. one per expanded query), deduplicating
    by DOI first, then by normalized title+year - the same matching plan
    calls for across sources (see PLAN.md's Core pipeline), kept here even
    though every list currently comes from OpenAlex so it doesn't need
    reworking when PubMed/Semantic Scholar are added."""
    seen = set()
    merged = []
    for results in results_lists:
        for result in results:
            if result.get("doi"):
                key = ("doi", result["doi"].lower())
            else:
                key = ("title", (result.get("title") or "").strip().lower(), result.get("year"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(result)
    return merged
