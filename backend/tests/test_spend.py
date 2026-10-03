"""Knowing what a run will cost before it starts, and stopping it at a spending limit."""

import json
import math
import re
from contextlib import closing

import pytest

import app as app_module
import db
import llm

ABSTRACT = "This study measures the effect of coral growth on reef output in field conditions. " * 2
HAIKU = ("anthropic", "claude-haiku-4-5")  # $1.00 in, $5.00 out per million tokens


def paper(i, abstract=ABSTRACT, **extra):
    return {"id": f"W{i}", "title": f"Paper {i}", "abstract": abstract, "year": 2020, **extra}


def make_dataset(count=3, name="Dataset", **paper_extra):
    dataset_id = db.create_dataset("topic", ["q"], name=name)
    ids = [db.get_or_create_paper(paper(f"{name}-{i}", **paper_extra)) for i in range(count)]
    db.add_papers_to_dataset(dataset_id, ids)
    return dataset_id, ids


def estimate_body(dataset_ids, **extra):
    return {"dataset_ids": dataset_ids, "grading_prompt": "find coral papers", **extra}


class TestEstimateArithmetic:
    def estimate(self, candidates, prompt="find coral papers", examples=(), per_paper=None, chunk=20):
        return llm.estimate_scoring_cost(candidates, prompt, list(examples), *HAIKU, chunk, output_tokens_per_paper=per_paper)

    def test_no_papers_cost_nothing(self):
        assert self.estimate([]) == {"papers": 0, "chunks": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0}

    def test_output_tokens_are_the_default_guess_per_paper(self):
        result = self.estimate([{"title": "t", "abstract": ABSTRACT}] * 10)
        assert result["output_tokens"] == 10 * llm.DEFAULT_OUTPUT_TOKENS_PER_PAPER

    def test_what_earlier_runs_used_replaces_the_guess(self):
        result = self.estimate([{"title": "t", "abstract": ABSTRACT}] * 10, per_paper=400)
        assert result["output_tokens"] == 4000

    def test_the_cost_follows_the_models_rates(self):
        result = self.estimate([{"title": "t", "abstract": ABSTRACT}] * 10)
        expected = (result["input_tokens"] * 1.00 + result["output_tokens"] * 5.00) / 1_000_000
        assert result["usd"] == pytest.approx(expected, abs=1e-6)
        assert result["usd"] > 0

    def test_papers_are_split_into_chunks_and_each_chunk_repeats_the_fixed_text(self):
        one = self.estimate([{"title": "t", "abstract": ABSTRACT}] * 20)
        two = self.estimate([{"title": "t", "abstract": ABSTRACT}] * 21)
        assert (one["chunks"], two["chunks"]) == (1, 2)
        three_more = self.estimate([{"title": "t", "abstract": ABSTRACT}] * 20, chunk=10)
        assert three_more["chunks"] == 2
        assert three_more["input_tokens"] > one["input_tokens"]  # the system prompt is sent twice

    def test_longer_abstracts_and_examples_cost_more(self):
        base = self.estimate([{"title": "t", "abstract": ABSTRACT}])
        longer = self.estimate([{"title": "t", "abstract": ABSTRACT * 20}])
        with_example = self.estimate(
            [{"title": "t", "abstract": ABSTRACT}],
            examples=[{"title": "x", "abstract": ABSTRACT * 5, "score": 90, "rationale": "Good."}],
        )
        assert longer["input_tokens"] > base["input_tokens"]
        assert with_example["input_tokens"] > base["input_tokens"]

    def test_a_missing_or_stub_abstract_is_counted_as_the_short_placeholder(self):
        assert self.estimate([{"title": "t", "abstract": None}]) == self.estimate([{"title": "t", "abstract": "N/A"}])


class TestObservedOutput:
    def test_nothing_is_said_until_enough_papers_have_been_scored(self, fake_llm):
        assert db.observed_output_tokens_per_paper(*HAIKU) is None
        dataset_id, ids = make_dataset(5)
        run_id = db.create_analysis_run([dataset_id], "g", *HAIKU)
        db.record_analysis_chunk(
            run_id, {i: {"score": 50, "rationale": "r"} for i in ids}, llm.Usage(100, 500, model=HAIKU[1], provider=HAIKU[0])
        )
        assert db.observed_output_tokens_per_paper(*HAIKU) is None

    def test_the_average_comes_from_this_models_own_scoring(self):
        dataset_id, ids = make_dataset(25)
        run_id = db.create_analysis_run([dataset_id], "g", *HAIKU)
        db.record_analysis_chunk(
            run_id, {i: {"score": 50, "rationale": "r"} for i in ids}, llm.Usage(100, 5000, model=HAIKU[1], provider=HAIKU[0])
        )
        tokens, papers = db.observed_output_tokens_per_paper(*HAIKU)
        assert (tokens, papers) == (200, 25)
        # Another model's runs say nothing about this one.
        assert db.observed_output_tokens_per_paper("anthropic", "claude-opus-5") is None


class TestEstimateRoute:
    def post(self, client, body):
        return client.post("/api/analysis-runs/estimate", json=body)

    def counts(self):
        with closing(db._connect()) as conn:
            return [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("analysis_run", "llm_call", "prompt")]

    def test_it_prices_the_papers_a_run_would_score_and_changes_nothing(self, client):
        dataset_id, _ = make_dataset(25)
        before = self.counts()
        response = self.post(client, estimate_body([dataset_id]))
        assert response.status_code == 200, response.get_data(as_text=True)
        body = response.get_json()
        assert (body["papers"], body["chunks"], body["basis"], body["approximate"]) == (25, 2, "default", True)
        assert body["usd"] > 0
        assert self.counts() == before

    def test_it_matches_what_a_real_run_would_score(self, client):
        dataset_id, ids = make_dataset(6)
        other_id, _ = make_dataset(4, name="Other")
        db.set_dataset_paper_excluded(dataset_id, ids[0], True)
        retracted = db.get_or_create_paper(paper("R", is_retracted=True))
        db.add_papers_to_dataset(dataset_id, [retracted])
        estimate = self.post(client, estimate_body([dataset_id, other_id])).get_json()
        run_id = db.create_analysis_run([dataset_id, other_id], "g", *HAIKU)
        assert estimate["papers"] == len(db.get_run_candidate_papers(run_id)) == 9
        with_retracted = self.post(client, estimate_body([dataset_id, other_id], include_retracted=True)).get_json()
        assert with_retracted["papers"] == 10

    def test_a_saved_prompt_is_priced_with_its_description_and_examples(self, client):
        dataset_id, ids = make_dataset(3)
        prompt_id = db.create_prompt("P", "find coral papers")
        plain = self.post(client, {"dataset_ids": [dataset_id], "prompt_id": prompt_id}).get_json()
        db.add_prompt_example(prompt_id, ids[0], None, 90, "Good match.")
        with_example = self.post(client, {"dataset_ids": [dataset_id], "prompt_id": prompt_id}).get_json()
        assert with_example["input_tokens"] > plain["input_tokens"]

    def test_once_the_model_has_scored_enough_it_uses_what_it_wrote(self, client):
        dataset_id, ids = make_dataset(25)
        run_id = db.create_analysis_run([dataset_id], "g", *HAIKU)
        db.record_analysis_chunk(
            run_id, {i: {"score": 50, "rationale": "r"} for i in ids}, llm.Usage(100, 25_000, model=HAIKU[1], provider=HAIKU[0])
        )
        other_id, _ = make_dataset(10, name="Other")
        body = self.post(client, estimate_body([other_id])).get_json()
        assert body["basis"] == "history"
        assert body["output_tokens"] == 10_000  # 1,000 a paper

    def test_it_never_calls_the_model(self, client, fake_llm):
        dataset_id, _ = make_dataset(3)
        self.post(client, estimate_body([dataset_id]))
        assert fake_llm.calls == []

    @pytest.mark.parametrize(
        "body",
        [
            [1],
            {},
            {"dataset_ids": []},
            {"dataset_ids": [999], "grading_prompt": "g"},
            {"dataset_ids": [1]},
            {"dataset_ids": [1], "grading_prompt": "g", "include_retracted": "yes"},
            {"dataset_ids": [1], "grading_prompt": "g", "ai_api": "nope"},
            {"dataset_ids": [1], "grading_prompt": "g", "ai_model": "nope"},
            {"dataset_ids": [True], "grading_prompt": "g"},
        ],
    )
    def test_a_bad_request_is_a_400(self, client, body):
        make_dataset(1)
        response = client.post("/api/analysis-runs/estimate", data=json.dumps(body), content_type="application/json")
        assert response.status_code == 400
        assert response.get_json()["error"]


class TestSpendingLimit:
    def make_run(self, count=45, max_usd=None):
        dataset_id, _ = make_dataset(count)
        return db.create_analysis_run([dataset_id], "find coral papers", *HAIKU, max_usd=max_usd)

    @pytest.fixture
    def dollar_a_chunk(self, fake_llm):
        """A model whose every call costs exactly $1.00."""
        fake_llm.input_tokens, fake_llm.output_tokens = 1_000_000, 0
        fake_llm.respond = lambda system, user, schema: {
            "scores": [
                {"id": i, "comparison": "Compared.", "bracket": "strong", "score": 70}
                for i in re.findall(r'<paper id="(\d+)">', user)
            ]
        }
        return fake_llm

    def process(self, client, run_id):
        return client.post(f"/api/analysis-runs/{run_id}/process")

    def test_a_run_with_no_limit_scores_everything(self, client, dollar_a_chunk):
        run_id = self.make_run()
        for _ in range(3):
            assert self.process(client, run_id).status_code == 200
        assert db.count_unscored_papers(run_id) == 0

    def test_scoring_stops_before_the_chunk_that_would_start_past_the_limit(self, client, dollar_a_chunk):
        run_id = self.make_run(max_usd=1.5)
        assert self.process(client, run_id).status_code == 200  # $1.00 spent, under $1.50
        assert self.process(client, run_id).status_code == 200  # $2.00 spent: one chunk past it
        refused = self.process(client, run_id)
        assert refused.status_code == 400
        assert refused.get_json()["limit_reached"] is True
        assert "spending limit of $1.50" in refused.get_json()["error"]
        assert len(dollar_a_chunk.calls) == 2  # the refused request never reached the model
        assert db.get_run_scoring_cost(run_id) == pytest.approx(2.0)

    def test_the_run_page_says_the_limit_is_what_is_holding_it_back(self, client, dollar_a_chunk):
        run_id = self.make_run(max_usd=1.0)
        self.process(client, run_id)
        run = client.get(f"/api/analysis-runs/{run_id}").get_json()
        assert (run["max_usd"], run["scoring_cost"], run["limit_reached"], run["status"]) == (1.0, 1.0, True, "running")
        assert run["remaining"] == 25

    def test_a_limit_is_not_reached_once_there_is_nothing_left_to_score(self, client, dollar_a_chunk):
        run_id = self.make_run(count=20, max_usd=1.0)
        self.process(client, run_id)
        run = client.get(f"/api/analysis-runs/{run_id}").get_json()
        assert run["limit_reached"] is False and run["status"] == "completed"
        again = self.process(client, run_id)
        assert again.status_code == 200 and again.get_json()["processed"] == 0

    def test_raising_the_limit_carries_on_from_the_same_papers(self, client, dollar_a_chunk):
        run_id = self.make_run(max_usd=1.0)
        self.process(client, run_id)
        assert self.process(client, run_id).status_code == 400
        patched = client.patch(f"/api/analysis-runs/{run_id}", json={"max_usd": 5})
        assert patched.status_code == 200 and patched.get_json()["max_usd"] == 5.0
        assert self.process(client, run_id).status_code == 200
        assert db.count_unscored_papers(run_id) == 5
        client.patch(f"/api/analysis-runs/{run_id}", json={"max_usd": None})
        assert self.process(client, run_id).status_code == 200
        assert db.count_unscored_papers(run_id) == 0

    def test_a_limit_that_is_already_spent_does_not_reopen_a_completed_run(self, client, dollar_a_chunk):
        dataset_id, ids = make_dataset(20)
        run_id = db.create_analysis_run([dataset_id], "g", *HAIKU, max_usd=1.0)
        self.process(client, run_id)
        late = db.get_or_create_paper(paper("late"))
        db.add_papers_to_dataset(dataset_id, [late])
        assert self.process(client, run_id).status_code == 400
        assert db.get_analysis_run(run_id)["status"] == "completed"

    def test_runs_from_before_the_limit_existed_have_none(self, client):
        run_id = self.make_run()
        assert db.get_analysis_run(run_id)["max_usd"] is None
        assert client.get(f"/api/analysis-runs/{run_id}").get_json()["limit_reached"] is False


class TestLimitInTheRequests:
    def test_creating_a_run_stores_the_limit(self, client):
        dataset_id, _ = make_dataset(2)
        body = {**estimate_body([dataset_id]), "max_usd": 2.5}
        run = client.post("/api/analysis-runs", json=body).get_json()
        assert run["max_usd"] == 2.5
        assert client.post("/api/analysis-runs", json=estimate_body([dataset_id])).get_json()["max_usd"] is None

    @pytest.mark.parametrize("value", [0, -1, "5", True, [1], {"a": 1}, 10_001, 10**400, -(10**400), math.inf, float("nan")])
    def test_a_bad_limit_is_refused_and_nothing_is_created(self, client, value):
        dataset_id, _ = make_dataset(2)
        # Raw JSON, so infinity and NaN reach the server as the bare words Python's encoder writes.
        response = client.post(
            "/api/analysis-runs",
            data=json.dumps({**estimate_body([dataset_id]), "max_usd": value}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert db.list_all_runs() == []

    def test_patching_a_bad_limit_changes_neither_the_limit_nor_the_name(self, client):
        dataset_id, _ = make_dataset(2)
        run = client.post("/api/analysis-runs", json={**estimate_body([dataset_id]), "max_usd": 2}).get_json()
        response = client.patch(f"/api/analysis-runs/{run['id']}", json={"name": "Renamed", "max_usd": -5})
        assert response.status_code == 400
        after = db.get_analysis_run(run["id"])
        assert after["max_usd"] == 2 and after["name"] == run["name"]

    def test_a_rename_alone_leaves_the_limit_and_a_limit_alone_leaves_the_name(self, client):
        dataset_id, _ = make_dataset(2)
        run = client.post("/api/analysis-runs", json={**estimate_body([dataset_id]), "max_usd": 2}).get_json()
        renamed = client.patch(f"/api/analysis-runs/{run['id']}", json={"name": "Renamed"}).get_json()
        assert (renamed["name"], renamed["max_usd"]) == ("Renamed", 2)
        limited = client.patch(f"/api/analysis-runs/{run['id']}", json={"max_usd": 3}).get_json()
        assert (limited["name"], limited["max_usd"]) == ("Renamed", 3)

    def test_the_old_blank_name_message_still_applies(self, client):
        dataset_id, _ = make_dataset(2)
        run = client.post("/api/analysis-runs", json=estimate_body([dataset_id])).get_json()
        assert client.patch(f"/api/analysis-runs/{run['id']}", json={}).status_code == 400
