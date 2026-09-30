import webbrowser
from pathlib import Path
from threading import Timer

import requests
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import safe_join

import credentials
import db
import llm
import openalex

SUPPORTED_PROVIDERS = {"anthropic"}

# Broader than SUPPORTED_PROVIDERS (which only gates *AI* provider/model
# choice for datasets/analysis runs) - this set is which providers the
# generic api-key endpoints below will store/return a key for. OpenAlex
# isn't an AI provider, but as of its Feb 2026 usage-based pricing change,
# an (free) OpenAlex API key gets its own private per-day credit budget
# instead of sharing the anonymous pool's much smaller one with every other
# anonymous caller on the same IP - the same encrypted credential storage
# credentials.py already has for Anthropic works unchanged for this.
CREDENTIAL_PROVIDERS = SUPPORTED_PROVIDERS | {"openalex"}

# Sized to control cost/latency per LLM call without hitting output-token
# limits (each candidate needs a full rationale in the response) - see
# PLAN.md's Core pipeline step 5 and the resumable-chunk design in Data
# model (Phase 3).
SCORE_CHUNK_SIZE = 20

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


def _validate_ai_model(ai_model):
    if ai_model not in llm.PRICING_PER_MTOK:
        raise ValueError(f"Unsupported ai_model '{ai_model}'.")


def _validate_ai_api(ai_api):
    if ai_api not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported ai_api '{ai_api}'.")


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
    years = [p["year"] for p in papers if p.get("year")]
    dates = [p["publication_date"] for p in papers if p.get("publication_date")]
    return {
        "id": dataset_row["id"],
        "name": dataset_row["name"],
        "verbose_query": dataset_row["verbose_query"],
        "from_year": dataset_row["from_year"],
        "to_year": dataset_row["to_year"],
        "expanded_queries": dataset_row["expanded_queries"],
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
    }


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

    ai_model = body.get("ai_model") or llm.MODEL
    try:
        from_year = _optional_year(body, "from_year")
        to_year = _optional_year(body, "to_year")
        _validate_ai_model(ai_model)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Reuse an existing dataset for the exact same question + filters instead
    # of re-running expansion/retrieval - this is what makes repeat testing
    # free. force_new opts out (e.g. periodically re-checking a field later).
    # Reuse deliberately ignores ai_model - it's about whether the same paper
    # pool was already retrieved, not which model happened to expand it.
    if not body.get("force_new"):
        existing_id = db.find_dataset(question, from_year=from_year, to_year=to_year)
        if existing_id is not None:
            dataset_row = db.get_dataset(existing_id)
            papers = db.get_dataset_papers(existing_id)
            return jsonify({"reused": True, "dataset": _dataset_to_dict(dataset_row, papers)})

    try:
        queries, expand_usage = llm.expand_query(question, ai_model)
    except llm.LLMError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "reused": False,
            "queries": queries,
            "usage": {
                "input_tokens": expand_usage.input_tokens,
                "output_tokens": expand_usage.output_tokens,
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
    if not question:
        return jsonify({"error": "missing 'question'"}), 400
    if not isinstance(queries, list) or not queries:
        return jsonify({"error": "missing or empty 'queries'"}), 400

    try:
        from_year = _optional_year(body, "from_year")
        to_year = _optional_year(body, "to_year")
        usage_model = usage.get("model") or llm.MODEL
        _validate_ai_model(usage_model)
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc) or "invalid 'usage'"}), 400

    try:
        result_lists = [
            openalex.search_works(q, per_page=50, from_year=from_year, to_year=to_year)
            for q in queries
        ]
        candidates = openalex.dedupe(result_lists)
    except requests.HTTPError as exc:
        return _openalex_error_response(exc)
    except requests.RequestException as exc:
        app.logger.warning("OpenAlex request failed: %s", exc)
        return jsonify({"error": "Failed to reach OpenAlex. Please try again."}), 502

    expand_usage = llm.Usage(input_tokens, output_tokens, model=usage_model)
    dataset_id = db.create_dataset(question, queries, from_year=from_year, to_year=to_year)
    db.record_llm_call("query_expansion", "anthropic", expand_usage.model, expand_usage, dataset_id=dataset_id)
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
    papers = db.get_dataset_papers(dataset_id)
    return jsonify(_dataset_to_dict(dataset_row, papers))


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


@app.delete("/api/datasets/<int:dataset_id>/papers/<int:paper_id>")
def exclude_dataset_paper(dataset_id, paper_id):
    db.exclude_dataset_paper(dataset_id, paper_id)
    return jsonify({"ok": True})


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
    if "doi" in body:
        fields["doi"] = (body.get("doi") or "").strip() or None
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
    ai_api = body.get("ai_api") or "anthropic"
    ai_model = body.get("ai_model") or llm.MODEL

    if not isinstance(dataset_ids, list) or not dataset_ids:
        return jsonify({"error": "missing or empty 'dataset_ids'"}), 400
    if not grading_prompt:
        return jsonify({"error": "missing 'grading_prompt'"}), 400
    try:
        # De-duplicated, order preserved - a repeated id would otherwise hit
        # analysis_run_dataset's (run_id, dataset_id) PK constraint on the
        # second insert and crash with a raw 500 instead of a clean error.
        dataset_ids = list(dict.fromkeys(int(d) for d in dataset_ids))
        _validate_ai_api(ai_api)
        _validate_ai_model(ai_model)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc) or "invalid 'dataset_ids'"}), 400

    for dataset_id in dataset_ids:
        if db.get_dataset(dataset_id) is None:
            return jsonify({"error": f"dataset {dataset_id} not found"}), 400

    run_id = db.create_analysis_run(dataset_ids, grading_prompt, ai_api, ai_model)
    return jsonify(_run_to_dict(db.get_analysis_run(run_id)))


@app.get("/api/analysis-runs")
def list_analysis_runs():
    return jsonify({"runs": db.list_all_runs()})


def _run_to_dict(run_row):
    run = dict(run_row)
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

    try:
        scores, usage = llm.score_batch(
            run_row["grading_prompt"],
            [{**paper, "id": str(paper["id"])} for paper in chunk],
            run_row["ai_model"],
        )
    except llm.LLMError as exc:
        # Leave the run "running" with nothing written for this chunk, so the
        # next /process call retries the same unscored remainder instead of
        # skipping or duplicating anything.
        return jsonify({"error": str(exc)}), 400

    scores_by_paper_id = {int(paper_id): scored for paper_id, scored in scores.items()}
    db.record_analysis_chunk(run_id, scores_by_paper_id, usage)

    if not db.count_unscored_papers(run_id):
        db.mark_run_completed(run_id)
    run_row = db.get_analysis_run(run_id)
    return jsonify({**_run_to_dict(run_row), "processed": len(scores_by_paper_id)})


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
