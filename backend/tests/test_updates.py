"""Version parsing, and the update-status route (the checking itself is in test_updater.py)."""

import pytest

import updater
import updates


@pytest.fixture(autouse=True)
def fresh_status():
    updater.reset_for_tests()
    yield
    updater.reset_for_tests()


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


class TestRoute:
    def test_it_answers_with_the_status(self, client):
        body = client.get("/api/update-check").get_json()
        assert body["current"] == "0.0.0-dev"
        assert body["state"] == "idle" and body["latest"] is None
        assert body["auto_apply"] is False

    def test_it_needs_the_session_like_every_other_api_call(self, client):
        import app as app_module

        stranger = app_module.app.test_client()
        stranger.environ_base.pop("HTTP_AUTHORIZATION", None)  # a browser that was never connected
        response = stranger.get("/api/update-check", base_url=f"http://127.0.0.1:{app_module.PORT}")
        assert response.status_code == 401
