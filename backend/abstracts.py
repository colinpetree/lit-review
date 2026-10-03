"""Look up a missing abstract by DOI from scholarly APIs.

OpenAlex leaves some abstracts out (publishers such as Elsevier and Springer
Nature don't allow them to be redistributed). Each source here is tried in
order until one returns a real abstract: the publisher's own API first (for
DOIs it covers, when the user has saved a key), then Semantic Scholar, then
Europe PMC. Only full abstract text is accepted, never a snippet, so the LLM keeps
judging real abstracts (see llm.MIN_ABSTRACT_CHARS).

A source that can't be used for the rest of a run (rejected key, quota or rate
limit reached, unreachable even after a few tries) raises SourceError; the caller
stops using that source and reports the message instead of failing the whole lookup.
"""

import logging
from dataclasses import dataclass
from typing import Callable, NamedTuple, Optional

import credentials
from llm import MIN_ABSTRACT_CHARS
from source_http import (
    SourceError,
    clean_text,
    get,
    json_of,
    normalize_doi,
    quote_doi,
    raise_if_unavailable,
    retry_unavailable,
    semanticscholar_get,
)
from title_match import titles_match

log = logging.getLogger(__name__)


class Found(NamedTuple):
    """What a source returned for a DOI: the abstract, and the title of the
    paper it belongs to (None if the source doesn't say), so the caller can
    check that the DOI led to the paper it expected."""

    abstract: str
    title: Optional[str]


@dataclass(frozen=True)
class Source:
    id: str
    label: str
    lookup: Callable[[str], Optional[Found]]
    # Credential provider a key must be saved under for this source to run
    # (None = no key needed) and the DOI prefixes it is worth asking about
    # (None = any DOI).
    required_credential: Optional[str] = None
    prefixes: Optional[tuple] = None


def _query_safe(doi):
    """A DOI for use inside a quoted search expression: quotes and backslashes
    would end the expression early (and no real DOI needs them)."""
    return doi.replace('"', "").replace("\\", "")


def _elsevier(doi):
    # Scopus Abstract Retrieval with the META_ABS view returns the abstract
    # with a free non-commercial key; the ScienceDirect article endpoint and
    # the plain META view do not.
    response = get(
        "Elsevier",
        f"https://api.elsevier.com/content/abstract/doi/{quote_doi(doi)}",
        params={"view": "META_ABS"},
        headers={"X-ELS-APIKey": credentials.get_key("elsevier"), "Accept": "application/json"},
    )
    if response.status_code == 404:
        return None
    if response.status_code in (401, 403):
        raise SourceError("Elsevier rejected the API key or your access level.")
    if response.status_code == 429:
        raise SourceError("Elsevier's usage quota for this key has been reached.")
    raise_if_unavailable("Elsevier", response)
    if response.status_code != 200:
        return None
    coredata = (json_of(response, "Elsevier").get("abstracts-retrieval-response") or {}).get("coredata") or {}
    return Found(clean_text(coredata.get("dc:description")), clean_text(coredata.get("dc:title")))


def _springer(doi):
    response = get(
        "Springer Nature",
        "https://api.springernature.com/meta/v2/json",
        params={"q": f"doi:{_query_safe(doi)}", "api_key": credentials.get_key("springernature")},
    )
    if response.status_code in (401, 403):
        raise SourceError("Springer Nature rejected the API key.")
    if response.status_code == 429:
        raise SourceError("Springer Nature's usage limit for this key has been reached.")
    raise_if_unavailable("Springer Nature", response)
    if response.status_code != 200:
        return None
    records = json_of(response, "Springer Nature").get("records") or []
    if not records or normalize_doi(records[0].get("doi")) != doi:
        return None
    return Found(clean_text(records[0].get("abstract")), clean_text(records[0].get("title")))


def _europepmc(doi):
    response = get(
        "Europe PMC",
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": f'DOI:"{_query_safe(doi)}"', "resultType": "core", "format": "json", "pageSize": 1},
    )
    raise_if_unavailable("Europe PMC", response)
    if response.status_code != 200:
        return None
    results = (json_of(response, "Europe PMC").get("resultList") or {}).get("result") or []
    # A DOI query can still return a near match, so require the same DOI.
    if not results or normalize_doi(results[0].get("doi")) != doi:
        return None
    return Found(clean_text(results[0].get("abstractText")), clean_text(results[0].get("title")))


def _semanticscholar(doi):
    # A lapsed key falls back to a keyless request: a lookup still works that way.
    response = semanticscholar_get(
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote_doi(doi)}",
        {"fields": "abstract,title"},
        keyless_fallback=True,
    )
    raise_if_unavailable("Semantic Scholar", response)
    if response.status_code != 200:
        return None
    data = json_of(response, "Semantic Scholar")
    return Found(clean_text(data.get("abstract")), clean_text(data.get("title")))


# Tried in this order: publisher APIs are the only way to get their abstracts, then
# Semantic Scholar (a lapsed key still works keyless, at its lower rate limit), and
# Europe PMC last: it is open and unrestricted, but it can be slow to answer, and a paper
# found by an earlier source never has to wait for it.
SOURCES = [
    Source("elsevier", "Elsevier (Scopus)", _elsevier, required_credential="elsevier", prefixes=("10.1016/",)),
    Source(
        "springer",
        "Springer Nature",
        _springer,
        required_credential="springernature",
        prefixes=("10.1007/", "10.1038/", "10.1186/"),
    ),
    Source("semanticscholar", "Semantic Scholar", _semanticscholar),
    Source("europepmc", "Europe PMC", _europepmc),
]
SOURCE_IDS = {source.id for source in SOURCES}


def _applies(source, doi):
    if source.required_credential and not credentials.has_key(source.required_credential):
        return False
    return source.prefixes is None or doi.startswith(source.prefixes)


class Lookup(NamedTuple):
    """What looking a paper up found. abstract/source are None if nothing usable was
    found. errors maps a source id to its SourceError message for any source that failed
    (the caller should skip those sources from then on). answered is the sources that
    replied this time without an error. complete is whether every source that applies to
    this DOI has now answered (this time or before), which is what lets the paper be
    recorded as looked up: one source being down or skipped must not stand for it having
    been asked."""

    abstract: Optional[str]
    source: Optional[str]
    errors: dict
    answered: frozenset
    complete: bool


def lookup_abstract(doi, skip_sources=frozenset(), title=None, answered_before=frozenset()):
    """Try each applicable source for one DOI, except the ones that already answered "no
    abstract" for this paper (answered_before) or that are to be skipped (they failed
    earlier in the run). Returns a Lookup.

    If `title` (the paper's own) is given, an abstract whose paper title
    clearly differs from it is skipped: the DOI led to a different paper in
    that source, so its abstract would be the wrong one."""
    doi = normalize_doi(doi)
    errors = {}
    answered = set()
    if not doi:
        return Lookup(None, None, errors, frozenset(), False)
    applicable = [source for source in SOURCES if _applies(source, doi)]
    for source in applicable:
        if source.id in answered_before or source.id in skip_sources or source.id in errors:
            continue
        try:
            # A passing problem (a dropped connection, a rate limit, a server error) is
            # asked again a few times: one hiccup must not switch the source off for every
            # paper that is left in the run. A source that is too slow to answer is not: it
            # is skipped for the rest of the run (the next source takes over, and a later
            # lookup tries it again) instead of costing a minute per paper.
            found = retry_unavailable(lambda: source.lookup(doi), retry_timeouts=False)
        except SourceError as exc:
            errors[source.id] = str(exc)
            continue
        answered.add(source.id)
        if not found or len(found.abstract) < MIN_ABSTRACT_CHARS:
            continue
        if title and not titles_match(title, found.title):
            log.info("Skipped %s abstract for %s: its title %r doesn't match %r", source.id, doi, found.title, title)
            continue
        return Lookup(found.abstract, source.id, errors, frozenset(answered), True)
    complete = all(source.id in answered or source.id in answered_before for source in applicable)
    return Lookup(None, None, errors, frozenset(answered), complete)


def find_abstract(doi, skip_sources=frozenset(), title=None):
    """lookup_abstract as (abstract, source_id, errors, answered), answered being how many
    sources replied without an error (0 means the lookup did not really happen)."""
    found = lookup_abstract(doi, skip_sources, title)
    return found.abstract, found.source, found.errors, len(found.answered)
