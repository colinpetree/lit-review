"""The page and the server must agree on the API: every path (and method) the frontend calls
is a route the backend has, and every backend route is used by the page or is known to be
backend-only. Catches a route renamed or removed on one side while each side's own tests
still pass (the page would then fail only when someone clicks the button).

The frontend's calls are read from its source: every '/api/...' string in frontend/src
(tests excluded), with `${...}` parts as placeholders. The method comes from the helper the
call uses (postJson, patchJson, putJson, deleteJson; fetchJson/apiFetch are GET unless a
`method:` follows). A path built elsewhere and passed in (the export URLs) is matched on its
path alone.
"""

import re
from pathlib import Path

import app as app_module

SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"

HELPER_METHODS = {"postJson": "POST", "patchJson": "PATCH", "putJson": "PUT", "deleteJson": "DELETE"}
CALL = re.compile(r"(\w+)\(\s*([`'\"])(/api/[^`'\"]*)\2")
LITERAL = re.compile(r"([`'\"])(/api/[^`'\"]*)\1")
METHOD_AFTER = re.compile(r"method:\s*['\"](\w+)['\"]")

# Routes the page never calls, and why. Each must still be a real route (checked below).
BACKEND_ONLY = {
    ("GET", "/api/health"): "a second launch asks it whether a port is already this app",
    ("POST", "/api/window/show"): "a second launch asks the running copy to show its window",
    ("POST", "/api/datasets"): "the older blocking search; the page queues a dataset_search job instead",
    ("POST", "/api/datasets/expand"): "the older blocking AI step; the dataset_search job does it",
    ("POST", "/api/datasets/<int:dataset_id>/refresh"): "the older blocking check; the page queues dataset_refresh",
    ("POST", "/api/datasets/<int:dataset_id>/find-abstracts"): "the older blocking lookup; the page queues find_abstracts",
    ("POST", "/api/analysis-runs/<int:run_id>/process"): "the older blocking grading chunk; the page queues run_score",
}


def shape(path):
    """A comparable form: every placeholder (`${...}` or `<int:x>`) becomes `*`."""
    path = re.sub(r"\$\{[^}]*\}", "*", path)
    path = re.sub(r"<[^>]+>", "*", path)
    return path.split("?")[0].rstrip("/")


def frontend_calls():
    """{(method or None, shape): first place it is called}."""
    calls = {}
    for file in sorted(SRC.rglob("*.js*")):
        if ".test." in file.name:
            continue
        text = file.read_text(encoding="utf-8")
        claimed = set()
        for match in CALL.finditer(text):
            helper, path = match.group(1), match.group(3)
            method = HELPER_METHODS.get(helper)
            if method is None and helper in ("fetchJson", "apiFetch"):
                after = METHOD_AFTER.search(text[match.end() : match.end() + 200])
                method = after.group(1).upper() if after else "GET"
            calls.setdefault((method, shape(path)), f"{file.relative_to(SRC)}")
            claimed.add(match.start(2))
        for match in LITERAL.finditer(text):
            if match.start() not in claimed:
                calls.setdefault((None, shape(match.group(2))), f"{file.relative_to(SRC)}")
    return calls


def backend_routes():
    routes = set()
    for rule in app_module.app.url_map.iter_rules():
        if rule.rule.startswith("/api/"):
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                routes.add((method, rule.rule))
    return routes


def test_the_scan_finds_the_pages_calls():
    calls = frontend_calls()
    assert len(calls) > 30  # the scan itself still works
    assert ("PATCH", "/api/papers/*") in calls and ("GET", "/api/jobs") in calls


def test_every_call_the_page_makes_is_a_backend_route():
    by_shape = {}
    for method, rule in backend_routes():
        by_shape.setdefault(shape(rule), set()).add(method)
    missing = []
    for (method, path), where in sorted(frontend_calls().items(), key=str):
        methods = by_shape.get(path, set())
        if not methods or (method is not None and method not in methods):
            missing.append(f"{method or 'any'} {path} (called in {where}; the backend has {sorted(methods) or 'no such path'})")
    assert not missing, "the page calls API routes the backend does not have:\n" + "\n".join(missing)


def test_every_backend_route_is_used_by_the_page_or_known_to_be_backend_only():
    calls = frontend_calls()
    used = {(m, p) for m, p in calls}
    unused = []
    for method, rule in sorted(backend_routes()):
        if (method, rule) in BACKEND_ONLY:
            continue
        if (method, shape(rule)) not in used and (None, shape(rule)) not in used:
            unused.append(f"{method} {rule}")
    assert not unused, (
        "backend routes the page never calls (a renamed call on the page, or a route to remove, or one "
        "to list in BACKEND_ONLY with the reason):\n" + "\n".join(unused)
    )


def test_the_backend_only_list_names_real_routes():
    stale = sorted(set(BACKEND_ONLY) - backend_routes())
    assert not stale, f"BACKEND_ONLY lists routes the backend no longer has: {stale}"
