"""Look up a missing abstract by DOI from scholarly APIs.

OpenAlex leaves some abstracts out (publishers such as Elsevier and Springer
Nature don't allow them to be redistributed). Each source here is tried in
order until one returns a real abstract: the publisher's own API first (for
DOIs it covers, when the user has saved a key), then Semantic Scholar, then
Europe PMC. Only full abstract text is accepted, never a snippet, so the LLM keeps
judging real abstracts (see llm.MIN_ABSTRACT_CHARS).

Papers are looked up a chunk at a time (lookup_batch). Semantic Scholar and Europe PMC
are each asked about the whole chunk in one request, which is what keeps a lookup fast:
asked one paper at a time, Semantic Scholar's rate limit alone cost over a second a paper.
The publishers' APIs have no such request, so they are asked per paper, side by side.

A source that can't be used for the rest of a run (rejected key, quota or rate
limit reached, unreachable even after a few tries) raises SourceError; the caller
stops using that source and reports the message instead of failing the whole lookup.
"""

import logging
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, NamedTuple, Optional

import credentials
from llm import MIN_ABSTRACT_CHARS
from source_http import (
    LOOKUP_TIMEOUT,
    SourceError,
    clean_text,
    get,
    json_of,
    normalize_doi,
    quote_doi,
    raise_if_unavailable,
    redact,
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
    # Asks about several DOIs in one request: takes a list of bare DOIs and returns
    # {doi: Found or None} for the DOIs it answered for (a DOI left out was not answered),
    # or None when the source refused the request as a whole, so each DOI is asked alone.
    batch: Optional[Callable[[list], Optional[dict]]] = None
    batch_size: int = 1


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
        timeout=LOOKUP_TIMEOUT,
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
        timeout=LOOKUP_TIMEOUT,
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


EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
# Europe PMC is often slow to answer, and that is just how it is. One batch request stands in
# for up to 25 single ones, and a timeout skips Europe PMC for the rest of the run (it is not
# asked again), so the batch gets longer to answer than a single request: 5 s to connect,
# 60 s to answer. A chunk can then hold a backup restore past its 30 s wait on a slow day
# (the restore is refused and can be tried again), which is the price of not losing Europe
# PMC's abstracts whenever it is slow.
EUROPEPMC_BATCH_TIMEOUT = (5, 60)


def _europepmc_records(results, dois):
    """{doi: Found} from Europe PMC's results, for the DOIs asked about. A DOI can have more
    than one record (a preprint and the article), so one with an abstract is preferred."""
    found = {}
    for result in results:
        doi = normalize_doi(result.get("doi"))
        if doi not in dois:
            continue
        record = Found(clean_text(result.get("abstractText")), clean_text(result.get("title")))
        if doi not in found or (record.abstract and not found[doi].abstract):
            found[doi] = record
    return found


def _europepmc(doi):
    response = get(
        "Europe PMC",
        EUROPEPMC_URL,
        params={"query": f'DOI:"{_query_safe(doi)}"', "resultType": "core", "format": "json", "pageSize": 1},
        timeout=LOOKUP_TIMEOUT,
    )
    raise_if_unavailable("Europe PMC", response)
    if response.status_code != 200:
        return None
    results = (json_of(response, "Europe PMC").get("resultList") or {}).get("result") or []
    # A DOI query can still return a near match, so require the same DOI.
    return _europepmc_records(results[:1], {doi}).get(doi)


def _europepmc_batch(dois):
    """One Europe PMC search for every DOI (DOI:"a" OR DOI:"b" ...). A DOI with no record
    is a real "not found", but only when the reply holds every hit."""
    query = " OR ".join(f'DOI:"{_query_safe(doi)}"' for doi in dois)
    response = get(
        "Europe PMC",
        EUROPEPMC_URL,
        params={"query": query, "resultType": "core", "format": "json", "pageSize": 1000},
        timeout=EUROPEPMC_BATCH_TIMEOUT,
    )
    raise_if_unavailable("Europe PMC", response)
    if response.status_code != 200:
        return None  # refused as a whole (a 400 for one odd DOI): ask one at a time
    body = json_of(response, "Europe PMC")
    results = (body.get("resultList") or {}).get("result") or []
    found = _europepmc_records(results, set(dois))
    hits = body.get("hitCount")
    if not isinstance(hits, int) or hits > len(results):
        # Some hits were not sent, so a DOI not seen may still be there: only the DOIs
        # that were seen have been answered.
        return found
    return {doi: found.get(doi) for doi in dois}


SEMANTIC_SCHOLAR_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper"


def _semanticscholar(doi):
    # A lapsed key falls back to a keyless request: a lookup still works that way.
    response = semanticscholar_get(
        f"{SEMANTIC_SCHOLAR_PAPER_URL}/DOI:{quote_doi(doi)}",
        {"fields": "abstract,title"},
        keyless_fallback=True,
        timeout=LOOKUP_TIMEOUT,
    )
    raise_if_unavailable("Semantic Scholar", response)
    if response.status_code != 200:
        return None
    data = json_of(response, "Semantic Scholar")
    return Found(clean_text(data.get("abstract")), clean_text(data.get("title")))


def _semanticscholar_batch(dois):
    """One Semantic Scholar batch request for every DOI. The reply is a list in the order
    asked, with null for a paper it does not know."""
    response = semanticscholar_get(
        f"{SEMANTIC_SCHOLAR_PAPER_URL}/batch",
        {"fields": "abstract,title"},
        keyless_fallback=True,
        body={"ids": [f"DOI:{doi}" for doi in dois]},
        timeout=LOOKUP_TIMEOUT,
    )
    raise_if_unavailable("Semantic Scholar", response)
    if response.status_code != 200:
        # Refused as a whole: one malformed DOI makes it answer 400 for every one.
        return None
    data = json_of(response, "Semantic Scholar")
    if not isinstance(data, list) or len(data) != len(dois):
        log.warning("Semantic Scholar's batch reply did not match the request; asking one at a time.")
        return None
    return {
        doi: Found(clean_text(item.get("abstract")), clean_text(item.get("title"))) if isinstance(item, dict) else None
        for doi, item in zip(dois, data)
    }


# Tried in this order: publisher APIs are the only way to get their abstracts, then
# Semantic Scholar (a lapsed key still works keyless, at its lower rate limit), and
# Europe PMC last: it is open and unrestricted, but it can be slow to answer, and a paper
# found by an earlier source is never sent to it.
SOURCES = [
    Source("elsevier", "Elsevier (Scopus)", _elsevier, required_credential="elsevier", prefixes=("10.1016/",)),
    Source(
        "springer",
        "Springer Nature",
        _springer,
        required_credential="springernature",
        prefixes=("10.1007/", "10.1038/", "10.1186/"),
    ),
    Source("semanticscholar", "Semantic Scholar", _semanticscholar, batch=_semanticscholar_batch, batch_size=500),
    Source("europepmc", "Europe PMC", _europepmc, batch=_europepmc_batch, batch_size=25),
]
SOURCE_IDS = {source.id for source in SOURCES}

# Papers asked about at once, one request each, for a source with no batch request (the
# publishers). Kept small so Elsevier's per-second limit is not hit.
MAX_PARALLEL = 10


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


def _ask_one(source, doi):
    # A passing problem (a dropped connection, a rate limit, a server error) is asked again a
    # few times: one hiccup must not switch the source off for every paper that is left in the
    # run. A source that is too slow to answer is not: it is skipped for the rest of the run
    # (the next source takes over, and a later lookup tries it again).
    return retry_unavailable(lambda: source.lookup(doi), retry_timeouts=False)


def _ask_each(source, dois, replies, errors):
    """Ask `source` about each DOI alone, side by side, adding to `replies` ({doi: Found or
    None} for the DOIs it answered) and `errors` ({doi: message} for the ones it failed on).
    A lookup that crashes is logged and leaves only its own DOI unanswered."""

    def ask(doi):
        # Papers still waiting for a turn are not sent once the source has failed for another.
        if _give_up_if_failed([doi], errors):
            return
        try:
            replies[doi] = _ask_one(source, doi)
        except SourceError as exc:
            errors[doi] = str(exc)
        except Exception:  # noqa: BLE001 - one paper's odd reply must not lose the others' answers
            log.error("Abstract lookup at %s failed for %s:\n%s", source.label, doi, redact(traceback.format_exc()))

    if len(dois) == 1:
        ask(dois[0])
    else:
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(dois))) as pool:
            list(pool.map(ask, dois))


# A DOI that a batch request might choke on (Semantic Scholar refuses a whole batch for one id
# it cannot read) is asked about on its own instead, so it never costs the others their batch.
_PLAIN_DOI = re.compile(r"^10\.[0-9.]+/[^\s\"<>#?\\%]+$")


def _give_up_if_failed(dois, errors):
    """True (with the source's error given to `dois`) once the source has failed in this
    chunk: nothing more is sent to it, so a timeout is not paid twice."""
    if not errors:
        return False
    # Copied in one step: other lookups of this source may be adding to `errors` from their
    # own threads, and a dict that grows while it is being iterated raises RuntimeError.
    message = list(errors.values())[0]
    errors.update({doi: message for doi in dois})
    return True


def _send_batch(source, dois, replies, errors):
    """One batch request for `dois`. Returns False if the source refused it as a whole, True
    once every DOI has been dealt with (answered, failed, or asked one at a time)."""
    try:
        answered = retry_unavailable(lambda: source.batch(dois), retry_timeouts=False)
    except SourceError as exc:
        errors.update({doi: str(exc) for doi in dois})
        return True
    except Exception:  # noqa: BLE001 - an odd reply must not lose the whole chunk
        # Asked one at a time instead: the single requests are read by other code, and a
        # paper whose reply is the trouble then costs only its own answer.
        log.error("Abstract lookup at %s failed for a batch:\n%s", source.label, redact(traceback.format_exc()))
        _ask_each(source, dois, replies, errors)
        return True
    if answered is None:
        return False
    replies.update(answered)
    return True


def _narrow_down(source, dois, replies, errors):
    """`dois` were refused as a whole. Split them in half and ask each half: if one half is
    refused again, the DOI it could not take is in there, so narrow that half down the same
    way. If both halves are refused, the trouble is not one odd DOI (the source is refusing
    batches, or there are several), so every DOI left is asked on its own; splitting further
    would cost more requests than that."""
    middle = len(dois) // 2
    refused = []
    for half in (dois[:middle], dois[middle:]):
        if _give_up_if_failed(half, errors):
            continue
        if len(half) == 1:
            _ask_each(source, half, replies, errors)
        elif not _send_batch(source, half, replies, errors):
            refused.append(half)
    if len(refused) == 1:
        _narrow_down(source, refused[0], replies, errors)
        return
    for half in refused:
        if not _give_up_if_failed(half, errors):
            _ask_each(source, half, replies, errors)


def _ask_batch(source, dois, replies, errors):
    """Ask `source` about `dois` in one request. A request it refuses as a whole is narrowed
    down to the one DOI it could not take (_narrow_down), so one odd DOI costs a few extra
    requests instead of one per paper."""
    if _give_up_if_failed(dois, errors):
        return
    if len(dois) == 1:
        _ask_each(source, dois, replies, errors)
    elif not _send_batch(source, dois, replies, errors):
        _narrow_down(source, dois, replies, errors)


def _ask(source, dois):
    """({doi: Found or None} for the DOIs `source` answered, {doi: error message} for the ones
    it could not be asked about). Several DOIs go in one request where the source has one."""
    replies, errors = {}, {}
    if source.batch is None:
        _ask_each(source, dois, replies, errors)
        return replies, errors
    plain = [doi for doi in dois if _PLAIN_DOI.match(doi)]
    odd = [doi for doi in dois if not _PLAIN_DOI.match(doi)]
    for start in range(0, len(plain), source.batch_size):
        _ask_batch(source, plain[start : start + source.batch_size], replies, errors)
    if odd:
        if errors:
            _ask_batch(source, odd, replies, errors)  # gives them the same error, unasked
        else:
            _ask_each(source, odd, replies, errors)
    return replies, errors


class _Paper:
    def __init__(self, doi, title, answered_before):
        self.doi = normalize_doi(doi)
        self.title = title
        self.answered_before = frozenset(answered_before)
        self.answered = set()
        self.errors = {}
        self.found = None  # (abstract, source id)
        self.applicable = [source for source in SOURCES if _applies(source, self.doi)] if self.doi else []

    def wants(self, source):
        return (
            self.found is None
            and source in self.applicable
            and source.id not in self.answered_before
        )

    def result(self):
        if not self.doi:
            return Lookup(None, None, {}, frozenset(), False)
        if self.found:
            return Lookup(self.found[0], self.found[1], self.errors, frozenset(self.answered), True)
        complete = all(s.id in self.answered or s.id in self.answered_before for s in self.applicable)
        return Lookup(None, None, self.errors, frozenset(self.answered), complete)


def lookup_batch(papers, skip_sources=frozenset(), answers=None):
    """Look up every (key, doi, title) in `papers` and return {key: Lookup}. Each source is
    asked, in SOURCES order, about the papers still without an abstract that it applies to,
    except those it already answered "no abstract" for (`answers`: {key: source ids}) and
    except sources to be skipped (they failed earlier in the run). A source that fails is
    not asked about anything more in this call.

    If a paper's title is given, an abstract whose paper title clearly differs from it is
    skipped: the DOI led to a different paper in that source, so its abstract would be the
    wrong one."""
    answers = answers or {}
    state = {key: _Paper(doi, title, answers.get(key, ())) for key, doi, title in papers}
    failed = set(skip_sources)
    for source in SOURCES:
        if source.id in failed:
            continue
        by_doi = {}
        for paper in state.values():
            if paper.wants(source):
                by_doi.setdefault(paper.doi, []).append(paper)
        if not by_doi:
            continue
        started = time.monotonic()
        try:
            replies, errors = _ask(source, list(by_doi))
        except Exception:  # noqa: BLE001 - one source's bug must not lose the others' results
            log.error("Abstract lookup at %s failed:\n%s", source.label, redact(traceback.format_exc()))
            continue  # nobody was answered, so every paper is left to be tried again
        log.info(
            "Abstract lookup: %s asked about %d papers in %.1f s",
            source.label,
            len(by_doi),
            time.monotonic() - started,
        )
        if errors:
            failed.add(source.id)
        for doi, waiting in by_doi.items():
            for paper in waiting:
                if doi in errors:
                    paper.errors[source.id] = errors[doi]
                    continue
                if doi not in replies:
                    continue  # not answered (part of a reply that was cut short)
                paper.answered.add(source.id)
                found = replies[doi]
                if not found or len(found.abstract) < MIN_ABSTRACT_CHARS:
                    continue
                if paper.title and not titles_match(paper.title, found.title):
                    log.info(
                        "Skipped %s abstract for %s: its title %r doesn't match %r",
                        source.id,
                        doi,
                        found.title,
                        paper.title,
                    )
                    continue
                paper.found = (found.abstract, source.id)
    return {key: paper.result() for key, paper in state.items()}


def lookup_abstract(doi, skip_sources=frozenset(), title=None, answered_before=frozenset()):
    """lookup_batch for one paper: try each applicable source for one DOI, except the ones
    that already answered "no abstract" for this paper (answered_before) or that are to be
    skipped (they failed earlier in the run). Returns a Lookup."""
    return lookup_batch([(0, doi, title)], skip_sources, {0: answered_before})[0]


def find_abstract(doi, skip_sources=frozenset(), title=None):
    """lookup_abstract as (abstract, source_id, errors, answered), answered being how many
    sources replied without an error (0 means the lookup did not really happen)."""
    found = lookup_abstract(doi, skip_sources, title)
    return found.abstract, found.source, found.errors, len(found.answered)
