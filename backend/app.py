import webbrowser
from pathlib import Path
from threading import Timer

import requests
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import safe_join

import openalex

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
    app.run(host="127.0.0.1", port=PORT, debug=False)
