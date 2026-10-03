"""Bad request bodies are refused with a 400 and a readable message, never a 500,
and the bounds that keep one request from doing unbounded work."""

import json

import pytest

import app as app_module
import db
import llm
import openalex

ABSTRACT = "This study measures the effect of coral growth on reef output in field conditions. " * 2
LONG = "x" * 5000


@pytest.fixture
def ids():
    """One of each thing a route can be pointed at."""
    dataset_id = db.create_dataset("topic", ["q"], name="Dataset")
    paper_id = db.get_or_create_paper({"id": "W1", "title": "A paper", "abstract": ABSTRACT, "year": 2020})
    db.add_papers_to_dataset(dataset_id, [paper_id])
    prompt_id = db.create_prompt("Prompt", "find coral papers")
    run_id = db.create_analysis_run([dataset_id], "find coral papers", "anthropic", "claude-haiku-4-5", prompt_id)
    return {"dataset": dataset_id, "paper": paper_id, "prompt": prompt_id, "run": run_id}


GOOD_USAGE = {"input_tokens": 10, "output_tokens": 5, "ai_api": "anthropic", "model": "claude-haiku-4-5"}


def create_body(**changes):
    body = {"question": "coral reefs", "queries": ["coral reef"], "usage": GOOD_USAGE}
    body.update(changes)
    return body


# (method, path, body) for every body a route must refuse. {dataset} {paper} {prompt}
# and {run} are filled in with real ids.
BAD_REQUESTS = [
    # Not an object at all
    ("post", "/api/settings/api-key", [1, 2]),
    ("post", "/api/datasets/expand", "text"),
    ("post", "/api/datasets", [1]),
    ("post", "/api/analysis-runs", 5),
    ("patch", "/api/papers/{paper}", ["title"]),
    ("patch", "/api/prompts/{prompt}", [1]),
    ("patch", "/api/datasets/{dataset}/papers/{paper}", [1]),
    ("post", "/api/datasets/{dataset}/find-abstracts", [1]),
    # API keys
    ("post", "/api/settings/api-key", {"provider": ["anthropic"], "api_key": "k"}),
    ("post", "/api/settings/api-key", {"provider": {"a": 1}, "api_key": "k"}),
    ("post", "/api/settings/api-key", {"provider": "anthropic", "api_key": 12345}),
    ("post", "/api/settings/api-key", {"provider": "anthropic", "api_key": ["k"]}),
    ("post", "/api/settings/api-key", {"provider": "anthropic", "api_key": "k" * 513}),
    ("post", "/api/settings/api-key", {"provider": "anthropic", "api_key": "   "}),
    ("post", "/api/settings/api-key", {"provider": 5, "api_key": "k"}),
    ("delete", "/api/settings/api-key", {"provider": ["anthropic"]}),
    ("delete", "/api/settings/api-key", {"provider": None}),
    # expand
    ("post", "/api/datasets/expand", {"question": 123}),
    ("post", "/api/datasets/expand", {"question": ["a"]}),
    ("post", "/api/datasets/expand", {"question": "q" * 4001}),
    ("post", "/api/datasets/expand", {"question": "q", "ai_api": ["anthropic"]}),
    ("post", "/api/datasets/expand", {"question": "q", "ai_model": {"a": 1}}),
    ("post", "/api/datasets/expand", {"question": "q", "sources": "openalex"}),
    # create dataset
    ("post", "/api/datasets", create_body(question=7)),
    ("post", "/api/datasets", create_body(queries="coral")),
    ("post", "/api/datasets", create_body(queries=[])),
    ("post", "/api/datasets", create_body(queries=["", "   "])),
    ("post", "/api/datasets", create_body(queries=[1, 2])),
    ("post", "/api/datasets", create_body(queries=[f"query {i}" for i in range(11)])),
    ("post", "/api/datasets", create_body(queries=["q" * 301])),
    ("post", "/api/datasets", create_body(usage=[1])),
    ("post", "/api/datasets", create_body(usage="x")),
    ("post", "/api/datasets", create_body(usage={**GOOD_USAGE, "input_tokens": -1})),
    ("post", "/api/datasets", create_body(usage={**GOOD_USAGE, "input_tokens": "10"})),
    ("post", "/api/datasets", create_body(usage={**GOOD_USAGE, "output_tokens": 10**9})),
    ("post", "/api/datasets", create_body(usage={**GOOD_USAGE, "output_tokens": True})),
    ("post", "/api/datasets", create_body(usage={**GOOD_USAGE, "input_tokens": [5]})),
    ("post", "/api/datasets", create_body(usage={**GOOD_USAGE, "ai_api": ["anthropic"]})),
    ("post", "/api/datasets", create_body(title=["a"])),
    # rename
    ("patch", "/api/datasets/{dataset}", {"name": 5}),
    ("patch", "/api/datasets/{dataset}", {"name": ["a"]}),
    ("patch", "/api/datasets/{dataset}", {"name": LONG}),
    ("patch", "/api/analysis-runs/{run}", {"name": 5}),
    ("patch", "/api/analysis-runs/{run}", {"name": {"a": 1}}),
    ("patch", "/api/analysis-runs/{run}", {"name": LONG}),
    # abstract lookup
    ("post", "/api/datasets/{dataset}/find-abstracts", {"skip_ids": "1"}),
    ("post", "/api/datasets/{dataset}/find-abstracts", {"skip_ids": list(range(10_001))}),
    ("post", "/api/datasets/{dataset}/find-abstracts", {"skip_sources": ["europepmc"] * 50}),
    ("post", "/api/datasets/{dataset}/find-abstracts", {"skip_sources": "europepmc"}),
    # papers
    ("patch", "/api/papers/{paper}", {"title": 5}),
    ("patch", "/api/papers/{paper}", {"title": ["a"]}),
    ("patch", "/api/papers/{paper}", {"title": "t" * 1001}),
    ("patch", "/api/papers/{paper}", {"abstract": 5}),
    ("patch", "/api/papers/{paper}", {"abstract": "a" * 20_001}),
    ("patch", "/api/papers/{paper}", {"venue": 5}),
    ("patch", "/api/papers/{paper}", {"venue": "v" * 301}),
    ("patch", "/api/papers/{paper}", {"url": "https://example.com/" + "a" * 2000}),
    ("patch", "/api/papers/{paper}", {"url": 5}),
    ("patch", "/api/papers/{paper}", {"year": True}),
    ("patch", "/api/papers/{paper}", {"year": "2020"}),
    ("patch", "/api/papers/{paper}", {"year": 2020.5}),
    ("patch", "/api/papers/{paper}", {"year": 999}),
    ("patch", "/api/papers/{paper}", {"year": 2101}),
    ("patch", "/api/papers/{paper}", {"year": [2020]}),
    ("patch", "/api/papers/{paper}", {"read": "yes"}),
    ("patch", "/api/datasets/{dataset}/papers/{paper}", {"excluded": "yes"}),
    # runs
    ("post", "/api/analysis-runs", {"dataset_ids": "1", "prompt_id": 1}),
    ("post", "/api/analysis-runs", {"dataset_ids": [], "prompt_id": 1}),
    ("post", "/api/analysis-runs", {"dataset_ids": [True], "prompt_id": 1}),
    ("post", "/api/analysis-runs", {"dataset_ids": ["1"], "prompt_id": 1}),
    ("post", "/api/analysis-runs", {"dataset_ids": [1.5], "prompt_id": 1}),
    ("post", "/api/analysis-runs", {"dataset_ids": [[1]], "prompt_id": 1}),
    ("post", "/api/analysis-runs", {"dataset_ids": [10**30], "prompt_id": 1}),
    ("post", "/api/analysis-runs", {"dataset_ids": [1], "prompt_id": "1"}),
    ("post", "/api/analysis-runs", {"dataset_ids": [1], "prompt_id": True}),
    ("post", "/api/analysis-runs", {"dataset_ids": [1], "prompt_id": [1]}),
    ("post", "/api/analysis-runs", {"dataset_ids": [1], "grading_prompt": 5}),
    ("post", "/api/analysis-runs", {"dataset_ids": [1], "grading_prompt": "g" * 4001}),
    ("post", "/api/analysis-runs", {"dataset_ids": [1], "grading_prompt": "g", "ai_api": ["anthropic"]}),
    ("post", "/api/analysis-runs", {"dataset_ids": [1], "grading_prompt": "g", "ai_model": ["m"]}),
    # prompts
    ("post", "/api/prompts", {"name": 5, "description": "d"}),
    ("post", "/api/prompts", {"name": "n", "description": ["d"]}),
    ("patch", "/api/prompts/{prompt}", {"name": ["n"], "description": "d"}),
    ("patch", "/api/prompts/{prompt}", {"name": "n", "description": 5}),
    # results and examples
    ("patch", "/api/analysis-runs/{run}/results/{paper}", {"relevance": ["relevant"]}),
    ("patch", "/api/analysis-runs/{run}/results/{paper}", {"relevance": 5}),
    ("post", "/api/analysis-runs/{run}/examples", {"paper_id": True}),
    ("post", "/api/analysis-runs/{run}/examples", {"paper_id": "1"}),
    ("post", "/api/analysis-runs/{run}/examples", {"paper_id": [1]}),
    ("post", "/api/analysis-runs/{run}/examples", {"paper_id": 1.5}),
    ("post", "/api/analysis-runs/{run}/examples", {"paper_id": 10**30}),
    ("post", "/api/analysis-runs/{run}/examples", {}),
]


def send(client, method, path, body):
    # Raw JSON, so values the test client would not serialize the same way still get through.
    return getattr(client, method)(path, data=json.dumps(body), content_type="application/json")


class TestBadBodiesAreRefused:
    @pytest.mark.parametrize("method,path,body", BAD_REQUESTS, ids=[f"{m} {p} {i}" for i, (m, p, _) in enumerate(BAD_REQUESTS)])
    def test_answers_400_with_a_message(self, client, ids, method, path, body):
        response = send(client, method, path.format(**ids), body)
        assert response.status_code == 400, response.get_data(as_text=True)
        assert response.get_json()["error"]

    def test_nothing_was_saved_by_the_refused_requests(self, client, ids):
        send(client, "post", "/api/settings/api-key", {"provider": "anthropic", "api_key": "k" * 513})
        send(client, "patch", "/api/papers/{paper}".format(**ids), {"title": "t" * 1001})
        assert db.get_paper(ids["paper"])["title"] == "A paper"
        assert not app_module.credentials.has_key("anthropic")


class TestQueries:
    @pytest.fixture
    def source(self, monkeypatch):
        calls = []

        def search_all(query, **kwargs):
            calls.append(query)
            return [], 0

        monkeypatch.setattr(openalex, "search_all", search_all)
        return calls

    def test_blank_and_repeated_queries_are_dropped_before_searching(self, client, source):
        response = client.post(
            "/api/datasets", json=create_body(queries=["  coral reef ", "", "Coral Reef", "reef   fish"])
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        assert source == ["coral reef", "reef fish"]
        assert response.get_json()["expanded_queries"] == ["coral reef", "reef fish"]

    def test_ten_queries_are_allowed(self, client, source):
        response = client.post("/api/datasets", json=create_body(queries=[f"query {i}" for i in range(10)]))
        assert response.status_code == 200
        assert len(source) == 10

    def test_a_refused_request_searches_nothing(self, client, source):
        client.post("/api/datasets", json=create_body(queries=[f"query {i}" for i in range(11)]))
        assert source == []

    def test_a_missing_usage_is_allowed(self, client, source):
        body = create_body()
        del body["usage"]
        assert client.post("/api/datasets", json=body).status_code == 200


class TestExpandQuery:
    def expand(self, fake_llm, answer):
        fake_llm.respond = lambda system, user, schema: answer
        return llm.expand_query("question", "anthropic", "claude-haiku-4-5")

    def test_blank_repeated_and_extra_queries_are_cleaned(self, fake_llm):
        answer = {"title": "Coral", "queries": [" a ", "A", "", "b", "c", "d", "e"]}
        queries, _, _ = self.expand(fake_llm, answer)
        assert queries == ["a", "b", "c", "d"]

    def test_a_long_query_is_cut_so_it_passes_the_api_limit(self, fake_llm):
        queries, _, _ = self.expand(fake_llm, {"title": "t", "queries": ["w" * 400]})
        assert len(queries[0]) == llm.MAX_QUERY_CHARS

    @pytest.mark.parametrize("queries", [[], ["", "  "]])
    def test_no_usable_query_is_an_error_that_carries_the_cost(self, fake_llm, queries):
        with pytest.raises(llm.LLMError, match="did not return any usable") as caught:
            self.expand(fake_llm, {"title": "t", "queries": queries})
        assert caught.value.usage.input_tokens == fake_llm.input_tokens

    def test_the_route_logs_the_cost_of_an_unusable_answer(self, client, fake_llm):
        fake_llm.respond = lambda system, user, schema: {"title": "t", "queries": []}
        response = client.post("/api/datasets/expand", json={"question": "coral reefs", "ai_api": "anthropic"})
        assert response.status_code == 400
        assert "reword" in response.get_json()["error"].lower()
        assert db.get_cost() > 0


class TestRequestLimits:
    def test_an_oversized_body_is_refused_in_json(self, client):
        body = json.dumps({"question": "q", "padding": "x" * (app_module.MAX_REQUEST_BYTES + 1)})
        response = client.post("/api/datasets/expand", data=body, content_type="application/json")
        assert response.status_code == 413
        assert response.get_json()["error"]

    def test_a_normal_abstract_is_not_near_the_limit(self, client, ids):
        response = client.patch(f"/api/papers/{ids['paper']}", json={"abstract": "a" * 20_000})
        assert response.status_code == 200


class TestUnexpectedErrors:
    def test_a_bug_is_a_json_500_with_the_key_removed_from_the_log(self, client, monkeypatch, caplog):
        def boom():
            raise RuntimeError("failed: https://api.example/works?api_key=SECRET123&x=1")

        monkeypatch.setattr(db, "list_datasets", boom)
        response = client.get("/api/datasets")
        assert response.status_code == 500
        assert response.get_json() == {"error": "Something went wrong on the server. Please try again."}
        assert "SECRET123" not in caplog.text
        assert "RuntimeError" in caplog.text

    def test_http_errors_keep_their_status(self, client, ids):
        assert client.get("/api/nothing-here").status_code == 404
        assert client.get("/api/nothing-here").get_json()["error"]
        assert client.delete("/api/datasets").status_code == 405
        assert client.get("/api/datasets/999").status_code == 404
