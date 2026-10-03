import datetime
import errno
import hmac
import json
import mimetypes
import os
import re
import socket
import sqlite3
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from threading import Timer
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.serving import ThreadedWSGIServer
from werkzeug.utils import safe_join

import abstracts
import access
import credentials
import db
import llm
import openalex
import search_sources
import single_instance
from source_http import SourceError, redact, safe_url

SUPPORTED_PROVIDERS = set(llm.PROVIDERS)

# Broader than SUPPORTED_PROVIDERS (which only gates *AI* provider/model
# choice for datasets/analysis runs) - this set is which providers the
# generic api-key endpoints below will store/return a key for. OpenAlex
# isn't an AI provider, but as of its Feb 2026 usage-based pricing change,
# an (free) OpenAlex API key gets its own private per-day credit budget
# instead of sharing the anonymous pool's much smaller one with every other
# anonymous caller on the same IP - the same encrypted credential storage
# credentials.py already has for Anthropic works unchanged for this. The same
# goes for the keys used to look up missing abstracts (abstracts.py): Elsevier
# and Springer Nature need one for their publishers' DOIs, Semantic Scholar's
# is optional and only raises its rate limit.
CREDENTIAL_PROVIDERS = SUPPORTED_PROVIDERS | {"openalex", "elsevier", "springernature", "semanticscholar"}
# The providers abstracts.py can use for lookups, so saving one of their keys
# makes an earlier "no abstract found" worth retrying.
LOOKUP_KEY_PROVIDERS = {"elsevier", "springernature", "semanticscholar"}

# Papers looked up per request. Semantic Scholar's unauthenticated limit is
# about one call a second, so this keeps a request to roughly ten seconds.
FIND_ABSTRACTS_CHUNK_SIZE = 8

# Sized to control cost/latency per LLM call without hitting output-token
# limits (each candidate needs a full rationale in the response) - see
# PLAN.md's Core pipeline step 5 and the resumable-chunk design in Data
# model (Phase 3).
SCORE_CHUNK_SIZE = 20

MAX_DATASET_NAME_CHARS = 120

STATIC_DIR = Path(__file__).parent / "static"
# LIT_REVIEW_PORT is for tests only, so launching real copies never touches the
# port a real app is using. The Vite dev proxy (vite.config.js) assumes 5175.
PORT = int(os.environ.get("LIT_REVIEW_PORT") or 5175)

# Python's mimetypes (and the Windows registry it reads) may not know .webp or
# the web font types, in which case send_from_directory serves them as
# application/octet-stream and stricter browsers refuse the favicon.
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")

# static_folder=None disables Flask's own auto-registered static route, so the
# catch-all below is the only route serving files/index.html - no silent collision.
app = Flask(__name__, static_folder=None)

# No request here is large (the biggest body is a paper's abstract), so anything
# bigger is refused (413) without being read.
MAX_REQUEST_BYTES = 1_000_000
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES


class InvalidRequest(ValueError):
    """A request body that cannot be used. The message is safe to show the user and
    is sent back as a 400, so a route only has to raise it."""


@app.errorhandler(InvalidRequest)
def _invalid_request(exc):
    return jsonify({"error": str(exc)}), 400


@app.errorhandler(Exception)
def _unexpected_error(exc):
    if isinstance(exc, HTTPException):
        # 404, 405, 413...: keep their status, but answer API calls in JSON like
        # every other API error (the page expects {"error": ...}).
        if request.path.startswith("/api/"):
            return jsonify({"error": exc.description or exc.name}), exc.code
        return exc
    # Anything else is a bug, not the caller's mistake. The details go to the log
    # (with API keys removed) and the caller gets a plain message.
    app.logger.error(
        "Unhandled error on %s %s:\n%s", request.method, request.path, redact(traceback.format_exc())
    )
    return jsonify({"error": "Something went wrong on the server. Please try again."}), 500

# The only Host values this app answers to. It listens on 127.0.0.1 only, but a
# website can still reach it from the user's own browser: a plain cross-site POST
# needs no permission, and a hostile domain re-pointed (DNS rebinding) at
# 127.0.0.1 gets same-origin access. Anything not addressed to us by one of
# these names is refused. The Vite dev server is covered by vite.config.js,
# which rewrites Host and Origin on the way through its proxy.
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


@app.before_request
def reject_foreign_requests():
    if request.host.lower() not in ALLOWED_HOSTS:
        return jsonify({"error": "Forbidden host."}), 403
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        # Browsers send Origin on every cross-site POST/PATCH/DELETE. Absent is
        # fine (curl, tests, same-origin tools); the literal "null" (sandboxed
        # frames, file:// pages) parses to no host and is refused with the rest.
        origin = request.headers.get("Origin")
        if origin is not None:
            parsed = urlparse(origin)
            if parsed.scheme != "http" or parsed.netloc.lower() not in ALLOWED_HOSTS:
                return jsonify({"error": "Forbidden origin."}), 403
    return None


@app.after_request
def add_security_headers(response):
    # Not framed by another site (clickjacking on the Delete buttons).
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# One piece of slow, billable or quota-spending work per run (or dataset) at a
# time. Stopping a request in the browser does not stop the server's call to the
# AI model, so without this a quick Stop then Resume, or a second tab, would
# score the same papers twice and pay twice.
_BUSY_LOCKS = {}
_BUSY_GUARD = threading.Lock()


@contextmanager
def _exclusive(kind, item_id):
    """Yields True holding the lock for (kind, item_id), or False at once, without
    waiting, if something else holds it."""
    with _BUSY_GUARD:
        lock = _BUSY_LOCKS.setdefault((kind, item_id), threading.Lock())
    if not lock.acquire(blocking=False):
        yield False
        return
    try:
        yield True
    finally:
        lock.release()


# Who may use this copy. The port is shared by every account on the computer, so
# the API requires a secret that only its own user can read (see access.py). The
# browser page keeps it and sends it as an Authorization header on every API call.
# It is not a cookie, because browsers send a cookie to every server on the same
# host name whatever its port, so any other local web server could collect it.
# The page itself (the HTML and scripts) holds nothing private and is open.
#
# Names this running copy in /api/health, so a second launch by the same user can
# tell its own copy from another user's on the same port.
INSTANCE_ID = uuid.uuid4().hex
# Set by main() once the secret is loaded. While it is unset every API call except
# the health check is refused, so a copy that was not started through main() fails
# closed instead of serving everyone.
app.config["ACCESS_TOKEN"] = None
OPEN_PATHS = {"/api/health"}

NOT_CONNECTED_MESSAGE = (
    "This browser is not connected to Lit Review. Open Lit Review again from its icon "
    "(it opens a connected browser window) to reconnect."
)


def _same_secret(supplied, token):
    # Bytes, so whatever text a client sends compares without raising, and constant
    # time, so the secret cannot be guessed a character at a time.
    return hmac.compare_digest(supplied.encode("utf-8", "replace"), token.encode("utf-8"))


def _bearer_token():
    """The secret from "Authorization: Bearer <secret>", or "" if there is none. Only
    that header counts: not a cookie (which a browser sends by itself on any request
    another site makes), and not the address."""
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def _refuse_access(status):
    message = NOT_CONNECTED_MESSAGE if status == 401 else "Lit Review is not ready yet."
    return jsonify({"error": message}), status


@app.before_request
def require_session():
    if not request.path.startswith("/api/") or request.path in OPEN_PATHS:
        return None
    token = app.config.get("ACCESS_TOKEN")
    if not token:
        return _refuse_access(503)
    if not _same_secret(_bearer_token(), token):
        return _refuse_access(401)
    return None


@app.get("/api/health")
def health():
    """Lets a second launch tell that this port is already Lit Review, and which
    copy (`instance`) it is. Open to everyone, so it carries nothing private."""
    return jsonify({"app": "lit-review", "instance": INSTANCE_ID})


@app.get("/api/settings/api-key")
def get_api_key_status():
    status = {provider: credentials.has_key(provider) for provider in CREDENTIAL_PROVIDERS}
    # True when saved keys exist but can't be read (see credentials.py), so the
    # Settings page can say so instead of showing every key as missing.
    status["store_error"] = credentials.store_error()
    return jsonify(status)


def _provider_name(body):
    provider = body.get("provider")
    if not isinstance(provider, str) or provider not in CREDENTIAL_PROVIDERS:
        raise InvalidRequest(f"Unsupported provider '{str(provider)[:40]}'.")
    return provider


@app.post("/api/settings/api-key")
def set_api_key():
    body = _json_body()
    provider = _provider_name(body)
    api_key = _str(body, "api_key", MAX_API_KEY_CHARS)
    if not api_key:
        return jsonify({"error": "missing 'api_key'"}), 400
    credentials.set_key(provider, api_key)
    if provider in LOOKUP_KEY_PROVIDERS:
        # A new source for abstract lookup: let papers it could now help with
        # be tried again.
        db.clear_abstract_checked()
    return jsonify({"ok": True})


@app.delete("/api/settings/api-key")
def delete_api_key():
    provider = _provider_name(_json_body())
    credentials.delete_key(provider)
    return jsonify({"ok": True})


MAX_QUESTION_CHARS = 4000
MAX_TOKEN_COUNT = 10_000_000
MAX_API_KEY_CHARS = 512
MAX_SKIP_IDS = 10_000
MAX_SQLITE_INT = 2**63 - 1


def _json_body():
    """The request's JSON body, which must be an object ({} if there is none)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise InvalidRequest("The request body must be a JSON object.")
    return body


def _str(body, key, max_chars=None):
    """body[key] stripped, '' if missing or null. Raises InvalidRequest for a value
    that is not text or is longer than max_chars."""
    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvalidRequest(f"'{key}' must be text")
    value = value.strip()
    if max_chars is not None and len(value) > max_chars:
        raise InvalidRequest(f"'{key}' must be at most {max_chars} characters")
    return value


def _int_id(value, name):
    """A database id: a whole number (not true/false, not text), within what the
    database stores."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_SQLITE_INT:
        raise InvalidRequest(f"'{name}' must be a whole number id")
    return value


def _token_count(value, name):
    """A token count: 0 if missing, else a whole number from 0 to MAX_TOKEN_COUNT."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_TOKEN_COUNT:
        raise InvalidRequest(f"'{name}' must be a whole number from 0 to {MAX_TOKEN_COUNT}")
    return value


def _clean_queries(raw):
    """The search queries from a request: a list of text, stripped, with blank and
    repeated ones (ignoring case) dropped. At least one must remain, and no more
    than llm.MAX_QUERIES of at most llm.MAX_QUERY_CHARS characters each, since every
    one is run against every selected source."""
    if not isinstance(raw, list) or not all(isinstance(q, str) for q in raw):
        raise InvalidRequest("'queries' must be a list of text")
    if any(len(" ".join(q.split())) > llm.MAX_QUERY_CHARS for q in raw):
        raise InvalidRequest(f"Each search query must be at most {llm.MAX_QUERY_CHARS} characters")
    queries = llm.clean_queries(raw)
    if not queries:
        raise InvalidRequest("missing or empty 'queries'")
    if len(queries) > llm.MAX_QUERIES:
        raise InvalidRequest(f"At most {llm.MAX_QUERIES} search queries are allowed")
    return queries


def _optional_year(body, field):
    value = body.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"'{field}' must be an integer")
    return value


def _optional_date(body, date_field, year_field, end_of_year):
    """A "YYYY-MM-DD" bound from body[date_field], else from a bare year in
    body[year_field] (Jan 1, or Dec 31 for an end bound), else None."""
    value = body.get(date_field)
    if value is not None:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"'{date_field}' must be a date like 2026-03-05")
        try:
            datetime.date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"'{date_field}' is not a real date") from exc
        return value
    year = _optional_year(body, year_field)
    if year is None:
        return None
    if not 1 <= year <= 9999:
        raise ValueError(f"'{year_field}' must be a four-digit year")
    return f"{year:04d}-12-31" if end_of_year else f"{year:04d}-01-01"


def _optional_range(body):
    """(from_date, to_date) publication date bounds from a request body, each a
    "YYYY-MM-DD" string or None. Raises ValueError (message safe to show)."""
    from_date = _optional_date(body, "from_date", "from_year", False)
    to_date = _optional_date(body, "to_date", "to_year", True)
    if from_date and to_date and from_date > to_date:
        raise ValueError("The 'from' date is after the 'to' date.")
    return from_date, to_date


def _validate_ai_api(ai_api):
    if not isinstance(ai_api, str) or ai_api not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported ai_api '{ai_api}'.")


def _validate_ai_model(ai_api, ai_model):
    """Models are only unique within a provider, so the pair is validated."""
    _validate_ai_api(ai_api)
    if not isinstance(ai_model, str) or ai_model not in llm.MODELS[ai_api]:
        raise ValueError(f"Unsupported ai_model '{ai_model}' for '{ai_api}'.")


def _ai_choice(body):
    """(ai_api, ai_model) from a request body, validated. A missing ai_api
    means the default provider and a missing ai_model that provider's default
    model. Raises ValueError for an unsupported provider or model."""
    ai_api = body.get("ai_api") or llm.DEFAULT_PROVIDER
    _validate_ai_api(ai_api)
    ai_model = body.get("ai_model") or llm.default_model(ai_api)
    _validate_ai_model(ai_api, ai_model)
    return ai_api, ai_model


def _openalex_error_response(exc):
    """OpenAlex answered, but with an error status - not a connectivity
    problem, so "try again" would be misleading (especially for a 4xx that
    a retry can't fix). For a 429, OpenAlex sends a Retry-After header
    telling us exactly how long the (usually short, burst-limit) cooldown
    is - surface that instead of a vague "wait a moment"."""
    status = exc.response.status_code if exc.response is not None else None
    app.logger.warning("OpenAlex returned HTTP %s: %s", status, redact(exc))
    if status == 429:
        retry_after = exc.response.headers.get("Retry-After") if exc.response is not None else None
        if retry_after:
            message = f"OpenAlex rate limit reached. Please wait {retry_after} seconds and try again."
        else:
            message = "OpenAlex rate limit reached. Please wait a moment and try again."
        return jsonify({"error": message}), 429
    return jsonify({"error": f"OpenAlex rejected the request (HTTP {status})."}), 502


def _mark_new(papers, last_refresh):
    """The papers, each with `is_new`: whether it joined the dataset in its latest check
    for new papers (they are stamped with that check's time)."""
    at = (last_refresh or {}).get("at")
    return [{**paper, "is_new": bool(at) and paper.get("added_at") == at} for paper in papers]


def _dataset_to_dict(dataset_row, papers):
    # Deliberately no run/score info here - a dataset is pure retrieval
    # (PLAN.md's Paper/Dataset model), never joined to any analysis_run for
    # display. Scores only ever appear on the Evaluate Papers / Results
    # side (RunResultsPage), never on Paper Datasets.
    # Excluded papers are in `papers` (so the detail page can show them grayed
    # out) but don't count toward the year spread, matching list_datasets.
    active = [p for p in papers if not p.get("excluded")]
    years = [p["year"] for p in active if p.get("year")]
    dates = [p["publication_date"] for p in active if p.get("publication_date")]
    return {
        "id": dataset_row["id"],
        "name": dataset_row["name"],
        "verbose_query": dataset_row["verbose_query"],
        "from_year": dataset_row["from_year"],
        "to_year": dataset_row["to_year"],
        "from_date": dataset_row["from_date"],
        "to_date": dataset_row["to_date"],
        "expanded_queries": dataset_row["expanded_queries"],
        "sources": dataset_row["sources"],
        # How complete each search was (None for a dataset from before it was
        # recorded): see create_dataset.
        "retrieval": dataset_row.get("retrieval"),
        "created_at": dataset_row["created_at"],
        "papers": _mark_new(papers, dataset_row.get("last_refresh")),
        # The latest check for new papers (None if never checked): when, the dates
        # searched, how many papers were new, and how complete the searches were.
        "last_refresh": dataset_row.get("last_refresh"),
        # The actual publication-year spread of what got retrieved (not to
        # be confused with from_year/to_year, the search filter constraints)
        # - lets the user eyeball whether a dataset looks stale and worth
        # re-running (e.g. newest_year is several years behind today).
        "oldest_year": min(years) if years else None,
        "newest_year": max(years) if years else None,
        # ISO date string (YYYY-MM-DD) of the most recent paper, when known -
        # lets the frontend show the newest paper's month, not just its year.
        "newest_publication_date": max(dates) if dates else None,
        "cost": round(db.get_cost(dataset_id=dataset_row["id"]), 6),
        # Which AI model expanded the query and what that call cost (None for
        # a dataset with no logged expansion call).
        "expansion": _expansion_to_dict(db.get_dataset_expansion(dataset_row["id"])),
    }


def _expansion_to_dict(expansion):
    if expansion is None:
        return None
    return {**expansion, "cost": round(expansion["cost"], 6)}


@app.post("/api/datasets/expand")
def expand_dataset_query():
    """Step 1 of dataset creation: the LLM part only (query expansion), plus
    the reuse check (which needs no LLM/OpenAlex call at all). Split out
    from the OpenAlex retrieval step (POST /api/datasets below) so that if
    OpenAlex's rate limit trips, the frontend can retry *just* the
    retrieval step with these same queries/usage - without paying for
    another expansion call just to retry a paper-database fetch."""
    body = _json_body()
    question = _str(body, "question", MAX_QUESTION_CHARS)
    if not question:
        return jsonify({"error": "missing 'question'"}), 400

    try:
        from_date, to_date = _optional_range(body)
        ai_api, ai_model = _ai_choice(body)
        sources = search_sources.validate_sources(body.get("sources"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Reuse an existing dataset for the exact same question + filters + paper
    # sources instead of re-running expansion/retrieval - this is what makes
    # repeat testing free. force_new opts out (e.g. periodically re-checking a
    # field later). Reuse deliberately ignores ai_model - it's about whether
    # the same paper pool was already retrieved, not which model happened to
    # expand it.
    if not body.get("force_new"):
        existing_id = db.find_dataset(question, from_date=from_date, to_date=to_date, sources=sources)
        if existing_id is not None:
            dataset_row = db.get_dataset(existing_id)
            papers = db.get_dataset_papers(existing_id)
            return jsonify({"reused": True, "dataset": _dataset_to_dict(dataset_row, papers)})

    try:
        queries, expand_usage, title = llm.expand_query(question, ai_api, ai_model)
    except llm.LLMError as exc:
        if exc.usage is not None:
            # The model answered (and was billed) but the answer was unusable. No
            # dataset follows, so the cost is logged on its own rather than lost.
            db.record_llm_call("query_expansion", ai_api, exc.usage.model, exc.usage)
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "reused": False,
            "queries": queries,
            "title": title,
            "usage": {
                "input_tokens": expand_usage.input_tokens,
                "output_tokens": expand_usage.output_tokens,
                "ai_api": expand_usage.provider,
                "model": expand_usage.model,
            },
        }
    )


@app.post("/api/datasets")
def create_dataset():
    """Step 2: given already-expanded queries (from POST /api/datasets/expand)
    and their usage, run OpenAlex retrieval and persist the dataset. Nothing
    is written to the DB until retrieval fully succeeds, so a failed call
    (e.g. OpenAlex's rate limit) leaves no partial state - retrying this
    same request with the same body is always safe, and never re-runs the
    LLM expansion that already happened in step 1."""
    body = _json_body()
    question = _str(body, "question", MAX_QUESTION_CHARS)
    usage = body.get("usage")
    if usage is None:
        usage = {}
    if not isinstance(usage, dict):
        raise InvalidRequest("'usage' must be an object")
    # Short title from the expansion step; carried through here so a retried
    # retrieval keeps it without another LLM call. Optional (a placeholder is
    # made from the topic if missing).
    title = _str(body, "title")[:MAX_DATASET_NAME_CHARS]
    if not question:
        return jsonify({"error": "missing 'question'"}), 400
    queries = _clean_queries(body.get("queries"))

    try:
        from_date, to_date = _optional_range(body)
        usage_api, usage_model = _ai_choice({"ai_api": usage.get("ai_api"), "ai_model": usage.get("model")})
        sources = search_sources.validate_sources(body.get("sources"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    input_tokens = _token_count(usage.get("input_tokens"), "input_tokens")
    output_tokens = _token_count(usage.get("output_tokens"), "output_tokens")
    expand_usage = llm.Usage(input_tokens, output_tokens, model=usage_model, provider=usage_api)

    # A long search spends the sources' quotas, so the same search is not run twice at
    # once (a second tab, a double click); the second asker is told, and finds the
    # dataset reused once the first has finished.
    search_key = (question.lower(), from_date, to_date, tuple(sources), tuple(q.lower() for q in queries))
    with _exclusive("search", search_key) as acquired:
        if not acquired:
            return jsonify({"error": "This search is already running. Wait for it to finish."}), 409
        return _retrieve_dataset(question, queries, from_date, to_date, title, sources, expand_usage)


# Searches that finished while a retrieval was still failing, kept for a few minutes so
# its retry button only re-runs what did not finish (a broad search can be minutes of
# requests). Dropped when the retrieval succeeds, so a later search of the same
# question asks the sources again, and after SEARCH_CACHE_SECONDS, so it is never stale.
# Keyed by (source id, query, from date, to date); the value is (when, SearchResult).
_SEARCH_CACHE = {}
_SEARCH_CACHE_LOCK = threading.Lock()
SEARCH_CACHE_SECONDS = 600
# Bounded by the papers held, not by how many searches: a full search is thousands of
# papers with abstracts, so this keeps the most it can hold to some tens of MB.
SEARCH_CACHE_MAX_PAPERS = 20_000


def _cached_search(key):
    """The finished search stored under `key`, or None."""
    now = time.monotonic()
    with _SEARCH_CACHE_LOCK:
        for stale in [k for k, (when, _) in _SEARCH_CACHE.items() if now - when >= SEARCH_CACHE_SECONDS]:
            del _SEARCH_CACHE[stale]
        entry = _SEARCH_CACHE.get(key)
    return entry[1] if entry else None


def _remember_search(key, found):
    """Keep a finished search, dropping the oldest ones if that holds too many papers."""
    with _SEARCH_CACHE_LOCK:
        _SEARCH_CACHE[key] = (time.monotonic(), found)
        # The newest is never dropped for its own size (a search is at most
        # MAX_RESULTS_PER_SEARCH papers), so a retry always keeps the last finished one.
        while len(_SEARCH_CACHE) > 1 and sum(len(f) for _, f in _SEARCH_CACHE.values()) > SEARCH_CACHE_MAX_PAPERS:
            del _SEARCH_CACHE[min(_SEARCH_CACHE, key=lambda k: _SEARCH_CACHE[k][0])]


def _forget_searches(keys):
    with _SEARCH_CACHE_LOCK:
        for key in keys:
            _SEARCH_CACHE.pop(key, None)


def _run_searches(queries, sources, from_date, to_date):
    """Run every query against every selected source. Returns (candidates, retrieval,
    used): the papers (deduplicated), how complete each search was (one entry per source
    and query, kept with the dataset so it can be seen later: `total` is what the source
    says matches, `fetched` what it returned, `capped` why any were left out), and the
    cache keys used (see _forget_searches). All of them have to succeed: a source that
    fails (rate limit, rejected key) fails the whole retrieval, with nothing saved, so
    the retry button is always safe and a dataset never silently lacks a source the user
    asked for. The searches that did finish are kept briefly (see _SEARCH_CACHE), so a
    retry does not repeat them. Raises requests.RequestException or SourceError."""
    result_lists = []
    retrieval = []
    used = []
    for source_id in sources:
        for q in queries:
            key = (source_id, q, from_date, to_date)
            found = _cached_search(key)
            if found is None:
                found = search_sources.SEARCH_SOURCES_BY_ID[source_id].search(q, from_date, to_date)
                _remember_search(key, found)
            used.append(key)
            result_lists.append(found)
            retrieval.append(
                {
                    "source": source_id,
                    "query": q,
                    "total": getattr(found, "total", None),
                    "fetched": getattr(found, "fetched", len(found)),
                    "kept": len(found),
                    "capped": getattr(found, "capped", None),
                }
            )
    return openalex.dedupe(result_lists), retrieval, used


def _search_failure(exc):
    """The response for a search that failed (an exception from _run_searches)."""
    if isinstance(exc, requests.HTTPError):
        return _openalex_error_response(exc)
    if isinstance(exc, requests.RequestException):
        app.logger.warning("OpenAlex request failed: %s", redact(exc))
        return jsonify({"error": "Failed to reach OpenAlex. Please try again."}), 502
    return jsonify({"error": str(exc)}), 502


def _retrieve_dataset(question, queries, from_date, to_date, title, sources, expand_usage):
    """Run every query against every selected source and save the dataset (the
    caller holds the search's lock)."""
    try:
        candidates, retrieval, used = _run_searches(queries, sources, from_date, to_date)
    except (requests.RequestException, SourceError) as exc:
        return _search_failure(exc)

    # One transaction: a failure here leaves no half-made dataset, and the finished
    # searches stay kept (see _SEARCH_CACHE) so the retry does not repeat them.
    dataset_id = db.save_retrieved_dataset(
        question,
        queries,
        candidates,
        expand_usage,
        from_date=from_date,
        to_date=to_date,
        name=title,
        sources=sources,
        retrieval=retrieval,
    )
    _forget_searches(used)

    dataset_row = db.get_dataset(dataset_id)
    papers = db.get_dataset_papers(dataset_id)
    return jsonify(_dataset_to_dict(dataset_row, papers))


# A refresh searches from this long before the last check, not from it: sources index
# papers late and PubMed dates some by their print issue, so a paper that appeared just
# before the last check can show up only now. Papers already held are absorbed.
REFRESH_OVERLAP_DAYS = 45


def _refresh_window(dataset_row, today):
    """(from_date, to_date) to search for papers that have appeared since the dataset was
    last searched. Raises InvalidRequest if the search ended in the past, since nothing
    newer can fall inside it.

    Searching the whole original range again would return the same most-relevant
    papers, and on a broad topic the new ones would rarely make the cut, so the window
    is narrowed to the time since the last search (less the overlap above)."""
    to_date = dataset_row["to_date"]
    if to_date and to_date < today.isoformat():
        raise InvalidRequest(
            f"This search ends on {to_date}, so no newer papers can appear. "
            "Start a new search with a later end date."
        )
    last = dataset_row.get("last_refresh") or {}
    searched_on = datetime.date.fromisoformat((last.get("at") or dataset_row["created_at"])[:10])
    since = (searched_on - datetime.timedelta(days=REFRESH_OVERLAP_DAYS)).isoformat()
    return max(dataset_row["from_date"] or "", since), to_date


@app.post("/api/datasets/<int:dataset_id>/refresh")
def refresh_dataset(dataset_id):
    """Check the dataset's sources again for papers that have appeared since it was
    last searched, and add only the new ones (nothing is spent on the AI: the saved
    queries are reused). Papers already in the dataset, with their excluded and read
    states, are untouched."""
    dataset_row = db.get_dataset(dataset_id)
    if dataset_row is None:
        return jsonify({"error": "dataset not found"}), 404
    try:
        sources = search_sources.validate_sources(dataset_row["sources"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    queries = llm.clean_queries([q for q in dataset_row["expanded_queries"] if isinstance(q, str)])
    from_date, to_date = _refresh_window(dataset_row, datetime.date.today())

    with _exclusive("search", ("refresh", dataset_id)) as acquired:
        if not acquired:
            return jsonify({"error": "This dataset is already being checked. Wait for it to finish."}), 409
        try:
            candidates, retrieval, used = _run_searches(queries, sources, from_date, to_date)
        except (requests.RequestException, SourceError) as exc:
            return _search_failure(exc)
        new_ids = db.save_refresh(
            dataset_id, candidates, {"from_date": from_date, "to_date": to_date, "retrieval": retrieval}
        )
        _forget_searches(used)
        dataset = _dataset_to_dict(db.get_dataset(dataset_id), db.get_dataset_papers(dataset_id, include_excluded=True))
        return jsonify({"new_count": len(new_ids), "dataset": dataset})


@app.get("/api/datasets")
def list_datasets():
    return jsonify({"datasets": db.list_datasets()})


@app.get("/api/datasets/<int:dataset_id>")
def get_dataset(dataset_id):
    dataset_row = db.get_dataset(dataset_id)
    if not dataset_row:
        return jsonify({"error": "dataset not found"}), 404
    papers = db.get_dataset_papers(dataset_id, include_excluded=True)
    return jsonify(_dataset_to_dict(dataset_row, papers))


@app.patch("/api/datasets/<int:dataset_id>")
def update_dataset(dataset_id):
    """Rename a dataset (its short title). The topic it was retrieved with is
    not editable."""
    if db.get_dataset(dataset_id) is None:
        return jsonify({"error": "dataset not found"}), 404
    name = _str(_json_body(), "name", MAX_DATASET_NAME_CHARS)
    if not name:
        return jsonify({"error": "'name' cannot be blank"}), 400
    db.rename_dataset(dataset_id, name)
    return jsonify(
        _dataset_to_dict(db.get_dataset(dataset_id), db.get_dataset_papers(dataset_id, include_excluded=True))
    )


@app.delete("/api/datasets/<int:dataset_id>")
def delete_dataset(dataset_id):
    """Soft delete of the grouping only; papers and runs that used it are
    left alone."""
    if db.get_dataset(dataset_id) is None:
        return jsonify({"error": "dataset not found"}), 404
    db.delete_dataset(dataset_id)
    return jsonify({"ok": True})


@app.patch("/api/analysis-runs/<int:run_id>")
def update_analysis_run(run_id):
    """Rename a run. Names are unique among live runs (case-insensitive)."""
    if db.get_analysis_run(run_id) is None:
        return jsonify({"error": "analysis run not found"}), 404
    name = " ".join(_str(_json_body(), "name").split())
    if not name:
        return jsonify({"error": "'name' cannot be blank"}), 400
    if len(name) > db.MAX_RUN_NAME_CHARS:
        return jsonify({"error": f"'name' must be at most {db.MAX_RUN_NAME_CHARS} characters"}), 400
    saved = db.rename_analysis_run(run_id, name)
    if saved is None:
        return jsonify({"error": "Another analysis run already has that name"}), 409
    return jsonify({"id": run_id, "name": saved})


@app.delete("/api/analysis-runs/<int:run_id>")
def delete_analysis_run(run_id):
    if db.get_analysis_run(run_id) is None:
        return jsonify({"error": "analysis run not found"}), 404
    db.delete_analysis_run(run_id)
    return jsonify({"ok": True})


@app.post("/api/datasets/<int:dataset_id>/find-abstracts")
def find_dataset_abstracts(dataset_id):
    """Look up missing abstracts (by DOI, from abstracts.py's sources) for one
    chunk of the dataset's papers. The client calls this repeatedly, like an
    analysis run's /process, until `remaining` is 0. It is stateless: the
    client sends back the paper ids already attempted (skip_ids, so a paper
    with no abstract anywhere isn't retried forever) and any sources that
    failed (skip_sources, so a rejected key isn't retried per paper)."""
    if db.get_dataset(dataset_id) is None:
        return jsonify({"error": "dataset not found"}), 404

    body = _json_body()
    skip_ids = body.get("skip_ids") or []
    skip_sources = body.get("skip_sources") or []
    if (
        not isinstance(skip_ids, list)
        or len(skip_ids) > MAX_SKIP_IDS
        or not all(isinstance(i, int) and not isinstance(i, bool) for i in skip_ids)
    ):
        return jsonify({"error": f"'skip_ids' must be a list of at most {MAX_SKIP_IDS} integers"}), 400
    if (
        not isinstance(skip_sources, list)
        or len(skip_sources) > len(abstracts.SOURCE_IDS)
        or not all(isinstance(s, str) for s in skip_sources)
        or not set(skip_sources) <= abstracts.SOURCE_IDS
    ):
        return jsonify({"error": "'skip_sources' must be a list of known source ids"}), 400

    with _exclusive("lookup", dataset_id) as acquired:
        if not acquired:
            return jsonify({"error": "A lookup is already running for this dataset."}), 409
        return _find_abstracts_chunk(dataset_id, set(skip_ids), set(skip_sources))


def _find_abstracts_chunk(dataset_id, attempted_before, skipped):
    # Papers a lookup already completed for without finding an abstract are
    # left out, so opening a dataset or clicking the button again doesn't ask
    # the same sources the same question. Saving a new API key clears those
    # marks (see set_api_key), since a new source can be asked.
    missing = db.get_dataset_papers_missing_abstract(dataset_id)
    no_doi = sum(1 for _, doi, _, _ in missing if not abstracts.normalize_doi(doi))
    candidates = [
        (paper_id, doi, title)
        for paper_id, doi, checked, title in missing
        if paper_id not in attempted_before and abstracts.normalize_doi(doi) and not checked
    ]
    batch = candidates[:FIND_ABSTRACTS_CHUNK_SIZE]

    source_errors = {}
    filled = []
    checked_ids = []
    for paper_id, doi, title in batch:
        abstract, source, errors, answered = abstracts.find_abstract(doi, skipped, title=title)
        source_errors.update(errors)
        skipped.update(errors)
        if abstract and db.set_paper_abstract_if_blank(paper_id, abstract, source):
            filled.append(db.get_paper(paper_id))
        elif answered:
            db.mark_abstract_checked(paper_id)
            checked_ids.append(paper_id)

    return jsonify(
        {
            "attempted": [paper_id for paper_id, _, _ in batch],
            "filled": filled,
            "checked": checked_ids,
            "remaining": len(candidates) - len(batch),
            "no_doi": no_doi,
            "source_errors": source_errors,
        }
    )


@app.patch("/api/datasets/<int:dataset_id>/papers/<int:paper_id>")
def update_dataset_paper(dataset_id, paper_id):
    """Exclude (or restore) a paper within this dataset. Excluded papers stay
    in the dataset but are skipped when it's used in an analysis run."""
    if db.get_dataset(dataset_id) is None:
        return jsonify({"error": "dataset not found"}), 404
    excluded = _json_body().get("excluded")
    if not isinstance(excluded, bool):
        return jsonify({"error": "'excluded' must be true or false"}), 400
    if not db.set_dataset_paper_excluded(dataset_id, paper_id, excluded):
        return jsonify({"error": "paper not in dataset"}), 404
    return jsonify({"id": paper_id, "excluded": excluded})


MAX_PAPER_TITLE_CHARS = 1000
MAX_PAPER_ABSTRACT_CHARS = 20_000
MAX_PAPER_VENUE_CHARS = 300
MAX_PAPER_URL_CHARS = 2000
MIN_PAPER_YEAR, MAX_PAPER_YEAR = 1000, 2100


@app.patch("/api/papers/<int:paper_id>")
def update_paper(paper_id):
    """Manual correction/fill-in for paper data OpenAlex didn't have -
    mainly a missing abstract, but any editable field goes through here.
    A paper is a single shared row across every dataset it appears in
    (PLAN.md's Paper model), so this edit is visible everywhere that paper
    shows up, not just the dataset the user happened to be looking at."""
    if db.get_paper(paper_id) is None:
        return jsonify({"error": "paper not found"}), 404

    body = _json_body()
    fields = {}
    if "title" in body:
        title = _str(body, "title", MAX_PAPER_TITLE_CHARS)
        if not title:
            return jsonify({"error": "'title' cannot be blank"}), 400
        fields["title"] = title
    if "abstract" in body:
        fields["abstract"] = _str(body, "abstract", MAX_PAPER_ABSTRACT_CHARS)
    # The DOI is deliberately not editable: it's how the same paper is
    # recognized across searches (db.get_or_create_paper), so changing it
    # would split off a duplicate that lacks the user's edits.
    if "venue" in body:
        fields["venue"] = _str(body, "venue", MAX_PAPER_VENUE_CHARS) or None
    if "url" in body:
        raw_url = body.get("url")
        if isinstance(raw_url, str) and len(raw_url) > MAX_PAPER_URL_CHARS:
            return jsonify({"error": f"'url' must be at most {MAX_PAPER_URL_CHARS} characters"}), 400
        url = safe_url(raw_url)
        # Blank clears the link; anything else must be a web address, since it
        # is opened in the browser (javascript: and data: links are refused).
        if url is None and isinstance(raw_url, str) and raw_url.strip():
            return jsonify({"error": "'url' must start with http:// or https://"}), 400
        if url is None and raw_url is not None and not isinstance(raw_url, str):
            return jsonify({"error": "'url' must be text"}), 400
        fields["url"] = url
    if "year" in body:
        year = body.get("year")
        if year is not None and (
            isinstance(year, bool) or not isinstance(year, int) or not MIN_PAPER_YEAR <= year <= MAX_PAPER_YEAR
        ):
            return jsonify({"error": f"'year' must be a year from {MIN_PAPER_YEAR} to {MAX_PAPER_YEAR}"}), 400
        fields["year"] = year

    # Not a data correction: whether the user has read the paper, shared like
    # the edits above across every dataset and run it appears in.
    read = body.get("read") if "read" in body else None
    if "read" in body and not isinstance(read, bool):
        return jsonify({"error": "'read' must be true or false"}), 400

    if not fields and read is None:
        return jsonify({"error": "no editable fields provided"}), 400

    if fields:
        db.update_paper(paper_id, fields)
    if read is not None:
        db.set_paper_read(paper_id, read)
    return jsonify(db.get_paper(paper_id))


@app.post("/api/analysis-runs")
def create_analysis_run():
    body = _json_body()
    dataset_ids = body.get("dataset_ids")
    grading_prompt = _str(body, "grading_prompt", MAX_PROMPT_DESCRIPTION_CHARS)
    prompt_id = body.get("prompt_id")

    if not isinstance(dataset_ids, list) or not dataset_ids:
        return jsonify({"error": "missing or empty 'dataset_ids'"}), 400
    if prompt_id is not None:
        # An existing saved prompt: its own description is used, so any
        # grading_prompt text in the body is ignored.
        prompt_id = _int_id(prompt_id, "prompt_id")
        if db.get_prompt(prompt_id) is None:
            return jsonify({"error": "prompt not found"}), 400
    elif not grading_prompt:
        return jsonify({"error": "missing 'prompt_id' or 'grading_prompt'"}), 400
    # De-duplicated, order preserved - a repeated id would otherwise hit
    # analysis_run_dataset's (run_id, dataset_id) PK constraint on the
    # second insert and crash with a raw 500 instead of a clean error.
    dataset_ids = list(dict.fromkeys(_int_id(d, "dataset_ids") for d in dataset_ids))
    try:
        ai_api, ai_model = _ai_choice(body)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    for dataset_id in dataset_ids:
        if db.get_dataset(dataset_id) is None:
            return jsonify({"error": f"dataset {dataset_id} not found"}), 400

    run_id = db.create_analysis_run(dataset_ids, grading_prompt, ai_api, ai_model, prompt_id)
    return jsonify(_run_to_dict(db.get_analysis_run(run_id)))


@app.get("/api/analysis-runs")
def list_analysis_runs():
    return jsonify({"runs": db.list_all_runs()})


def _run_to_dict(run_row):
    run = dict(run_row)
    # The scoring snapshot is internal (full abstracts); the client only
    # needs to know which prompt the run belongs to.
    run.pop("examples_snapshot", None)
    run.pop("name_auto", None)
    prompt = db.get_prompt(run["prompt_id"], include_deleted=True) if run.get("prompt_id") else None
    run["prompt"] = (
        {"id": prompt["id"], "name": prompt["name"], "deleted": prompt["deleted_at"] is not None}
        if prompt
        else None
    )
    run["datasets"] = db.get_run_datasets(run["id"])
    run["results"] = db.get_run_results(run["id"])
    run["candidate_papers"] = db.get_run_candidate_papers(run["id"])
    run["remaining"] = db.count_unscored_papers(run["id"])
    run["cost"] = round(db.get_run_cost(run["id"]), 6)
    return run


@app.get("/api/analysis-runs/<int:run_id>")
def get_analysis_run(run_id):
    run_row = db.get_analysis_run(run_id)
    if not run_row:
        return jsonify({"error": "analysis run not found"}), 404
    return jsonify(_run_to_dict(run_row))


@app.post("/api/analysis-runs/<int:run_id>/process")
def process_analysis_run(run_id):
    with _exclusive("run", run_id) as acquired:
        if not acquired:
            return jsonify({"error": "This run is already being scored. Wait for it to finish."}), 409
        return _process_run_chunk(run_id)


def _process_run_chunk(run_id):
    """Score one chunk of the run's unscored papers (the caller holds the run's
    lock, so the unscored set can't be taken by a second request meanwhile)."""
    run_row = db.get_analysis_run(run_id)
    if not run_row:
        return jsonify({"error": "analysis run not found"}), 404

    chunk = db.get_unscored_papers(run_id, SCORE_CHUNK_SIZE)
    if not chunk:
        # Nothing left to score. A run still marked "running" is finished: its
        # last unscored papers may all have been excluded since it started.
        if run_row["status"] != "completed":
            db.mark_run_completed(run_id)
            run_row = db.get_analysis_run(run_id)
        return jsonify({**_run_to_dict(run_row), "processed": 0})

    if run_row["status"] == "completed":
        # Papers have come back since the run finished (an excluded one was
        # restored, or a dataset gained papers): the run is in progress again
        # until they are scored. Its prompt, examples and earlier scores stand.
        db.reopen_run(run_id)
        run_row = db.get_analysis_run(run_id)

    # Only a prompt created by this run (from Evaluate) is still waiting for an
    # AI title; existing prompts never ask for one.
    prompt = db.get_prompt(run_row["prompt_id"], include_deleted=True) if run_row["prompt_id"] else None
    want_title = bool(prompt and prompt["title_pending"])

    try:
        scores, usage, title = llm.score_batch(
            run_row["grading_prompt"],
            [{**paper, "id": str(paper["id"])} for paper in chunk],
            run_row["ai_api"],
            run_row["ai_model"],
            examples=run_row["examples_snapshot"],
            want_title=want_title,
        )
    except llm.LLMError as exc:
        # Leave the run "running" with nothing written for this chunk, so the
        # next /process call retries the same unscored remainder instead of
        # skipping or duplicating anything.
        return jsonify({"error": str(exc)}), 400

    scores_by_paper_id = {int(paper_id): scored for paper_id, scored in scores.items()}
    db.record_analysis_chunk(run_id, scores_by_paper_id, usage)
    if want_title:
        db.set_generated_prompt_title(prompt["id"], title)

    if not db.count_unscored_papers(run_id):
        db.mark_run_completed(run_id)
    run_row = db.get_analysis_run(run_id)
    return jsonify({**_run_to_dict(run_row), "processed": len(scores_by_paper_id)})


MAX_PROMPT_NAME_CHARS = 120
MAX_PROMPT_DESCRIPTION_CHARS = 4000


def _prompt_fields(body):
    """(name, description, error) from a create/edit body."""
    name = _str(body, "name", MAX_PROMPT_NAME_CHARS)
    description = _str(body, "description", MAX_PROMPT_DESCRIPTION_CHARS)
    if not name:
        return None, None, "'name' cannot be blank"
    if not description:
        return None, None, "'description' cannot be blank"
    return name, description, None


@app.get("/api/prompts")
def list_prompts():
    return jsonify({"prompts": db.list_prompts()})


@app.post("/api/prompts")
def create_prompt():
    name, description, error = _prompt_fields(_json_body())
    if error:
        return jsonify({"error": error}), 400
    prompt_id = db.create_prompt(name, description)
    return jsonify(_prompt_to_dict(db.get_prompt(prompt_id)))


def _prompt_to_dict(prompt):
    prompt["examples"] = db.list_prompt_examples(prompt["id"])
    prompt["example_limit"] = db.EXAMPLE_LIMIT
    return prompt


@app.get("/api/prompts/<int:prompt_id>")
def get_prompt(prompt_id):
    prompt = db.get_prompt(prompt_id)
    if not prompt:
        return jsonify({"error": "prompt not found"}), 404
    return jsonify(_prompt_to_dict(prompt))


@app.patch("/api/prompts/<int:prompt_id>")
def update_prompt(prompt_id):
    if db.get_prompt(prompt_id) is None:
        return jsonify({"error": "prompt not found"}), 404
    name, description, error = _prompt_fields(_json_body())
    if error:
        return jsonify({"error": error}), 400
    db.update_prompt(prompt_id, name, description)
    return jsonify(_prompt_to_dict(db.get_prompt(prompt_id)))


@app.delete("/api/prompts/<int:prompt_id>")
def delete_prompt(prompt_id):
    if db.get_prompt(prompt_id) is None:
        return jsonify({"error": "prompt not found"}), 404
    db.delete_prompt(prompt_id)
    return jsonify({"ok": True})


@app.delete("/api/prompts/<int:prompt_id>/examples/<int:example_id>")
def remove_prompt_example(prompt_id, example_id):
    if db.get_prompt(prompt_id) is None:
        return jsonify({"error": "prompt not found"}), 404
    if not db.remove_prompt_example(prompt_id, example_id):
        return jsonify({"error": "example not found"}), 404
    return jsonify({"ok": True})


@app.patch("/api/analysis-runs/<int:run_id>/results/<int:paper_id>")
def update_run_result(run_id, paper_id):
    """Set the user's relevance call on one scored paper in this run."""
    if not db.get_analysis_run(run_id):
        return jsonify({"error": "analysis run not found"}), 404
    relevance = _json_body().get("relevance")
    if not isinstance(relevance, str) or relevance not in db.RELEVANCE_VALUES:
        return jsonify({"error": "'relevance' must be relevant, neutral or not_relevant"}), 400
    if not db.set_result_relevance(run_id, paper_id, relevance):
        return jsonify({"error": "that paper has no result in this run"}), 404
    return jsonify({"id": paper_id, "relevance": relevance})


@app.post("/api/analysis-runs/<int:run_id>/examples")
def mark_run_example(run_id):
    """Save one scored paper from this run as a good example for the run's
    prompt. Stores a copy of the score and reasoning as they are now."""
    run_row = db.get_analysis_run(run_id)
    if not run_row:
        return jsonify({"error": "analysis run not found"}), 404
    prompt = db.get_prompt(run_row["prompt_id"]) if run_row["prompt_id"] else None
    if not prompt:
        return jsonify({"error": "this run's prompt no longer exists"}), 400

    paper_id = _int_id(_json_body().get("paper_id"), "paper_id")

    result = db.get_run_result(run_id, paper_id)
    if not result or result["score"] is None or not result["rationale"]:
        return jsonify({"error": "that paper has no score in this run"}), 400

    db.add_prompt_example(prompt["id"], paper_id, run_id, result["score"], result["rationale"])
    return jsonify({"ok": True, "prompt_id": prompt["id"]})


@app.get("/")
@app.get("/<path:path>")
def serve_frontend(path="index.html"):
    # Serve the requested static asset if it exists; otherwise fall back to
    # index.html so any future client-side route (e.g. a "past runs" page)
    # still loads the app instead of 404ing on direct navigation/refresh.
    # safe_join resolves ".."/absolute-path traversal to None *before* we ever
    # touch the filesystem, so a crafted path can't be used to probe for the
    # existence of arbitrary files outside STATIC_DIR.
    # An unknown API path is an error, not a client-side route: without this a
    # mistyped or removed endpoint would answer 200 with the app's HTML page.
    if path == "api" or path.startswith("api/"):
        return jsonify({"error": "not found"}), 404
    safe_path = safe_join(str(STATIC_DIR), path)
    if safe_path and Path(safe_path).is_file():
        return send_from_directory(STATIC_DIR, path)
    return send_from_directory(STATIC_DIR, "index.html")


def _open_browser(port=None, token=None):
    """Open the browser on the app: through the private link when there is a secret
    (the page reads it from the address and keeps it), else on the plain address."""
    url = access.launch_url(port or PORT, token)
    if os.environ.get("LIT_REVIEW_NO_BROWSER"):  # tests: say so instead of opening one
        print(f"Would open {url}")
        return
    webbrowser.open(url)


# The whole probe of a busy port, not each read: a per-read timeout starts again
# with every byte, so a program that streams or drips data would hold it forever.
HEALTH_PROBE_SECONDS = 3
# Long enough for a listener to accept a loopback connection (milliseconds, with
# a wide margin), short enough that a free port costs a launch almost nothing.
PORT_CONNECT_SECONDS = 0.25
HEALTH_PROBE_MAX_BYTES = 65536


def _health_reply(data):
    """The JSON object in `data` (the raw bytes a server sent back) if it is a 200
    whose body says this is Lit Review, else None. Anything else, including a
    program that does not speak HTTP at all, is not."""
    head, separator, body = data.partition(b"\r\n\r\n")
    if not separator:
        return None
    status = head.split(b"\r\n", 1)[0].split(None, 2)
    if len(status) < 2 or not status[0].startswith(b"HTTP/") or status[1] != b"200":
        return None
    try:
        reply = json.loads(body)
    except ValueError:  # not JSON, or not UTF-8
        return None
    if isinstance(reply, dict) and reply.get("app") == "lit-review":
        return reply
    return None


def _is_our_health_reply(data):
    return _health_reply(data) is not None


def probe_port(port):
    """What is listening on 127.0.0.1:port, as (state, reply): (None, None) if
    nothing, ("other", None) if something that is not Lit Review, or ("ours", reply)
    with the JSON the app answered to GET /api/health.

    Whether anything listens is decided by connecting, with a short timeout:
    a listener accepts a loopback connection in a few milliseconds (even one on
    all interfaces or dual-stack IPv6, which binding the port to test it would
    miss). A port with nothing on it is the normal case on every launch, and on
    Windows a closed loopback port takes 1 to 2 seconds to refuse, so waiting for
    the refusal would slow every start; the short timeout bounds it instead.

    A held port is then probed with a raw socket on purpose, not urllib: the
    probe must talk only to the one address it was given (urllib follows
    redirects wherever a program sends it, and honors proxy settings), must give
    up after HEALTH_PROBE_SECONDS in total, and must read a bounded amount,
    whatever the program on the port does."""
    deadline = time.monotonic() + HEALTH_PROBE_SECONDS
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=PORT_CONNECT_SECONDS)
    except OSError:
        # Nothing accepted in time: a free port (the normal case), or something
        # that holds it without accepting connections (a socket bound and never
        # listened on). Either way there is no running app to hand over to.
        return None, None
    try:
        with sock:
            sock.sendall(
                f"GET /api/health HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode()
            )
            data = b""
            while len(data) < HEALTH_PROBE_MAX_BYTES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return "other", None
                sock.settimeout(remaining)
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
    except OSError:  # refused, reset, or timed out mid-read
        return "other", None
    reply = _health_reply(data)
    if reply is None:
        return "other", None
    return "ours", reply


def check_port(port, instance=None):
    """What is already listening on 127.0.0.1:port: None if nothing, "ours" if it
    answers GET /api/health as Lit Review, else "other". With `instance`, "ours"
    means that particular running copy (its id in the answer), so a copy of the
    app belonging to another user on the same port is "other"."""
    state, reply = probe_port(port)
    if state == "ours" and instance is not None and reply.get("instance") != instance:
        return "other"
    return state


class PortTaken(Exception):
    """The port is already in use (so the next one can be tried)."""


class SingleOwnerServer(ThreadedWSGIServer):
    """Werkzeug's threaded server, refusing a port that is already in use.

    On Windows, SO_REUSEADDR (which Werkzeug sets) lets a second server bind a
    port another one is listening on, with no error at all, so the exclusive
    flag is used there instead: the bind fails. That is reported as PortTaken,
    not as Werkzeug's own "port is in use" message and exit, so that startup can
    carry on with the next port when two copies, each looking for a free port
    at the same moment, pick the same one. Elsewhere SO_REUSEADDR does not allow
    a second listener, and keeping it lets the app restart straight after it
    stops. Threaded matters since dataset creation and analysis-run processing
    can each take several seconds (LLM + OpenAlex calls): without it nothing
    else, not even a static asset, could be served meanwhile."""

    allow_reuse_address = not hasattr(socket, "SO_EXCLUSIVEADDRUSE")

    def server_bind(self):
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)  # Windows only
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        try:
            super().server_bind()
        except OSError as exc:
            # Windows reports a port held by an exclusive socket as "access denied"
            # (WSAEACCES, 10013), and one held by an ordinary socket as 10048: both
            # are the same situation as "address in use".
            if exc.errno == errno.EADDRINUSE or getattr(exc, "winerror", None) in (10013, 10048):
                raise PortTaken(f"port {self.server_address[1]} is in use") from exc
            raise


# How long a second launch waits for the first to start answering, when the
# first holds the lock but has not bound its port yet (importing takes a moment).
RUNNING_COPY_WAIT_SECONDS = 15
# How long a second launch waits for a record before deciding the other copy is an
# older version that never writes one (a new copy writes it within a second or two).
LEGACY_GRACE_SECONDS = 4
# How many ports, from the default up, a copy may try when the default is taken
# (by another user's copy of this app, or by another program).
PORT_FALLBACK_COUNT = 20


def start_server(start=None, count=PORT_FALLBACK_COUNT):
    """A server bound to the first usable port from `start` (the default port), trying
    `count` in a row, or None if they are all taken. A port is skipped if anything
    listens on it (another user's copy of this app is as taken as any other: it
    needs its owner's secret, so it is no use to this user) and also if it cannot
    be bound, which is what happens when another copy, looking for a port at the
    same moment, chose the same one first."""
    if start is None:
        start = PORT
    for port in range(start, start + count):
        if check_port(port) is not None:
            continue
        try:
            return SingleOwnerServer("127.0.0.1", port, app)
        except PortTaken:
            continue
    return None


def hand_over_to_running_copy(state_dir, wait_seconds=RUNNING_COPY_WAIT_SECONDS):
    """This user's other copy holds the lock. Open the browser on it, signed in,
    without starting a second app, once it answers; wait for it if it is still
    starting. Which copy it is, and where, comes from the record it wrote (not
    from the default port: it may be on another). Returns the exit code.

    A copy from before records existed holds the lock too but never writes one, and
    never asks for a secret. If there is still no record after a few seconds and
    the default port answers as Lit Review without an instance id (only such an
    older copy does that), that is the copy: open it as it is."""
    started = time.monotonic()
    deadline = started + wait_seconds
    while True:
        record = access.read_instance(state_dir)
        if record and check_port(record["port"], instance=record["id"]) == "ours":
            token = access.load_or_create_token(state_dir)
            print(f"Lit Review is already running. Opening it at http://127.0.0.1:{record['port']}")
            _open_browser(record["port"], token)
            return 0
        if record is None and time.monotonic() - started >= LEGACY_GRACE_SECONDS:
            state, reply = probe_port(PORT)
            if state == "ours" and "instance" not in reply:
                print(
                    f"An older version of Lit Review is already running. Opening it at http://127.0.0.1:{PORT}\n"
                    "(Close it and start Lit Review again to use the latest version.)"
                )
                _open_browser(PORT)
                return 0
        if time.monotonic() >= deadline:
            print(
                "Another copy of Lit Review is running but is not answering. "
                "Close it and start Lit Review again.",
                file=sys.stderr,
            )
            return 1
        time.sleep(0.25)


def _data_folder_problem(folder, exc):
    reason = getattr(exc, "strerror", None) or str(exc)
    advice = (
        "Then start Lit Review again."
        if isinstance(exc, db.DatabaseTooNew)
        else "Make sure that folder can be written to and the disk is not full, then start Lit Review again."
    )
    print(
        "Lit Review cannot use its data folder:\n"
        f"  {folder}\n"
        f"{reason}\n"
        f"{advice}",
        file=sys.stderr,
    )
    return 1


def main():
    """Start the app, unless this user already has a copy running, in which case
    open the browser on that one and exit. Returns the exit code."""
    state_dir = db.DB_PATH.parent
    try:
        # Held until the process ends (kept in a local that lives as long as main).
        instance_lock = single_instance.acquire(state_dir / "instance.lock")
    except single_instance.AlreadyRunning:
        return hand_over_to_running_copy(state_dir)
    except OSError as exc:
        return _data_folder_problem(state_dir, exc)

    try:
        # Everything that touches the data folder happens here, so a folder that
        # cannot be used is reported plainly at launch instead of as errors later.
        db.ensure_ready()
        token = access.load_or_create_token(state_dir)
    except (OSError, sqlite3.Error) as exc:
        return _data_folder_problem(state_dir, exc)

    # Ports taken by another user's copy (or another program) are skipped, so two
    # people signed in at once each get their own copy. It binds before the
    # browser is asked to open.
    server = start_server()
    if server is None:
        print(
            f"Lit Review could not find a free port from {PORT} to {PORT + PORT_FALLBACK_COUNT - 1}. "
            "Close some programs and start Lit Review again.",
            file=sys.stderr,
        )
        return 1
    port = server.server_port
    app.config["ACCESS_TOKEN"] = token
    ALLOWED_HOSTS.update({f"127.0.0.1:{port}", f"localhost:{port}"})

    try:
        access.write_instance(state_dir, port, INSTANCE_ID)
    except OSError as exc:
        server.server_close()
        return _data_folder_problem(state_dir, exc)
    Timer(1, _open_browser, args=(port, token)).start()
    print(f"Lit Review is running at http://127.0.0.1:{port}  (press Ctrl+C to stop)")
    print(f"If your browser does not open, use this private link (only you can use it):\n  {access.launch_url(port, token)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        access.clear_instance(state_dir, INSTANCE_ID)
        instance_lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
