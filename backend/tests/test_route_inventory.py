"""Every /api route, checked the same way: the access secret, the Host and Origin guards, and
junk request bodies. The list below must match app.url_map exactly, so a new route fails this
file until it is added here, and is then covered by every check below without writing any.

What a route does is tested elsewhere (test_validation.py has the bad-body table per field);
this file makes sure no route is ever left out of the guards that protect all of them.
"""

import pytest

import app as app_module

# (method, rule) for every /api route. Add a new route here (and keep the list sorted).
KNOWN_ROUTES = sorted([
    ("DELETE", "/api/analysis-runs/<int:run_id>"),
    ("DELETE", "/api/datasets/<int:dataset_id>"),
    ("DELETE", "/api/prompts/<int:prompt_id>"),
    ("DELETE", "/api/prompts/<int:prompt_id>/examples/<int:example_id>"),
    ("DELETE", "/api/settings/api-key"),
    ("GET", "/api/about"),
    ("GET", "/api/analysis-runs"),
    ("GET", "/api/analysis-runs/<int:run_id>"),
    ("GET", "/api/data/backup"),
    ("GET", "/api/datasets"),
    ("GET", "/api/datasets/<int:dataset_id>"),
    ("GET", "/api/health"),
    ("GET", "/api/jobs"),
    ("GET", "/api/notices"),
    ("GET", "/api/prompts"),
    ("GET", "/api/prompts/<int:prompt_id>"),
    ("GET", "/api/settings/api-key"),
    ("GET", "/api/settings/updates"),
    ("GET", "/api/trash"),
    ("GET", "/api/update-check"),
    ("PATCH", "/api/analysis-runs/<int:run_id>"),
    ("PATCH", "/api/analysis-runs/<int:run_id>/results/<int:paper_id>"),
    ("PATCH", "/api/datasets/<int:dataset_id>"),
    ("PATCH", "/api/datasets/<int:dataset_id>/papers/<int:paper_id>"),
    ("PATCH", "/api/papers/<int:paper_id>"),
    ("PATCH", "/api/prompts/<int:prompt_id>"),
    ("POST", "/api/analysis-runs"),
    ("POST", "/api/analysis-runs/<int:run_id>/examples"),
    ("POST", "/api/analysis-runs/<int:run_id>/export"),
    ("POST", "/api/analysis-runs/<int:run_id>/process"),
    ("POST", "/api/analysis-runs/estimate"),
    ("POST", "/api/data/restore"),
    ("POST", "/api/datasets"),
    ("POST", "/api/datasets/<int:dataset_id>/export"),
    ("POST", "/api/datasets/<int:dataset_id>/find-abstracts"),
    ("POST", "/api/datasets/<int:dataset_id>/refresh"),
    ("POST", "/api/datasets/expand"),
    ("POST", "/api/jobs"),
    ("POST", "/api/jobs/<int:job_id>/resume"),
    ("POST", "/api/jobs/<int:job_id>/stop"),
    ("POST", "/api/prompts"),
    ("POST", "/api/settings/api-key"),
    ("PUT", "/api/settings/updates"),
    ("POST", "/api/trash/<kind>/<int:item_id>/restore"),
    ("POST", "/api/update/apply"),
    ("POST", "/api/update/check"),
    ("POST", "/api/update/installed-seen"),
    ("POST", "/api/window/show"),
])

# Open to everyone: a second launch asks it whether a port is already Lit Review.
OPEN_ROUTES = {("GET", "/api/health")}
MUTATING = {"POST", "PATCH", "DELETE", "PUT"}
SAMPLE_VALUES = {"kind": "dataset"}


@pytest.fixture(autouse=True)
def no_update_check(monkeypatch):
    """POST /api/update/check starts a background check of GitHub; these tests only care that
    the route is guarded, so the check itself is a no-op (conftest would refuse the network)."""
    monkeypatch.setattr(app_module.updater, "check_now", lambda *a, **k: True)


def api_routes():
    found = set()
    for rule in app_module.app.url_map.iter_rules():
        if rule.rule.startswith("/api/"):
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                found.add((method, rule.rule))
    return sorted(found)


def concrete(rule):
    """The rule with sample values in its placeholders, as a real request would have."""
    for converter in app_module.app.url_map.iter_rules():
        if converter.rule == rule:
            path = rule
            for name in converter.arguments:
                value = SAMPLE_VALUES.get(name, "1")
                path = path.replace(f"<int:{name}>", value).replace(f"<path:{name}>", value).replace(f"<{name}>", value)
            return path
    raise AssertionError(rule)


ROUTES = api_routes()


def test_the_list_matches_the_app():
    added = sorted(set(ROUTES) - set(KNOWN_ROUTES))
    removed = sorted(set(KNOWN_ROUTES) - set(ROUTES))
    assert not added, f"new /api routes: add them to KNOWN_ROUTES so the guards below check them: {added}"
    assert not removed, f"routes no longer in the app: remove them from KNOWN_ROUTES: {removed}"


@pytest.fixture
def stranger(client):
    """The app's own address, but no secret."""
    browser = app_module.app.test_client()
    browser.environ_base.pop("HTTP_AUTHORIZATION", None)
    return browser


@pytest.mark.parametrize("method,rule", [r for r in ROUTES if r not in OPEN_ROUTES])
def test_every_route_needs_the_secret(stranger, method, rule):
    response = stranger.open(concrete(rule), method=method, json={} if method in MUTATING else None)
    assert response.status_code == 401, f"{method} {rule} answered {response.status_code} without the secret"
    assert response.is_json


@pytest.mark.parametrize("method,rule", ROUTES)
def test_every_route_refuses_another_host(client, method, rule):
    # DNS rebinding: a page on another name that resolves to 127.0.0.1.
    response = client.open(concrete(rule), method=method, base_url="http://attacker.example:8100", json={} if method in MUTATING else None)
    assert response.status_code == 403, f"{method} {rule} answered {response.status_code} for a foreign Host"


@pytest.mark.parametrize("method,rule", [r for r in ROUTES if r[0] in MUTATING])
@pytest.mark.parametrize("origin", ["https://attacker.example", "http://localhost:8100.attacker.example", "null"])
def test_every_change_refuses_another_site(client, method, rule, origin):
    # A plain cross-site form POST needs no preflight; the Origin header is what gives it away.
    response = client.open(concrete(rule), method=method, headers={"Origin": origin}, json={})
    assert response.status_code == 403, f"{method} {rule} answered {response.status_code} for Origin {origin}"


JUNK_BODIES = [
    [1, 2, 3],
    True,
    "a string",
    10**30,
    {
        "name": [], "dataset_id": "x", "dataset_ids": "x", "run_id": {}, "prompt_id": -1, "paper_id": 10**30,
        "paper_ids": "x", "kind": 5, "format": {}, "read": "maybe", "relevance": 7, "excluded": "no",
        "api_key": [], "provider": [], "queries": "x", "verbose_query": 7, "from_date": 2020, "to_date": [],
        "sources": "openalex", "search_limit": "lots", "ai_api": 1, "ai_model": [], "max_usd": "free",
        "start": "yes", "auto_apply": "yes", "description": [], "score": "high", "rationale": 3,
        "skip_ids": "x", "skip_sources": 1, "include_retracted": "no", "title": [], "extend_limit": "y",
    },
]


@pytest.mark.parametrize("method,rule", [r for r in ROUTES if r[0] in MUTATING])
@pytest.mark.parametrize("body", JUNK_BODIES, ids=["list", "bool", "string", "huge-int", "wrong-types"])
def test_junk_bodies_never_cause_a_server_error(client, method, rule, body):
    response = client.open(concrete(rule), method=method, json=body)
    assert response.status_code < 500, f"{method} {rule} answered {response.status_code} for {str(body)[:60]}"
    assert response.is_json or response.status_code in (200, 202, 204), f"{method} {rule} answered with a non-JSON {response.status_code}"


@pytest.mark.parametrize("method,rule", [r for r in ROUTES if r[0] in MUTATING and r[1] != "/api/data/restore"])
def test_a_body_over_the_limit_is_refused(client, method, rule):
    # A route that reads a JSON body must refuse one over MAX_REQUEST_BYTES (413) without
    # reading it; a route that takes no body never reads it, so its size cannot matter.
    # /api/data/restore takes a backup file as its body, with its own, much larger, limit.
    reads_body = client.open(concrete(rule), method=method, json=[1]).status_code == 400
    response = client.open(concrete(rule), method=method, data=b"{" + b" " * (app_module.MAX_REQUEST_BYTES + 10) + b"}",
                           content_type="application/json")
    if reads_body:
        assert response.status_code == 413, f"{method} {rule} answered {response.status_code} for an oversized body"
    else:
        assert response.status_code < 500, f"{method} {rule} answered {response.status_code} for an oversized body"
