"""How many of the most relevant papers a search keeps, and the AI writing narrow queries."""

from contextlib import closing

import pytest

import db
import llm
import openalex
import search_sources as ss


def work(i):
    return {"id": f"W{i}", "source": "openalex", "title": f"Paper number {i}", "year": 2024, "authors": []}


@pytest.fixture
def asked(monkeypatch):
    """OpenAlex that records the limit it was asked to keep and returns nothing."""
    seen = []

    def search_all(query, **kwargs):
        seen.append(kwargs["max_results"])
        return [], 0

    monkeypatch.setattr(openalex, "search_all", search_all)
    return seen


class TestTheSetting:
    def create(self, client, **extra):
        return client.post("/api/datasets", json={"question": "coral", "queries": ["coral reef"], **extra})

    def test_the_default_is_100_and_is_kept_with_the_dataset(self, client, asked):
        body = self.create(client).get_json()
        assert asked == [100]
        assert body["search_limit"] == 100

    @pytest.mark.parametrize("limit", [50, 100, 200, 500])
    def test_each_choice_is_used(self, client, asked, limit):
        assert self.create(client, search_limit=limit).get_json()["search_limit"] == limit
        assert asked == [limit]

    @pytest.mark.parametrize("value", [0, 25, 75, 1000, 2500, "100", 100.0, True, [100], {"n": 1}])
    def test_anything_else_is_refused_for_both_steps(self, client, asked, value):
        for path, body in (
            ("/api/datasets", {"question": "coral", "queries": ["coral reef"], "search_limit": value}),
            ("/api/datasets/expand", {"question": "coral", "search_limit": value}),
        ):
            response = client.post(path, json=body)
            assert response.status_code == 400, (path, value)
            assert "search_limit" in response.get_json()["error"]
        assert asked == []

    def test_a_dataset_from_before_the_setting_has_none(self):
        dataset_id = db.create_dataset("topic", ["q"])
        assert db.get_dataset(dataset_id)["search_limit"] is None


class TestReuse:
    """Searching the same question again opens the dataset it made, but only if it was
    made with the same limit: a tighter or wider search is a different pool of papers."""

    def make(self, client, **extra):
        return client.post("/api/datasets", json={"question": "coral", "queries": ["coral reef"], **extra}).get_json()

    def expand(self, client, **extra):
        return client.post("/api/datasets/expand", json={"question": "coral", **extra}).get_json()

    def test_the_same_limit_reuses_and_another_does_not(self, client, asked):
        dataset = self.make(client, search_limit=200)
        same = self.expand(client, search_limit=200)
        assert same["reused"] is True and same["dataset"]["id"] == dataset["id"]

    def test_a_different_limit_is_not_reused(self, client, asked, fake_llm):
        fake_llm.respond = lambda system, user, schema: {"title": "Coral", "queries": ["coral reef growth"]}
        self.make(client, search_limit=200)
        assert self.expand(client, search_limit=50)["reused"] is False
        assert self.expand(client)["reused"] is False  # the default, 100

    def test_a_dataset_from_before_the_setting_counts_as_the_default(self, client, fake_llm):
        fake_llm.respond = lambda system, user, schema: {"title": "Coral", "queries": ["coral reef growth"]}
        dataset_id = db.create_dataset("coral", ["q"], name="Old")
        assert self.expand(client)["dataset"]["id"] == dataset_id
        assert self.expand(client, search_limit=50)["reused"] is False


class TestWhichLimitStoppedIt:
    def test_a_source_s_own_limit_is_told_apart_from_the_users_limit(self, client, monkeypatch):
        monkeypatch.setattr(ss, "SEMANTIC_SCHOLAR_DEPTH", 60)
        monkeypatch.setattr(ss, "semanticscholar_get", lambda url, params, **kw: _page(params))
        monkeypatch.setattr(openalex, "search_all", lambda query, **kw: ([work(i) for i in range(50)], 900))
        monkeypatch.setattr("credentials.has_key", lambda name: True)
        body = {
            "question": "coral",
            "queries": ["coral reef"],
            "sources": ["openalex", "semanticscholar"],
            "search_limit": 200,
        }
        rows = {r["source"]: r for r in client.post("/api/datasets", json=body).get_json()["retrieval"]}
        assert rows["openalex"]["capped_by"] == "source"  # returned only 50 of the 900 it reports
        assert rows["semanticscholar"]["capped_by"] == "source"
        assert "will not return more than 60" in rows["semanticscholar"]["capped"]


def _page(params):
    class Response:
        status_code = 200

        def json(self):
            start = params["offset"]
            return {
                "total": 900,
                "data": [
                    {"paperId": f"s{i}", "title": f"Semantic paper {i}", "year": 2024}
                    for i in range(start, start + params["limit"])
                ],
            }

    return Response()


class TestEachSourceKeepsOnlyTheLimit:
    def test_openalex_pages_no_bigger_than_the_limit(self, monkeypatch):
        sizes = []

        def fetch(params):
            sizes.append(params["per_page"])
            nxt = f"after-{len(sizes)}"
            return {
                "meta": {"count": 9000, "next_cursor": nxt},
                "results": [{"id": f"W{i}", "title": "t"} for i in range(params["per_page"])],
            }

        monkeypatch.setattr(openalex, "_fetch_page", fetch)
        results, total = openalex.search_all("coral", max_results=50)
        assert (len(results), total, sizes) == (50, 9000, [50])
        sizes.clear()
        openalex.search_all("coral", max_results=500)
        # The last page asks only for what is still wanted.
        assert sizes == [200, 200, 100]

    def test_a_narrow_topic_is_not_capped_at_all(self, monkeypatch):
        monkeypatch.setattr(openalex, "search_all", lambda *a, **k: ([work(i) for i in range(30)], 30))
        found = ss._search_openalex("coral reef growth modeling", None, None, 100)
        assert (len(found), found.total, found.capped) == (30, 30, None)


class TestTheAiWritesNarrowQueries:
    def instructions(self, fake_llm):
        fake_llm.respond = lambda system, user, schema: {"title": "Coral", "queries": ["a"]}
        llm.expand_query("question", "anthropic", "claude-haiku-4-5")
        return fake_llm.calls[0]["system"]

    def test_the_instructions_ask_for_a_focused_set_not_broad_recall(self, fake_llm):
        text = self.instructions(fake_llm)
        assert "NARROW" in text and "focused" in text
        assert "never use a bare generic word" in text
        assert "broaden recall" not in text

    def test_no_syntax_that_only_some_sources_understand(self, fake_llm):
        text = self.instructions(fake_llm)
        assert "Do not use boolean operators, quotation marks or wildcards" in text

    def test_it_still_asks_for_at_most_four_queries_and_a_title(self, fake_llm):
        text = self.instructions(fake_llm)
        assert "at most 4 queries" in text and "`title`" in text


class TestMigration:
    def test_a_version_4_database_gets_the_column_and_a_copy(self):
        db.ensure_ready()
        dataset_id = db.create_dataset("topic", ["q"], search_limit=200)
        conn = db.sqlite3.connect(str(db.DB_PATH))
        conn.execute("ALTER TABLE dataset DROP COLUMN search_limit")
        conn.execute("PRAGMA user_version = 4")
        conn.commit()
        conn.close()
        db._ready_for = None
        db.ensure_ready()
        assert db.get_dataset(dataset_id)["search_limit"] is None
        assert db.DB_PATH.with_name(f"{db.DB_PATH.name}.pre-upgrade-4-to-{db.SCHEMA_VERSION}").exists()
        with closing(db._connect()) as conn:
            assert "search_limit" in {row["name"] for row in conn.execute("PRAGMA table_info(dataset)")}
