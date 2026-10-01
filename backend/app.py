import webbrowser
from pathlib import Path
from threading import Timer

import requests
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import safe_join

import abstracts
import credentials
import db
import llm
import openalex
import search_sources
from source_http import SourceError

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
PORT = 5175

# static_folder=None disables Flask's own auto-registered static route, so the
# catch-all below is the only route serving files/index.html - no silent collision.
app = Flask(__name__, static_folder=None)


@app.get("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "missing query param 'q'"}), 400

    from_year = request.args.get("from_year", type=int)
    to_year = request.args.get("to_year", type=int)

    try:
        results = openalex.search_works(query, from_year=from_year, to_year=to_year)
    except requests.HTTPError as exc:
        return _openalex_error_response(exc)
    except requests.RequestException as exc:
        app.logger.warning("OpenAlex request failed: %s", exc)
        return jsonify({"error": "Failed to reach OpenAlex. Please try again."}), 502

    return jsonify({"results": results})


@app.get("/api/settings/api-key")
def get_api_key_status():
    return jsonify({provider: credentials.has_key(provider) for provider in CREDENTIAL_PROVIDERS})


@app.post("/api/settings/api-key")
def set_api_key():
    body = request.get_json(silent=True) or {}
    provider = body.get("provider")
    api_key = body.get("api_key", "").strip()
    if provider not in CREDENTIAL_PROVIDERS:
        return jsonify({"error": f"Unsupported provider '{provider}'."}), 400
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
    body = request.get_json(silent=True) or {}
    provider = body.get("provider")
    if provider not in CREDENTIAL_PROVIDERS:
        return jsonify({"error": f"Unsupported provider '{provider}'."}), 400
    credentials.delete_key(provider)
    return jsonify({"ok": True})


def _optional_year(body, field):
    value = body.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"'{field}' must be an integer")
    return value


def _validate_ai_api(ai_api):
    if ai_api not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported ai_api '{ai_api}'.")


def _validate_ai_model(ai_api, ai_model):
    """Models are only unique within a provider, so the pair is validated."""
    _validate_ai_api(ai_api)
    if ai_model not in llm.MODELS[ai_api]:
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
    app.logger.warning("OpenAlex returned HTTP %s: %s", status, exc)
    if status == 429:
        retry_after = exc.response.headers.get("Retry-After") if exc.response is not None else None
        if retry_after:
            message = f"OpenAlex rate limit reached. Please wait {retry_after} seconds and try again."
        else:
            message = "OpenAlex rate limit reached. Please wait a moment and try again."
        return jsonify({"error": message}), 429
    return jsonify({"error": f"OpenAlex rejected the request (HTTP {status})."}), 502


def _dataset_to_dict(dataset_row, papers):
    # Deliberately no run/score info here - a dataset is pure retrieval
    # (PLAN.md's Paper/Dataset model), never joined to any analysis_run for
    # display. Scores only ever appear on the Analyze Papers / Past Results
    # side (RunResultsPage), never on Paper Data Sets.
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
        "expanded_queries": dataset_row["expanded_queries"],
        "sources": dataset_row["sources"],
        "created_at": dataset_row["created_at"],
        "papers": papers,
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
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "missing 'question'"}), 400

    try:
        from_year = _optional_year(body, "from_year")
        to_year = _optional_year(body, "to_year")
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
        existing_id = db.find_dataset(question, from_year=from_year, to_year=to_year, sources=sources)
        if existing_id is not None:
            dataset_row = db.get_dataset(existing_id)
            papers = db.get_dataset_papers(existing_id)
            return jsonify({"reused": True, "dataset": _dataset_to_dict(dataset_row, papers)})

    try:
        queries, expand_usage, title = llm.expand_query(question, ai_api, ai_model)
    except llm.LLMError as exc:
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
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    queries = body.get("queries")
    usage = body.get("usage") or {}
    # Short title from the expansion step; carried through here so a retried
    # retrieval keeps it without another LLM call. Optional (a placeholder is
    # made from the topic if missing).
    title = str(body.get("title") or "").strip()[:MAX_DATASET_NAME_CHARS]
    if not question:
        return jsonify({"error": "missing 'question'"}), 400
    if not isinstance(queries, list) or not queries:
        return jsonify({"error": "missing or empty 'queries'"}), 400

    try:
        from_year = _optional_year(body, "from_year")
        to_year = _optional_year(body, "to_year")
        usage_api, usage_model = _ai_choice({"ai_api": usage.get("ai_api"), "ai_model": usage.get("model")})
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        sources = search_sources.validate_sources(body.get("sources"))
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc) or "invalid 'usage'"}), 400

    # Every selected source is searched with every query. All of them have to
    # succeed: a source that fails (rate limit, rejected key) fails the whole
    # retrieval, with nothing saved, so the retry button is always safe and a
    # dataset never silently lacks a source the user asked for.
    try:
        result_lists = [
            search_sources.SEARCH_SOURCES_BY_ID[source_id].search(q, from_year, to_year)
            for source_id in sources
            for q in queries
        ]
        candidates = openalex.dedupe(result_lists)
    except requests.HTTPError as exc:
        return _openalex_error_response(exc)
    except requests.RequestException as exc:
        app.logger.warning("OpenAlex request failed: %s", exc)
        return jsonify({"error": "Failed to reach OpenAlex. Please try again."}), 502
    except SourceError as exc:
        return jsonify({"error": str(exc)}), 502

    expand_usage = llm.Usage(input_tokens, output_tokens, model=usage_model, provider=usage_api)
    dataset_id = db.create_dataset(
        question, queries, from_year=from_year, to_year=to_year, name=title, sources=sources
    )
    db.record_llm_call("query_expansion", usage_api, expand_usage.model, expand_usage, dataset_id=dataset_id)
    paper_ids = [db.get_or_create_paper(candidate) for candidate in candidates]
    db.add_papers_to_dataset(dataset_id, paper_ids)

    dataset_row = db.get_dataset(dataset_id)
    papers = db.get_dataset_papers(dataset_id)
    return jsonify(_dataset_to_dict(dataset_row, papers))


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
    name = ((request.get_json(silent=True) or {}).get("name") or "").strip()
    if not name:
        return jsonify({"error": "'name' cannot be blank"}), 400
    if len(name) > MAX_DATASET_NAME_CHARS:
        return jsonify({"error": f"'name' must be at most {MAX_DATASET_NAME_CHARS} characters"}), 400
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

    body = request.get_json(silent=True) or {}
    skip_ids = body.get("skip_ids") or []
    skip_sources = body.get("skip_sources") or []
    if not isinstance(skip_ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in skip_ids):
        return jsonify({"error": "'skip_ids' must be a list of integers"}), 400
    if (
        not isinstance(skip_sources, list)
        or not all(isinstance(s, str) for s in skip_sources)
        or not set(skip_sources) <= abstracts.SOURCE_IDS
    ):
        return jsonify({"error": "'skip_sources' must be a list of known source ids"}), 400

    # Papers a lookup already completed for without finding an abstract are
    # left out, so opening a dataset or clicking the button again doesn't ask
    # the same sources the same question. Saving a new API key clears those
    # marks (see set_api_key), since a new source can be asked.
    attempted_before = set(skip_ids)
    missing = db.get_dataset_papers_missing_abstract(dataset_id)
    no_doi = sum(1 for _, doi, _, _ in missing if not abstracts.normalize_doi(doi))
    candidates = [
        (paper_id, doi, title)
        for paper_id, doi, checked, title in missing
        if paper_id not in attempted_before and abstracts.normalize_doi(doi) and not checked
    ]
    batch = candidates[:FIND_ABSTRACTS_CHUNK_SIZE]

    skipped = set(skip_sources)
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
    excluded = (request.get_json(silent=True) or {}).get("excluded")
    if not isinstance(excluded, bool):
        return jsonify({"error": "'excluded' must be true or false"}), 400
    if not db.set_dataset_paper_excluded(dataset_id, paper_id, excluded):
        return jsonify({"error": "paper not in dataset"}), 404
    return jsonify({"id": paper_id, "excluded": excluded})


@app.patch("/api/papers/<int:paper_id>")
def update_paper(paper_id):
    """Manual correction/fill-in for paper data OpenAlex didn't have -
    mainly a missing abstract, but any editable field goes through here.
    A paper is a single shared row across every dataset it appears in
    (PLAN.md's Paper model), so this edit is visible everywhere that paper
    shows up, not just the dataset the user happened to be looking at."""
    if db.get_paper(paper_id) is None:
        return jsonify({"error": "paper not found"}), 404

    body = request.get_json(silent=True) or {}
    fields = {}
    if "title" in body:
        title = (body.get("title") or "").strip()
        if not title:
            return jsonify({"error": "'title' cannot be blank"}), 400
        fields["title"] = title
    if "abstract" in body:
        fields["abstract"] = (body.get("abstract") or "").strip()
    # The DOI is deliberately not editable: it's how the same paper is
    # recognized across searches (db.get_or_create_paper), so changing it
    # would split off a duplicate that lacks the user's edits.
    if "venue" in body:
        fields["venue"] = (body.get("venue") or "").strip() or None
    if "url" in body:
        fields["url"] = (body.get("url") or "").strip() or None
    if "year" in body:
        year = body.get("year")
        if year is not None:
            try:
                year = int(year)
            except (TypeError, ValueError):
                return jsonify({"error": "'year' must be an integer"}), 400
        fields["year"] = year

    if not fields:
        return jsonify({"error": "no editable fields provided"}), 400

    db.update_paper(paper_id, fields)
    return jsonify(db.get_paper(paper_id))


@app.post("/api/analysis-runs")
def create_analysis_run():
    body = request.get_json(silent=True) or {}
    dataset_ids = body.get("dataset_ids")
    grading_prompt = (body.get("grading_prompt") or "").strip()
    prompt_id = body.get("prompt_id")

    if not isinstance(dataset_ids, list) or not dataset_ids:
        return jsonify({"error": "missing or empty 'dataset_ids'"}), 400
    if prompt_id is not None:
        # An existing saved prompt: its own description is used, so any
        # grading_prompt text in the body is ignored.
        try:
            prompt_id = int(prompt_id)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid 'prompt_id'"}), 400
        if db.get_prompt(prompt_id) is None:
            return jsonify({"error": "prompt not found"}), 400
    elif not grading_prompt:
        return jsonify({"error": "missing 'prompt_id' or 'grading_prompt'"}), 400
    try:
        # De-duplicated, order preserved - a repeated id would otherwise hit
        # analysis_run_dataset's (run_id, dataset_id) PK constraint on the
        # second insert and crash with a raw 500 instead of a clean error.
        dataset_ids = list(dict.fromkeys(int(d) for d in dataset_ids))
        ai_api, ai_model = _ai_choice(body)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc) or "invalid 'dataset_ids'"}), 400

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
    run_row = db.get_analysis_run(run_id)
    if not run_row:
        return jsonify({"error": "analysis run not found"}), 404

    if run_row["status"] == "completed":
        return jsonify({**_run_to_dict(run_row), "processed": 0})

    chunk = db.get_unscored_papers(run_id, SCORE_CHUNK_SIZE)
    if not chunk:
        db.mark_run_completed(run_id)
        run_row = db.get_analysis_run(run_id)
        return jsonify({**_run_to_dict(run_row), "processed": 0})

    # Only a prompt created by this run (from Analyze) is still waiting for an
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
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    if not name:
        return None, None, "'name' cannot be blank"
    if not description:
        return None, None, "'description' cannot be blank"
    if len(name) > MAX_PROMPT_NAME_CHARS:
        return None, None, f"'name' must be at most {MAX_PROMPT_NAME_CHARS} characters"
    if len(description) > MAX_PROMPT_DESCRIPTION_CHARS:
        return None, None, f"'description' must be at most {MAX_PROMPT_DESCRIPTION_CHARS} characters"
    return name, description, None


@app.get("/api/prompts")
def list_prompts():
    return jsonify({"prompts": db.list_prompts()})


@app.post("/api/prompts")
def create_prompt():
    name, description, error = _prompt_fields(request.get_json(silent=True) or {})
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
    name, description, error = _prompt_fields(request.get_json(silent=True) or {})
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

    body = request.get_json(silent=True) or {}
    try:
        paper_id = int(body.get("paper_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "missing or invalid 'paper_id'"}), 400

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
    safe_path = safe_join(str(STATIC_DIR), path)
    if safe_path and Path(safe_path).is_file():
        return send_from_directory(STATIC_DIR, path)
    return send_from_directory(STATIC_DIR, "index.html")


def _open_browser():
    webbrowser.open(f"http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    Timer(1, _open_browser).start()
    # threaded=True matters since dataset creation and analysis-run processing
    # can each take several seconds (LLM + OpenAlex calls) - without it, the
    # dev server can't serve any other request (even static assets) while
    # one is running.
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
