"""The "is there a newer version" check. No test reaches GitHub: the HTTP call is faked."""

import pytest

import source_http
import updates


class Reply:
    def __init__(self, status=200, data=None, bad_json=False):
        self.status_code = status
        self._data = data
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._data


def release(tag="v0.2.0", url="https://github.com/colinpetree/lit-review/releases/tag/v0.2.0", body="Notes"):
    return {"tag_name": tag, "html_url": url, "body": body}


@pytest.fixture(autouse=True)
def fresh_cache():
    updates.forget()
    yield
    updates.forget()


@pytest.fixture
def github(monkeypatch):
    """Whatever the test sets `answer` to is what GitHub says; `calls` counts asks."""

    class Fake:
        answer = Reply(200, release())
        calls = []

    def get(label, url, **kwargs):
        Fake.calls.append((label, url, kwargs))
        if isinstance(Fake.answer, Exception):
            raise Fake.answer
        return Fake.answer

    Fake.calls = []
    monkeypatch.setattr(source_http, "get", get)
    return Fake


class TestParseVersion:
    @pytest.mark.parametrize(
        "text,expected",
        [("v1.2.3", (1, 2, 3)), ("1.2.3", (1, 2, 3)), (" v10.0.12 ", (10, 0, 12)), ("v0.1.0", (0, 1, 0))],
    )
    def test_good(self, text, expected):
        assert updates.parse_version(text) == expected

    @pytest.mark.parametrize("text", ["0.0.0-dev", "v1.2", "v1.2.3-rc1", "latest", "", None, 5, "v1.2.3.4"])
    def test_not_a_release_number(self, text):
        assert updates.parse_version(text) is None

    def test_compares_as_numbers_not_text(self):
        assert updates.parse_version("v0.10.0") > updates.parse_version("v0.9.0")


class TestCheck:
    def test_a_newer_release_is_offered(self, github):
        result = updates.check("0.1.0")
        assert result == {
            "current": "0.1.0",
            "latest": "0.2.0",
            "newer": True,
            "url": "https://github.com/colinpetree/lit-review/releases/tag/v0.2.0",
            "notes": "Notes",
        }

    def test_the_same_or_an_older_release_is_not(self, github):
        assert updates.check("0.2.0")["newer"] is False
        updates.forget()
        assert updates.check("0.3.0")["newer"] is False

    def test_a_dev_build_never_says_there_is_an_update(self, github):
        assert updates.check("0.0.0-dev")["newer"] is False

    def test_it_asks_with_the_program_name_and_nothing_else(self, github):
        updates.check("0.1.0")
        label, url, kwargs = github.calls[0]
        assert url == "https://api.github.com/repos/colinpetree/lit-review/releases/latest"
        assert kwargs["headers"]["User-Agent"] == "lit-review/0.1.0"
        assert set(kwargs) == {"headers"}

    def test_the_answer_is_kept_for_a_day(self, github):
        updates.check("0.1.0")
        updates.check("0.1.0")
        assert len(github.calls) == 1

    @pytest.mark.parametrize(
        "answer",
        [
            Reply(500),
            Reply(403, {"message": "rate limited"}),
            Reply(200, bad_json=True),
            Reply(200, ["not", "an", "object"]),
            Reply(200, {"tag_name": "nightly"}),
            Reply(200, {}),
            source_http.SourceUnavailable("Could not reach GitHub."),
        ],
    )
    def test_any_trouble_means_nothing_new(self, github, answer):
        github.answer = answer
        result = updates.check("0.1.0")
        assert result["newer"] is False and result["url"] is None

    def test_a_failure_is_not_asked_again_at_once(self, github):
        github.answer = Reply(500)
        updates.check("0.1.0")
        updates.check("0.1.0")
        assert len(github.calls) == 1

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "https://evil.example/colinpetree/lit-review/releases/tag/v0.2.0",
            "https://github.com/someone-else/lit-review/releases/tag/v0.2.0",
            "http://github.com/colinpetree/lit-review/releases/tag/v0.2.0",
            None,
            42,
        ],
    )
    def test_a_link_that_is_not_this_projects_release_page_is_never_offered(self, github, url):
        github.answer = Reply(200, release(url=url))
        result = updates.check("0.1.0")
        assert result["url"] is None
        assert result["newer"] is False  # nothing to link to, so nothing to announce

    def test_notes_are_cut_short(self, github):
        github.answer = Reply(200, release(body="x" * 10_000))
        assert len(updates.check("0.1.0")["notes"]) == updates.MAX_NOTES_CHARS


class TestRoute:
    def test_it_answers_with_the_check(self, client, github):
        body = client.get("/api/update-check").get_json()
        assert body["current"] == "0.0.0-dev"
        assert body["newer"] is False

    def test_it_needs_the_session_like_every_other_api_call(self, client):
        import app as app_module

        stranger = app_module.app.test_client()
        stranger.environ_base.pop("HTTP_AUTHORIZATION", None)  # a browser that was never connected
        response = stranger.get("/api/update-check", base_url=f"http://127.0.0.1:{app_module.PORT}")
        assert response.status_code == 401
