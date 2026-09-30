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
        # OpenAlex answered, but with an error status - not a connectivity
        # problem, so "try again" would be misleading (especially for a 4xx
        # that a retry can't fix).
        status = exc.response.status_code if exc.response is not None else None
        app.logger.warning("OpenAlex returned HTTP %s: %s", status, exc)
        if status == 429:
            return jsonify(
                {"error": "OpenAlex rate limit reached. Please wait a moment and try again."}
            ), 429
        return jsonify({"error": f"OpenAlex rejected the request (HTTP {status})."}), 502
    except requests.RequestException as exc:
        app.logger.warning("OpenAlex request failed: %s", exc)
        return jsonify({"error": "Failed to reach OpenAlex. Please try again."}), 502

    return jsonify({"results": results})


@app.get("/api/settings/api-key")
def get_api_key_status():
    return jsonify({provider: credentials.has_key(provider) for provider in SUPPORTED_PROVIDERS})


@app.post("/api/settings/api-key")
def set_api_key():
    body = request.get_json(silent=True) or {}
    provider = body.get("provider")
    api_key = body.get("api_key", "").strip()
    if provider not in SUPPORTED_PROVIDERS:
        return jsonify({"error": f"Unsupported provider '{provider}'."}), 400
    if not api_key:
        return jsonify({"error": "missing 'api_key'"}), 400
    credentials.set_key(provider, api_key)
    return jsonify({"ok": True})


@app.delete("/api/settings/api-key")
def delete_api_key():
    body = request.get_json(silent=True) or {}
    provider = body.get("provider")
    if provider not in SUPPORTED_PROVIDERS:
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


def _dataset_to_dict(dataset_row, papers):
    return {
        "id": dataset_row["id"],
        "name": dataset_row["name"],
        "verbose_query": dataset_row["verbose_query"],
        "from_year": dataset_row["from_year"],
        "to_year": dataset_row["to_year"],
        "expanded_queries": dataset_row["expanded_queries"],
        "created_at": dataset_row["created_at"],
        "papers": papers,
        "cost": round(db.get_cost(dataset_id=dataset_row["id"]), 6),
    }


@app.post("/api/datasets")
def create_dataset():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "missing 'question'"}), 400

    try:
        from_year = _optional_year(body, "from_year")
        to_year = _optional_year(body, "to_year")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Reuse an existing dataset for the exact same question + filters instead
    # of re-running expansion/retrieval - this is what makes repeat testing
    # free. force_new opts out (e.g. periodically re-checking a field later).
    if not body.get("force_new"):
        existing_id = db.find_dataset(question, from_year=from_year, to_year=to_year)
        if existing_id is not None:
            dataset_row = db.get_dataset(existing_id)
            papers = db.get_dataset_papers(existing_id)
            return jsonify(_dataset_to_dict(dataset_row, papers))

    try:
        queries, expand_usage = llm.expand_query(question)
        result_lists = [
            openalex.search_works(q, per_page=50, from_year=from_year, to_year=to_year)
            for q in queries
        ]
        candidates = openalex.dedupe(result_lists)
    except llm.LLMError as exc:
        return jsonify({"error": str(exc)}), 400
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        app.logger.warning("OpenAlex returned HTTP %s: %s", status, exc)
        if status == 429:
            return jsonify(
                {"error": "OpenAlex rate limit reached. Please wait a moment and try again."}
            ), 429
        return jsonify({"error": f"OpenAlex rejected the request (HTTP {status})."}), 502
    except requests.RequestException as exc:
        app.logger.warning("OpenAlex request failed: %s", exc)
        return jsonify({"error": "Failed to reach OpenAlex. Please try again."}), 502

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
    result = _dataset_to_dict(dataset_row, papers)
    result["runs"] = db.list_dataset_runs(dataset_id)
    return jsonify(result)


@app.delete("/api/datasets/<int:dataset_id>/papers/<int:paper_id>")
def exclude_dataset_paper(dataset_id, paper_id):
    db.exclude_dataset_paper(dataset_id, paper_id)
    return jsonify({"ok": True})


@app.post("/api/datasets/<int:dataset_id>/analysis-runs")
def create_analysis_run(dataset_id):
    dataset_row = db.get_dataset(dataset_id)
    if not dataset_row:
        return jsonify({"error": "dataset not found"}), 404

    body = request.get_json(silent=True) or {}
    grading_prompt = (body.get("grading_prompt") or dataset_row["verbose_query"]).strip()
    ai_api = body.get("ai_api") or "anthropic"
    ai_model = body.get("ai_model") or llm.MODEL

    run_id = db.create_analysis_run(dataset_id, grading_prompt, ai_api, ai_model)
    return jsonify(db.get_analysis_run(run_id))


def _run_to_dict(run_row):
    run = dict(run_row)
    run["results"] = db.get_run_results(run["id"])
    run["cost"] = round(db.get_run_cost(run["id"], run["dataset_id"]), 6)
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
        return jsonify({**_run_to_dict(run_row), "processed": 0, "remaining": 0})

    chunk = db.get_unscored_papers(run_id, SCORE_CHUNK_SIZE)
    if not chunk:
        db.mark_run_completed(run_id)
        run_row = db.get_analysis_run(run_id)
        return jsonify({**_run_to_dict(run_row), "processed": 0, "remaining": 0})

    try:
        scores, usage = llm.score_batch(
            run_row["grading_prompt"], [{**paper, "id": str(paper["id"])} for paper in chunk]
        )
    except llm.LLMError as exc:
        # Leave the run "running" with nothing written for this chunk, so the
        # next /process call retries the same unscored remainder instead of
        # skipping or duplicating anything.
        return jsonify({"error": str(exc)}), 400

    scores_by_paper_id = {int(paper_id): scored for paper_id, scored in scores.items()}
    db.record_analysis_chunk(run_id, run_row["dataset_id"], scores_by_paper_id, usage)

    remaining = db.count_unscored_papers(run_id)
    if not remaining:
        db.mark_run_completed(run_id)
    run_row = db.get_analysis_run(run_id)
    return jsonify(
        {**_run_to_dict(run_row), "processed": len(scores_by_paper_id), "remaining": remaining}
    )


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
