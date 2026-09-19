import webbrowser
from pathlib import Path
from threading import Timer

import requests
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import safe_join

import credentials
import llm
import openalex

SUPPORTED_PROVIDERS = {"anthropic"}

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


@app.post("/api/review")
def review():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "missing 'question'"}), 400

    def _optional_year(field):
        value = body.get(field)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"'{field}' must be an integer")
        return value

    try:
        from_year = _optional_year("from_year")
        to_year = _optional_year("to_year")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        queries, expand_usage = llm.expand_query(question)

        result_lists = [
            openalex.search_works(q, per_page=50, from_year=from_year, to_year=to_year)
            for q in queries
        ]
        candidates = openalex.dedupe(result_lists)

        if not candidates:
            return jsonify({"results": [], "queries": queries, "cost": expand_usage.to_dict()})

        # Scoring a large candidate set in one call risks truncating the JSON
        # response at max_tokens (each candidate needs a full rationale) - chunk
        # into batches small enough to fit comfortably, while still avoiding
        # the one-call-per-paper cost PLAN.md calls out to control.
        SCORE_CHUNK_SIZE = 20
        scores = {}
        score_usage = llm.Usage(model=llm.MODEL)
        for i in range(0, len(candidates), SCORE_CHUNK_SIZE):
            chunk_scores, chunk_usage = llm.score_batch(
                question, candidates[i : i + SCORE_CHUNK_SIZE]
            )
            scores.update(chunk_scores)
            score_usage.add(chunk_usage)
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

    for candidate in candidates:
        scored = scores.get(candidate["id"])
        candidate["score"] = scored["score"] if scored else None
        candidate["rationale"] = scored["rationale"] if scored else None
    candidates.sort(key=lambda c: c["score"] if c["score"] is not None else -1, reverse=True)

    expand_usage.add(score_usage)
    return jsonify({"results": candidates, "queries": queries, "cost": expand_usage.to_dict()})


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
    # threaded=True matters now that /api/review can take many sequential
    # seconds (several LLM + OpenAlex calls) - without it, the dev server
    # can't serve any other request (even static assets) while one is running.
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
