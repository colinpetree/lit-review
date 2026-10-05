"""Who may use a running copy: the secret in an Authorization header, an open page,
and failing closed. Another account on the same computer shares 127.0.0.1, so
without the secret it must get no data and be able to change nothing.

The secret is a header, never a cookie: a browser sends a cookie to every server on
the same host name whatever its port, and to any request another site makes."""

import pytest

import app as app_module
import db
from conftest import TEST_TOKEN

PAGES = ["/", "/discover", "/datasets/3", "/results", "/settings", "/no-such-page", "/index.html", "/favicon.svg", "/assets/index.js"]
API_READS = [
    "/api/datasets",
    "/api/datasets/1",
    "/api/prompts",
    "/api/prompts/1",
    "/api/analysis-runs",
    "/api/analysis-runs/1",
    "/api/settings/api-key",
    "/api/search?q=coral",
    "/api/no-such-route",
    "/api/",
]
API_WRITES = [
    ("post", "/api/prompts"),
    ("post", "/api/datasets"),
    ("post", "/api/datasets/expand"),
    ("post", "/api/datasets/1/find-abstracts"),
    ("post", "/api/analysis-runs"),
    ("post", "/api/analysis-runs/1/process"),
    ("post", "/api/settings/api-key"),
    ("patch", "/api/prompts/1"),
    ("patch", "/api/papers/1"),
    ("delete", "/api/prompts/1"),
    ("delete", "/api/datasets/1"),
    ("delete", "/api/settings/api-key"),
]


@pytest.fixture
def anonymous(client):
    """A browser that was never connected: the app's own address, no secret."""
    browser = app_module.app.test_client()
    browser.environ_base.pop("HTTP_AUTHORIZATION", None)
    return browser


def bearer(value):
    return {"Authorization": value}


class TestTheApiIsClosedWithoutTheSecret:
    @pytest.mark.parametrize("path", API_READS)
    def test_reads_are_refused_as_json(self, anonymous, path):
        response = anonymous.get(path)
        assert response.status_code == 401
        assert response.get_json() == {"error": app_module.NOT_CONNECTED_MESSAGE}

    @pytest.mark.parametrize("method, path", API_WRITES)
    def test_writes_are_refused(self, anonymous, method, path):
        response = getattr(anonymous, method)(path, json={"name": "x", "description": "y"})
        assert response.status_code == 401
        assert response.get_json() == {"error": app_module.NOT_CONNECTED_MESSAGE}

    def test_a_refused_write_changes_nothing(self, anonymous):
        anonymous.post("/api/prompts", json={"name": "Sneaky", "description": "added by someone else"})
        assert db.list_prompts() == []

    def test_a_refused_request_never_reaches_the_ai_model(self, anonymous, fake_llm):
        dataset_id = db.create_dataset("topic", ["q"], name="D")
        paper_id = db.get_or_create_paper({"id": "W1", "title": "A paper", "abstract": "x" * 200, "year": 2020})
        db.add_papers_to_dataset(dataset_id, [paper_id])
        run_id = db.create_analysis_run([dataset_id], "find coral papers", "anthropic", "claude-haiku-4-5")

        assert anonymous.post(f"/api/analysis-runs/{run_id}/process").status_code == 401
        assert anonymous.post("/api/datasets/expand", json={"question": "coral"}).status_code == 401
        assert fake_llm.calls == []
        assert db.count_unscored_papers(run_id) == 1

    def test_saved_keys_cannot_be_replaced_or_removed(self, anonymous):
        import credentials

        credentials.set_key("anthropic", "mine")
        assert anonymous.post("/api/settings/api-key", json={"provider": "anthropic", "api_key": "theirs"}).status_code == 401
        assert anonymous.delete("/api/settings/api-key", json={"provider": "anthropic"}).status_code == 401
        assert credentials.get_key("anthropic") == "mine"

    def test_a_stranger_cannot_read_what_is_stored(self, anonymous):
        db.create_dataset("my private research topic", ["q"], name="Alice's secret project")
        response = anonymous.get("/api/datasets")
        assert "Alice" not in response.get_data(as_text=True)
        assert "private research" not in response.get_data(as_text=True)

    def test_the_refusal_carries_the_security_headers(self, anonymous):
        headers = anonymous.get("/api/datasets").headers
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Cache-Control"] == "no-store"

    def test_the_refusal_does_not_hint_at_which_routes_exist(self, anonymous):
        real = anonymous.get("/api/datasets")
        made_up = anonymous.get("/api/definitely/not/a/route")
        assert (real.status_code, real.get_json()) == (made_up.status_code, made_up.get_json())

    def test_the_ordering_of_checks_is_host_origin_then_secret(self, anonymous):
        assert anonymous.get("/api/datasets", base_url="http://evil.example:8100").status_code == 403
        assert anonymous.post("/api/prompts", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert anonymous.get("/api/datasets").status_code == 401


class TestThePageItselfIsOpen:
    """The HTML and scripts hold nothing private; the page reads the secret from the
    address it is opened with and sends it with each API call."""

    @pytest.mark.parametrize("path", PAGES)
    def test_pages_are_not_refused(self, anonymous, path):
        response = anonymous.get(path)
        assert response.status_code not in (401, 503)  # served (or a plain 404 where no build exists)

    def test_a_page_never_contains_the_secret(self, anonymous):
        for path in PAGES:
            assert TEST_TOKEN not in anonymous.get(path).get_data(as_text=True)

    def test_health_answers_anyone_and_says_nothing_private(self, anonymous):
        response = anonymous.get("/api/health")
        assert response.status_code == 200
        assert response.get_json() == {"app": "lit-review", "instance": app_module.INSTANCE_ID}
        assert TEST_TOKEN not in response.get_data(as_text=True)

    def test_only_health_is_open_among_the_api_paths(self):
        assert app_module.OPEN_PATHS == {"/api/health"}

    @pytest.mark.parametrize("path", ["/api/health/", "/api/health/x", "/api/healthz", "/api/health.json", "/api/Health"])
    def test_look_alike_api_paths_are_not_open(self, anonymous, path):
        assert anonymous.get(path).status_code in (401, 404)  # never served; a 404 for a case the router rejects first
        assert anonymous.get(path).get_json() != {"app": "lit-review", "instance": app_module.INSTANCE_ID}

    def test_the_old_sign_in_route_is_gone(self, anonymous):
        response = anonymous.get(f"/auth?token={TEST_TOKEN}")
        assert "Set-Cookie" not in response.headers
        assert response.status_code != 302


class TestTheWrongHeader:
    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("", id="empty"),
            pytest.param("Bearer", id="scheme-only"),
            pytest.param("Bearer ", id="scheme-and-space"),
            pytest.param("Bearer x", id="short"),
            pytest.param(f"Bearer {TEST_TOKEN[:-1]}", id="one-short"),
            pytest.param(f"Bearer {TEST_TOKEN}x", id="one-long"),
            pytest.param(f"Bearer {TEST_TOKEN.upper()}", id="upper-cased"),
            pytest.param(f"Bearer {TEST_TOKEN[::-1]}", id="reversed"),
            pytest.param(f"Bearer {'A' * 4000}", id="huge"),
            pytest.param("Bearer ünï", id="latin1-letters"),
            pytest.param("Bearer None", id="None"),
            pytest.param("Bearer null", id="null"),
            pytest.param("Bearer true", id="true"),
            pytest.param(f"Basic {TEST_TOKEN}", id="wrong-scheme-basic"),
            pytest.param(f"Token {TEST_TOKEN}", id="wrong-scheme-token"),
            pytest.param(f"Digest {TEST_TOKEN}", id="wrong-scheme-digest"),
            pytest.param(TEST_TOKEN, id="no-scheme"),
            pytest.param(f"Bearer{TEST_TOKEN}", id="no-space"),
            pytest.param(f"Bearer\t{TEST_TOKEN}", id="tab-not-space"),
        ],
    )
    def test_is_refused_and_never_an_error(self, anonymous, value):
        assert anonymous.get("/api/datasets", headers=bearer(value)).status_code == 401

    def test_another_users_secret_is_refused(self, anonymous):
        other_users_secret = "another-users-secret-" + "y" * 30
        assert anonymous.get("/api/datasets", headers=bearer(f"Bearer {other_users_secret}")).status_code == 401

    def test_the_secret_in_other_places_does_not_count(self, anonymous):
        assert anonymous.get(f"/api/datasets?token={TEST_TOKEN}").status_code == 401
        assert anonymous.get(f"/api/datasets?access_token={TEST_TOKEN}").status_code == 401
        assert anonymous.get("/api/datasets", headers={"X-Token": TEST_TOKEN}).status_code == 401
        assert anonymous.get("/api/datasets", headers={"X-Access-Token": TEST_TOKEN}).status_code == 401
        assert anonymous.get("/api/datasets", headers={"Proxy-Authorization": f"Bearer {TEST_TOKEN}"}).status_code == 401
        assert anonymous.post("/api/prompts", json={"name": "a", "description": "b", "token": TEST_TOKEN}).status_code == 401

    def test_a_cookie_never_authenticates_whatever_it_holds(self, anonymous):
        """The point of using a header: a browser attaches cookies by itself, to every
        server on the host name and to requests made by other sites, so a cookie must
        never be accepted as proof."""
        for name in ("lr_session", "session", "token", "Authorization", "access_token"):
            anonymous.set_cookie(name, TEST_TOKEN, domain="127.0.0.1")
            anonymous.set_cookie(name, f"Bearer {TEST_TOKEN}", domain="127.0.0.1")
        assert anonymous.get("/api/datasets").status_code == 401
        assert anonymous.post("/api/prompts", json={"name": "a", "description": "b"}).status_code == 401
        assert db.list_prompts() == []


class TestTheRightHeader:
    def test_everything_works(self, client):
        assert client.get("/api/datasets").status_code == 200
        assert client.get("/api/prompts").status_code == 200
        assert client.post("/api/prompts", json={"name": "Mine", "description": "wanted"}).status_code == 200

    @pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER", "BeArEr"])
    def test_the_scheme_is_not_case_sensitive(self, anonymous, scheme):
        assert anonymous.get("/api/datasets", headers=bearer(f"{scheme} {TEST_TOKEN}")).status_code == 200

    def test_spaces_around_the_secret_are_ignored(self, anonymous):
        assert anonymous.get("/api/datasets", headers=bearer(f"Bearer   {TEST_TOKEN}  ")).status_code == 200

    def test_it_works_on_either_loopback_name(self, client):
        assert client.get("/api/datasets", base_url="http://localhost:8100").status_code == 200
        assert client.get("/api/datasets", base_url="http://127.0.0.1:8100").status_code == 200

    def test_the_guard_against_other_sites_still_comes_first(self, client):
        assert client.post("/api/prompts", json={"name": "a", "description": "b"}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/datasets", base_url="http://evil.example:8100").status_code == 403


class TestNoCookieIsEverSet:
    @pytest.mark.parametrize("path", ["/", "/api/health", "/api/datasets", "/api/prompts", "/no-such-page", "/api/nothing"])
    def test_with_the_secret(self, client, path):
        assert "Set-Cookie" not in client.get(path).headers

    @pytest.mark.parametrize("path", ["/", "/api/health", "/api/datasets", "/api/nothing", f"/auth?token={TEST_TOKEN}"])
    def test_without_it(self, anonymous, path):
        assert "Set-Cookie" not in anonymous.get(path).headers


class TestFailingClosed:
    @pytest.fixture(autouse=True)
    def no_secret_configured(self, monkeypatch):
        monkeypatch.setitem(app_module.app.config, "ACCESS_TOKEN", None)

    @pytest.mark.parametrize("path", ["/api/datasets", "/api/prompts", "/api/settings/api-key", "/api/nope"])
    def test_a_copy_started_without_a_secret_serves_no_data(self, anonymous, path):
        assert anonymous.get(path).status_code == 503

    @pytest.mark.parametrize("value", ["", "Bearer", "Bearer None", "Bearer null", "Bearer " + "x" * 40, "None"])
    def test_no_header_value_gets_in_when_there_is_no_secret(self, anonymous, value):
        assert anonymous.get("/api/datasets", headers=bearer(value)).status_code == 503

    def test_writes_are_refused_too(self, anonymous):
        assert anonymous.post("/api/prompts", json={"name": "a", "description": "b"}, headers=bearer("Bearer ")).status_code == 503
        assert db.list_prompts() == []

    def test_health_still_answers_so_a_second_launch_can_see_it(self, anonymous):
        assert anonymous.get("/api/health").status_code == 200

    def test_an_empty_secret_is_no_secret(self, monkeypatch, anonymous):
        monkeypatch.setitem(app_module.app.config, "ACCESS_TOKEN", "")
        assert anonymous.get("/api/datasets").status_code == 503
        assert anonymous.get("/api/datasets", headers=bearer("Bearer ")).status_code == 503

    def test_the_app_object_ships_with_no_secret_set(self, tmp_path):
        """Importing the app must not configure one: only main() does, from the user's
        file. Checked in a fresh process, since reloading the module here would swap
        in new copies of its classes under every other test."""
        import os
        import subprocess
        import sys

        from procutil import BACKEND_DIR

        env = {
            **os.environ,
            "LIT_REVIEW_DATA_DIR": str(tmp_path / "data"),
            "LIT_REVIEW_CONFIG_DIR": str(tmp_path / "config"),
        }
        result = subprocess.run(
            [sys.executable, "-c", "import app; print(repr(app.app.config['ACCESS_TOKEN']))"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.stdout.strip() == "None", result.stderr
        assert not (tmp_path / "data" / "access.token").exists()  # and importing made no secret file either


class TestTheSecretIsNeverGivenAway:
    def test_it_is_in_no_response_body_or_header(self, client):
        paths = ["/", "/api/datasets", "/api/prompts", "/api/analysis-runs", "/api/settings/api-key", "/api/health", "/no-such-page", "/api/nope"]
        for path in paths:
            response = client.get(path)
            assert TEST_TOKEN not in response.get_data(as_text=True), path
            assert TEST_TOKEN not in str(response.headers), path

    def test_a_refusal_does_not_echo_what_was_sent(self, anonymous):
        sent = "my-guess-" + "z" * 30
        for response in (
            anonymous.get("/api/datasets", headers=bearer(f"Bearer {sent}")),
            anonymous.get(f"/api/datasets?token={sent}"),
        ):
            assert sent not in response.get_data(as_text=True)
            assert sent not in str(response.headers)

    def test_the_key_status_never_carries_it(self, client):
        assert TEST_TOKEN not in client.get("/api/settings/api-key").get_data(as_text=True)


class TestSameSecret:
    def test_equal_and_unequal(self):
        assert app_module._same_secret("abc", "abc") is True
        assert app_module._same_secret("abd", "abc") is False
        assert app_module._same_secret("", "abc") is False
        assert app_module._same_secret("abc", "abcd") is False

    @pytest.mark.parametrize("odd", ["\udcff", "ünï", "\x00", "💥" * 50, "a\r\nb"])
    def test_any_text_a_client_can_send_compares_without_raising(self, odd):
        assert app_module._same_secret(odd, "abc") is False

    def test_it_uses_a_constant_time_comparison(self, monkeypatch):
        calls = []
        real = app_module.hmac.compare_digest
        monkeypatch.setattr(app_module.hmac, "compare_digest", lambda a, b: calls.append((a, b)) or real(a, b))
        app_module._same_secret("abc", "abc")
        assert calls == [(b"abc", b"abc")]
