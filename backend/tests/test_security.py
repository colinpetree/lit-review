"""The request guard, response headers, log redaction and URL checks."""

import logging

import pytest
import requests

import app as app_module
import db
import source_http

GOOD_HOST = f"http://127.0.0.1:{app_module.PORT}"


class TestHostGuard:
    @pytest.mark.parametrize("host", ["evil.example", "evil.example:8100", "127.0.0.1:9999", "localhost", "127.0.0.1"])
    def test_wrong_host_is_refused_on_any_route(self, client, host):
        for path in ("/api/datasets", "/", "/anything"):
            response = client.get(path, base_url=f"http://{host}")
            assert response.status_code == 403, (host, path)
        assert client.post("/api/prompts", json={}, base_url=f"http://{host}").status_code == 403

    @pytest.mark.parametrize("host", ["127.0.0.1:8100", "localhost:8100", "LOCALHOST:8100"])
    def test_our_own_names_work(self, client, host):
        assert client.get("/api/datasets", base_url=f"http://{host}").status_code == 200

    def test_a_refused_request_does_nothing(self, client):
        client.post(
            "/api/prompts",
            json={"name": "x", "description": "y"},
            base_url="http://evil.example:8100",
        )
        assert db.list_prompts() == []


class TestOriginGuard:
    BODY = {"name": "Prompt", "description": "What I want"}

    @pytest.mark.parametrize(
        "origin",
        [
            "https://evil.example",
            "http://evil.example:8100",
            "null",
            "http://localhost:3000",
            "https://127.0.0.1:8100",  # wrong scheme
            "http://127.0.0.1:8100.evil.example",
            "",
        ],
    )
    def test_mutating_requests_from_other_origins_are_refused(self, client, origin):
        response = client.post("/api/prompts", json=self.BODY, headers={"Origin": origin})
        assert response.status_code == 403
        assert db.list_prompts() == []

    @pytest.mark.parametrize("method", ["post", "patch", "delete"])
    def test_every_mutating_method_is_checked(self, client, method):
        response = getattr(client, method)("/api/prompts/1", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403

    @pytest.mark.parametrize("origin", [GOOD_HOST, "http://localhost:8100", "HTTP://LOCALHOST:8100"])
    def test_our_own_origin_is_accepted(self, client, origin):
        response = client.post("/api/prompts", json=self.BODY, headers={"Origin": origin})
        assert response.status_code == 200

    def test_a_request_with_no_origin_is_accepted(self, client):
        assert client.post("/api/prompts", json=self.BODY).status_code == 200

    def test_reads_are_not_blocked_by_origin(self, client):
        # Reading across origins is stopped by the browser (no CORS headers are
        # sent); the guard only has to stop requests that change things.
        assert client.get("/api/datasets", headers={"Origin": "https://evil.example"}).status_code == 200

    def test_a_cross_site_post_cannot_spend_money_on_a_run(self, client, fake_llm):
        """The body-less /process POST is the one a hostile page could send with
        no preflight; it must never reach the model."""
        dataset_id = db.create_dataset("topic", ["q"], name="Topic")
        paper_id = db.get_or_create_paper({"id": "W1", "title": "A paper", "abstract": "x" * 200, "year": 2020})
        db.add_papers_to_dataset(dataset_id, [paper_id])
        run_id = db.create_analysis_run([dataset_id], "find coral papers", "anthropic", "claude-haiku-4-5")
        fake_llm.respond = lambda *_: {"scores": [{"id": str(paper_id), "comparison": "ok", "bracket": "strong", "score": 70}]}

        blocked = client.post(f"/api/analysis-runs/{run_id}/process", headers={"Origin": "https://evil.example"})
        assert blocked.status_code == 403
        assert fake_llm.calls == []
        assert db.count_unscored_papers(run_id) == 1

        allowed = client.post(f"/api/analysis-runs/{run_id}/process")
        assert allowed.status_code == 200
        assert len(fake_llm.calls) == 1
        assert db.count_unscored_papers(run_id) == 0

    def test_a_cross_site_post_cannot_trigger_an_abstract_lookup(self, client):
        dataset_id = db.create_dataset("topic", ["q"], name="Topic")
        response = client.post(
            f"/api/datasets/{dataset_id}/find-abstracts", headers={"Origin": "https://evil.example"}
        )
        assert response.status_code == 403

    def test_saved_keys_cannot_be_changed_cross_site(self, client):
        response = client.post(
            "/api/settings/api-key",
            json={"provider": "anthropic", "api_key": "attacker"},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403
        assert not app_module.credentials.has_key("anthropic")


class TestSecurityHeaders:
    @pytest.mark.parametrize("path", ["/api/datasets", "/api/prompts", "/no-such-page"])
    def test_headers_are_on_every_response(self, client, path):
        headers = client.get(path).headers
        assert headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "no-referrer"

    def test_headers_are_on_refused_requests_too(self, client):
        response = client.get("/api/datasets", base_url="http://evil.example:8100")
        assert response.status_code == 403
        assert response.headers["X-Frame-Options"] == "DENY"

    def test_api_responses_are_not_cached(self, client):
        assert client.get("/api/datasets").headers["Cache-Control"] == "no-store"

    def test_error_responses_from_the_api_are_not_cached(self, client):
        assert client.get("/api/datasets/999").headers["Cache-Control"] == "no-store"

    def test_font_types_are_known(self):
        import mimetypes

        assert mimetypes.guess_type("a.woff2")[0] == "font/woff2"
        assert mimetypes.guess_type("a.woff")[0] == "font/woff"
        assert mimetypes.guess_type("a.webp")[0] == "image/webp"


class TestRemovedRoutes:
    def test_the_open_openalex_proxy_is_gone(self, client, monkeypatch):
        def must_not_run(*args, **kwargs):
            raise AssertionError("OpenAlex was searched through the removed proxy")

        monkeypatch.setattr(app_module.openalex, "search_all", must_not_run)
        response = client.get("/api/search?q=coral")
        assert response.status_code == 404
        assert response.get_json() == {"error": "not found"}

    @pytest.mark.parametrize("path", ["/api", "/api/", "/api/nothing/here"])
    def test_unknown_api_paths_are_json_404s_not_the_app_page(self, client, path):
        response = client.get(path)
        assert response.status_code == 404
        assert response.get_json() == {"error": "not found"}

    def test_app_pages_still_fall_back_to_the_frontend(self, client):
        # Not under /api, so a client-side route such as /results/3 must not 404 as JSON.
        response = client.get("/results/3")
        assert response.get_json(silent=True) != {"error": "not found"}


class TestRedact:
    @pytest.mark.parametrize(
        "text, hidden",
        [
            ("429 Client Error for url: https://api.openalex.org/works?search=x&api_key=SECRET123&per_page=5", "SECRET123"),
            ("https://api.springernature.com/meta/v2/json?q=doi:1&api_key=abcDEF", "abcDEF"),
            ("url: https://x.test/a?API_KEY=UPPER&b=1", "UPPER"),
            ("https://x.test/a?apikey=nodash", "nodash"),
            ("https://x.test/a?key=short", "short"),
            ("https://x.test/a?token=tok123", "tok123"),
            ("https://x.test/a?search=y&api-key=dashed", "dashed"),
        ],
    )
    def test_secret_values_are_hidden(self, text, hidden):
        cleaned = source_http.redact(text)
        assert hidden not in cleaned
        assert "REDACTED" in cleaned

    def test_the_rest_of_the_message_is_kept(self):
        cleaned = source_http.redact("429 Too Many Requests for url: https://a.test/works?search=coral&api_key=S&per_page=5")
        assert "search=coral" in cleaned and "per_page=5" in cleaned and "429 Too Many Requests" in cleaned

    def test_text_without_secrets_is_unchanged(self):
        assert source_http.redact("Connection refused") == "Connection refused"

    def test_it_accepts_exceptions(self):
        assert "SECRET" not in source_http.redact(ValueError("bad url ...?api_key=SECRET"))

    def test_the_openalex_error_log_hides_the_key(self, client, caplog):
        """The real path: an HTTP error from requests carries the full URL."""
        response = requests.Response()
        response.status_code = 500
        response.url = "https://api.openalex.org/works?search=x&api_key=TOPSECRET"
        error = requests.HTTPError(
            "500 Server Error: Internal Server Error for url: " + response.url, response=response
        )
        with app_module.app.app_context(), caplog.at_level(logging.WARNING):
            app_module._openalex_error_response(error)
        assert "TOPSECRET" not in caplog.text
        assert "REDACTED" in caplog.text

    def test_the_retrieval_failure_log_hides_the_key(self, client, monkeypatch, caplog):
        def boom(*args, **kwargs):
            raise requests.ConnectionError("Max retries exceeded with url: /works?search=x&api_key=TOPSECRET")

        monkeypatch.setitem(
            app_module.search_sources.SEARCH_SOURCES_BY_ID,
            "openalex",
            app_module.search_sources.SearchSource("openalex", "OpenAlex", boom),
        )
        with caplog.at_level(logging.WARNING):
            response = client.post("/api/datasets", json={"question": "coral", "queries": ["coral"]})
        assert response.status_code == 502
        assert "TOPSECRET" not in caplog.text and "TOPSECRET" not in response.get_data(as_text=True)


class TestSafeUrl:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://doi.org/10.1/x", "https://doi.org/10.1/x"),
            ("  http://example.com/a?b=c  ", "http://example.com/a?b=c"),
            ("HTTPS://EXAMPLE.COM", "HTTPS://EXAMPLE.COM"),
        ],
    )
    def test_web_addresses_are_kept(self, value, expected):
        assert source_http.safe_url(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "javascript:alert(1)",
            "JaVaScRiPt:alert(1)",
            " javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:x",
            "file:///C:/Windows/win.ini",
            "ftp://example.com/f",
            "//example.com/x",
            "https://",
            "http:///path",
            "example.com",
            "",
            "   ",
            None,
            42,
            ["https://example.com"],
        ],
    )
    def test_everything_else_is_refused(self, value):
        assert source_http.safe_url(value) is None

    def test_a_malformed_url_does_not_raise(self):
        assert source_http.safe_url("http://[::1") is None


class TestPaperUrlRoute:
    @pytest.fixture
    def paper_id(self):
        return db.get_or_create_paper({"id": "W1", "title": "A paper", "year": 2020, "url": "https://example.com/p"})

    @pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html,x", "ftp://x.test/f", "example.com"])
    def test_a_non_web_url_is_rejected_and_nothing_is_saved(self, client, paper_id, bad):
        response = client.patch(f"/api/papers/{paper_id}", json={"url": bad})
        assert response.status_code == 400
        assert "http" in response.get_json()["error"]
        assert db.get_paper(paper_id)["url"] == "https://example.com/p"

    def test_a_non_text_url_is_rejected(self, client, paper_id):
        assert client.patch(f"/api/papers/{paper_id}", json={"url": 5}).status_code == 400
        assert client.patch(f"/api/papers/{paper_id}", json={"url": ["https://x.test"]}).status_code == 400

    def test_a_web_url_is_saved_trimmed(self, client, paper_id):
        response = client.patch(f"/api/papers/{paper_id}", json={"url": "  https://new.example/p  "})
        assert response.status_code == 200
        assert db.get_paper(paper_id)["url"] == "https://new.example/p"

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_a_blank_url_clears_the_link(self, client, paper_id, blank):
        response = client.patch(f"/api/papers/{paper_id}", json={"url": blank})
        assert response.status_code == 200
        assert db.get_paper(paper_id)["url"] is None

    def test_other_fields_are_untouched_by_a_rejected_url(self, client, paper_id):
        client.patch(f"/api/papers/{paper_id}", json={"title": "Changed", "url": "javascript:x"})
        assert db.get_paper(paper_id)["title"] == "A paper"

    def test_an_unsafe_url_from_a_search_source_is_not_stored(self):
        paper_id = db.get_or_create_paper(
            {"id": "W2", "title": "Hostile", "year": 2021, "url": "javascript:alert(document.cookie)"}
        )
        assert db.get_paper(paper_id)["url"] is None

    def test_a_missing_url_from_a_source_is_stored_as_none(self):
        paper_id = db.get_or_create_paper({"id": "W3", "title": "No link", "year": 2021})
        assert db.get_paper(paper_id)["url"] is None
