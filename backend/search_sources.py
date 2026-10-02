"""Paper-search sources a dataset can be retrieved from.

Every source returns results in the shape openalex._work_to_result() does (id,
title, abstract, year, publication_date, citation_count, doi, url, venue,
authors, is_review) plus a `source` name, and reports DOIs as https://doi.org/...
so the same paper found through two sources dedupes (openalex.dedupe and
db.get_or_create_paper match on DOI first).

OpenAlex is searched by openalex.py (errors are requests exceptions, handled
by the app). The others raise SourceError, whose message is written for the
user. Semantic Scholar and Elsevier (Scopus) need a saved API key; PubMed
(NCBI E-utilities) needs none.

Springer Nature isn't a search source: its API only matches strictly, so a search
returned just a few papers. It is used to look up abstracts (abstracts.py).

Scopus search results carry no abstract or full author list with a free key,
so those papers come in without abstracts; the dataset page's "Find missing
abstracts" button fills them in.
"""

import calendar
import datetime
import functools
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, Optional

import credentials
import openalex
from source_http import SourceError, clean_text, doi_url, get, json_of, ncbi_get, semanticscholar_get

PER_PAGE = 50
# Scopus Search returns at most 25 results per request without a subscription.
SCOPUS_PER_PAGE = 25


@dataclass(frozen=True)
class SearchSource:
    id: str
    label: str
    # search(query, from_date, to_date): the dates are "YYYY-MM-DD" or None.
    search: Callable[[str, Optional[str], Optional[str]], list]
    # Credential provider a key must be saved under (None = no key needed).
    required_credential: Optional[str] = None


def _year(value):
    match = re.match(r"\d{4}", value or "")
    return int(match.group()) if match else None


def _span(result):
    """(earliest, latest) "YYYY-MM-DD" a result could have been published on, or
    (None, None) if nothing is known. A source that knows only the month or year
    (`date_precision` "month" or "year", with the date filled in as the 1st) could
    have published on any day of it."""
    date = result.get("publication_date")
    year = result.get("year")
    precision = result.get("date_precision")
    if date and precision == "month":
        y, m = int(date[:4]), int(date[5:7])
        return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
    if date and precision == "year":
        return f"{date[:4]}-01-01", f"{date[:4]}-12-31"
    if date:
        return date, date
    if year:
        return f"{year:04d}-01-01", f"{year:04d}-12-31"
    return None, None


def _in_range(result, from_date, to_date):
    """Whether a result could fall within the "YYYY-MM-DD" bounds (either may be
    None): it is kept unless every day it might have been published on is outside
    them. A result with no date at all is kept."""
    earliest, latest = _span(result)
    if from_date and latest and latest < from_date:
        return False
    if to_date and earliest and earliest > to_date:
        return False
    return True


def _filtered(search):
    """Wrap a source's search so it only returns papers inside the requested
    dates. Each source narrows the search its own way (some only by year, and
    PubMed's date filter also matches a paper's print issue date), so this makes
    the shown dates decide. A blank end means "present", so it defaults to today:
    an open-ended range can't return papers dated in the future (early-access or
    in-press records some sources give a coming year or issue date). An end the
    user typed is honored, even a future one, and so is a future start with no end."""

    @functools.wraps(search)
    def wrapper(query, from_date, to_date):
        today = datetime.date.today().isoformat()
        if not to_date and (not from_date or from_date <= today):
            to_date = today
        return [r for r in search(query, from_date, to_date) if _in_range(r, from_date, to_date)]

    return wrapper


def _year_of(date):
    return int(date[:4]) if date else None


@_filtered
def _search_openalex(query, from_date, to_date):
    return openalex.search_works(query, per_page=PER_PAGE, from_date=from_date, to_date=to_date)


@_filtered
def _search_semanticscholar(query, from_date, to_date):
    params = {
        "query": query,
        "limit": PER_PAGE,
        "fields": "title,abstract,year,publicationDate,citationCount,externalIds,venue,authors,url,publicationTypes",
    }
    if from_date or to_date:
        # Narrowed by year here; _filtered applies the exact dates.
        params["year"] = f"{_year_of(from_date) or ''}-{_year_of(to_date) or ''}"
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


def _scopus_query(query, from_date, to_date):
    # Scopus's query language treats quotes, brackets and braces specially.
    words = re.sub(r'[(){}\[\]"\\]', " ", query).strip()
    scopus = f"TITLE-ABS-KEY({words})"
    # Narrowed by year here; _filtered applies the exact dates.
    if from_date:
        scopus += f" AND PUBYEAR > {_year_of(from_date) - 1}"
    if to_date:
        scopus += f" AND PUBYEAR < {_year_of(to_date) + 1}"
    return scopus


@_filtered
def _search_scopus(query, from_date, to_date):
    response = get(
        "Elsevier",
        "https://api.elsevier.com/content/search/scopus",
        params={"query": _scopus_query(query, from_date, to_date), "count": SCOPUS_PER_PAGE},
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


_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_MONTHS = {
    m: i
    for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)
}


def _text(element):
    """All the text inside an XML element, including text within inline tags
    (italics, subscripts), as clean plain text."""
    return clean_text("".join(element.itertext())) if element is not None else ""


def _pubmed_date(article):
    """(year, date, precision) for a PubmedArticle. Prefers the electronic
    publication date, then the journal issue date. The date is "YYYY-MM-DD", with
    the 1st filled in when PubMed has only a month or a year; precision says which
    ("day", "month" or "year")."""
    node = article.find(".//Article/ArticleDate")
    if node is None:
        node = article.find(".//Article/Journal/JournalIssue/PubDate")
    if node is None:
        return None, None, None
    year = _year(node.findtext("Year")) or _year(node.findtext("MedlineDate"))
    if not year:
        return None, None, None
    month = (node.findtext("Month") or "").strip()
    month = int(month) if month.isdigit() else _MONTHS.get(month[:3].lower())
    day = (node.findtext("Day") or "").strip()
    if month and day.isdigit():
        return year, f"{year:04d}-{month:02d}-{int(day):02d}", "day"
    if month:
        return year, f"{year:04d}-{month:02d}-01", "month"
    return year, f"{year:04d}-01-01", "year"


def _pubmed_result(article):
    pmid = article.findtext(".//MedlineCitation/PMID")
    title = _text(article.find(".//Article/ArticleTitle"))
    if not pmid or not title:
        return None
    # Structured abstracts come in labeled parts (BACKGROUND, METHODS, ...).
    parts = []
    for node in article.findall(".//Article/Abstract/AbstractText"):
        text = _text(node)
        if text:
            label = node.get("Label")
            parts.append(f"{label.capitalize()}: {text}" if label else text)
    doi = None
    for node in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
        if node.get("IdType") == "doi":
            doi = doi_url(node.text)
    authors = []
    for node in article.findall(".//Article/AuthorList/Author"):
        collective = node.findtext("CollectiveName")
        name = " ".join(p for p in (node.findtext("ForeName"), node.findtext("LastName")) if p)
        if name or collective:
            authors.append(name or collective)
    year, date, date_precision = _pubmed_date(article)
    types = [_text(t) for t in article.findall(".//Article/PublicationTypeList/PublicationType")]
    return {
        "source": "pubmed",
        "id": pmid.strip(),
        "title": title,
        "abstract": " ".join(parts),
        "year": year,
        "publication_date": date,
        # How much of the date PubMed knows; only used by _in_range.
        "date_precision": date_precision,
        # PubMed has no citation counts; OpenAlex's record wins when both find a paper.
        "citation_count": 0,
        "doi": doi,
        "url": doi or f"https://pubmed.ncbi.nlm.nih.gov/{pmid.strip()}/",
        "venue": _text(article.find(".//Article/Journal/Title")) or None,
        "authors": authors,
        "is_review": "Review" in types,
    }


@_filtered
def _search_pubmed(query, from_date, to_date):
    # Square brackets are PubMed field tags ("[Author]"), which a topic never needs.
    term = re.sub(r"[\[\]]", " ", query).strip()
    params = {"db": "pubmed", "term": term, "retmax": PER_PAGE, "retmode": "json", "sort": "relevance"}
    if from_date or to_date:
        params.update(
            {
                "datetype": "pdat",
                "mindate": (from_date or "1800-01-01").replace("-", "/"),
                "maxdate": (to_date or "3000-12-31").replace("-", "/"),
            }
        )
    response = ncbi_get(f"{_EUTILS}/esearch.fcgi", params)
    if response.status_code != 200:
        raise SourceError(f"PubMed returned an error (HTTP {response.status_code}).")
    body = json_of(response, "PubMed")
    # NCBI can report an error (a rate limit, for one) in a normal 200 reply, which
    # must not be read as "no results": that would leave the dataset silently
    # without PubMed papers.
    if body.get("error"):
        raise SourceError(f"PubMed could not run this search: {body['error']}")
    data = body.get("esearchresult")
    if not isinstance(data, dict):
        raise SourceError("PubMed returned an unreadable response.")
    if data.get("ERROR"):
        raise SourceError(f"PubMed could not run this search: {data['ERROR']}")
    ids = data.get("idlist") or []
    if not ids:
        return []

    response = ncbi_get(f"{_EUTILS}/efetch.fcgi", {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
    if response.status_code != 200:
        raise SourceError(f"PubMed returned an error (HTTP {response.status_code}).")
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise SourceError("PubMed returned an unreadable response.") from exc
    if root.tag != "PubmedArticleSet" or root.find("ERROR") is not None:
        raise SourceError("PubMed could not return the papers for this search.")
    by_id = {}
    for article in root.findall("PubmedArticle"):
        result = _pubmed_result(article)
        if result:
            by_id[result["id"]] = result
    # efetch doesn't promise the order esearch ranked them in. (PubMed's date
    # filter also matches a paper's print issue date, which is why _filtered
    # re-checks the shown dates.)
    return [by_id[pmid] for pmid in ids if pmid in by_id]


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
    SearchSource("pubmed", "PubMed", _search_pubmed),
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
