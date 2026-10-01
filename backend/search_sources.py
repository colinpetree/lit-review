"""Paper-search sources a dataset can be retrieved from.

Every source returns results in the shape openalex._work_to_result() does (id,
title, abstract, year, publication_date, citation_count, doi, url, venue,
authors, is_review) plus a `source` name, and reports DOIs as https://doi.org/...
so the same paper found through two sources dedupes (openalex.dedupe and
db.get_or_create_paper match on DOI first).

OpenAlex is searched by openalex.py (errors are requests exceptions, handled
by the app). The others raise SourceError, whose message is written for the
user. Semantic Scholar and Elsevier (Scopus) need a saved API key.

Springer Nature isn't a search source: its API only matches strictly, so a search
returned just a few papers. It is used to look up abstracts (abstracts.py).

Scopus search results carry no abstract or full author list with a free key,
so those papers come in without abstracts; the dataset page's "Find missing
abstracts" button fills them in.
"""

import re
from dataclasses import dataclass
from typing import Callable, Optional

import credentials
import openalex
from source_http import SourceError, clean_text, doi_url, get, json_of, semanticscholar_get

PER_PAGE = 50
# Scopus Search returns at most 25 results per request without a subscription.
SCOPUS_PER_PAGE = 25


@dataclass(frozen=True)
class SearchSource:
    id: str
    label: str
    search: Callable[[str, Optional[int], Optional[int]], list]
    # Credential provider a key must be saved under (None = no key needed).
    required_credential: Optional[str] = None


def _year(value):
    match = re.match(r"\d{4}", value or "")
    return int(match.group()) if match else None


def _search_openalex(query, from_year, to_year):
    return openalex.search_works(query, per_page=PER_PAGE, from_year=from_year, to_year=to_year)


def _search_semanticscholar(query, from_year, to_year):
    params = {
        "query": query,
        "limit": PER_PAGE,
        "fields": "title,abstract,year,publicationDate,citationCount,externalIds,venue,authors,url,publicationTypes",
    }
    if from_year or to_year:
        params["year"] = f"{from_year or ''}-{to_year or ''}"
    response = semanticscholar_get("https://api.semanticscholar.org/graph/v1/paper/search", params)
    if response.status_code in (400, 404):
        return []
    if response.status_code != 200:
        raise SourceError(f"Semantic Scholar returned an error (HTTP {response.status_code}).")

    results = []
    for item in json_of(response, "Semantic Scholar").get("data") or []:
        if not item.get("title") or not item.get("paperId"):
            continue
        doi = doi_url((item.get("externalIds") or {}).get("DOI"))
        results.append(
            {
                "source": "semanticscholar",
                "id": item["paperId"],
                "title": item["title"],
                "abstract": clean_text(item.get("abstract")),
                "year": item.get("year"),
                "publication_date": item.get("publicationDate"),
                "citation_count": item.get("citationCount") or 0,
                "doi": doi,
                "url": doi or item.get("url"),
                "venue": item.get("venue") or None,
                "authors": [a.get("name") for a in item.get("authors") or [] if a.get("name")],
                "is_review": "Review" in (item.get("publicationTypes") or []),
            }
        )
    return results


def _scopus_query(query, from_year, to_year):
    # Scopus's query language treats quotes, brackets and braces specially.
    words = re.sub(r'[(){}\[\]"\\]', " ", query).strip()
    scopus = f"TITLE-ABS-KEY({words})"
    if from_year:
        scopus += f" AND PUBYEAR > {from_year - 1}"
    if to_year:
        scopus += f" AND PUBYEAR < {to_year + 1}"
    return scopus


def _search_scopus(query, from_year, to_year):
    response = get(
        "Elsevier",
        "https://api.elsevier.com/content/search/scopus",
        params={"query": _scopus_query(query, from_year, to_year), "count": SCOPUS_PER_PAGE},
        headers={"X-ELS-APIKey": credentials.get_key("elsevier"), "Accept": "application/json"},
    )
    if response.status_code in (401, 403):
        raise SourceError("Elsevier rejected the API key or your access level.")
    if response.status_code == 429:
        raise SourceError("Elsevier's usage quota for this key has been reached.")
    if response.status_code == 404:
        return []
    if response.status_code != 200:
        raise SourceError(f"Elsevier returned an error (HTTP {response.status_code}).")

    results = []
    for entry in (json_of(response, "Elsevier").get("search-results") or {}).get("entry") or []:
        # An empty result set comes back as one entry holding an "error" note.
        if entry.get("error") or not entry.get("dc:title") or not entry.get("dc:identifier"):
            continue
        cover_date = entry.get("prism:coverDate")
        creator = entry.get("dc:creator")
        results.append(
            {
                "source": "scopus",
                "id": entry["dc:identifier"],
                "title": entry["dc:title"],
                "abstract": "",
                "year": _year(cover_date),
                "publication_date": cover_date,
                "citation_count": int(entry.get("citedby-count") or 0),
                "doi": doi_url(entry.get("prism:doi")),
                "url": doi_url(entry.get("prism:doi")),
                "venue": entry.get("prism:publicationName"),
                # A free key returns only the first author.
                "authors": [creator] if creator else [],
                "is_review": entry.get("subtypeDescription") == "Review",
            }
        )
    return results


# In the order sources are searched. OpenAlex goes first so that when the same
# paper turns up in several sources its record (the fullest one) is kept.
SEARCH_SOURCES = [
    SearchSource("openalex", "OpenAlex", _search_openalex),
    # Needs a key to search: the shared keyless limit is usually used up, so a
    # keyless search would mostly fail. (Abstract lookup still tries it keyless.)
    SearchSource(
        "semanticscholar", "Semantic Scholar", _search_semanticscholar, required_credential="semanticscholar"
    ),
    SearchSource("elsevier", "Elsevier (Scopus)", _search_scopus, required_credential="elsevier"),
]
SEARCH_SOURCES_BY_ID = {source.id: source for source in SEARCH_SOURCES}
DEFAULT_SOURCES = ["openalex"]


def validate_sources(value):
    """The requested source ids as a list in search order, defaulting to
    OpenAlex. Raises ValueError (message safe to show) for an unknown source,
    an empty list, or a source that needs an API key that isn't saved."""
    if value is None:
        return list(DEFAULT_SOURCES)
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise ValueError("'sources' must be a non-empty list of source ids")
    unknown = [v for v in value if v not in SEARCH_SOURCES_BY_ID]
    if unknown:
        raise ValueError(f"Unknown paper source: {unknown[0]}")
    chosen = [source for source in SEARCH_SOURCES if source.id in set(value)]
    for source in chosen:
        if source.required_credential and not credentials.has_key(source.required_credential):
            raise ValueError(f"{source.label} needs an API key. Add one in Settings.")
    return [source.id for source in chosen]
