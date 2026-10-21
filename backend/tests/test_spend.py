"""Knowing what a run will cost before it starts, and stopping it at a spending limit."""

import json
import math
import re
from contextlib import closing

import pytest

import app as app_module
import db
import jobs as jobs_module
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


class TestResumePastTheLimit:
    """Resume (a run_score job with extend_limit) raises a limit that has stopped the run by the
    limit the run started with, so the user can always carry on past it."""

    make_run = TestSpendingLimit.make_run
    dollar_a_chunk = TestSpendingLimit.dollar_a_chunk

    @pytest.fixture(autouse=True)
    def jobs_can_run(self):
        # A test elsewhere may leave the "stop every job" switch set (as quitting does).
        jobs_module._stop_all.clear()

    def resume(self, client, run_id, extend=True):
        return client.post("/api/jobs", json={"kind": "run_score", "run_id": run_id, "extend_limit": extend})

    def run_info(self, client, run_id):
        return client.get(f"/api/analysis-runs/{run_id}").get_json()

    def test_each_resume_adds_the_starting_limit_again(self, client, dollar_a_chunk):
        run_id = self.make_run(max_usd=1.0)
        self.resume(client, run_id)
        jobs_module.drain()
        stopped = self.run_info(client, run_id)
        assert (stopped["limit_reached"], stopped["next_limit"]) == (True, 2.0)
        assert "Resume raises it by $1.00" in stopped["job"]["error"]

        assert self.resume(client, run_id).status_code == 202
        assert db.get_analysis_run(run_id)["max_usd"] == 2.0
        jobs_module.drain()
        assert self.run_info(client, run_id)["next_limit"] == 3.0  # $1 more, not doubled

        self.resume(client, run_id)
        jobs_module.drain()
        done = self.run_info(client, run_id)
        assert (done["max_usd"], done["remaining"], done["state"]) == (3.0, 0, "completed")

    def test_a_batch_that_went_far_past_the_limit_gets_enough_steps(self, client, dollar_a_chunk):
        run_id = self.make_run(max_usd=0.25)
        self.resume(client, run_id, extend=False)
        jobs_module.drain()  # one $1 batch against a $0.25 limit
        assert self.run_info(client, run_id)["next_limit"] == 1.25
        self.resume(client, run_id)
        assert db.get_analysis_run(run_id)["max_usd"] == 1.25

    @pytest.mark.parametrize(
        "max_usd, spent, expected",
        [(0.1, 0.3, 0.4), (0.1, 0.1 + 0.1 + 0.1, 0.4), (0.7, 2.1, 2.8), (1.0, 1.0, 2.0), (0.25, 1.0, 1.25)],
    )
    def test_the_next_limit_is_always_above_what_is_spent(self, max_usd, spent, expected):
        # Spending that lands exactly on a multiple of the step once came out as "no higher limit".
        assert app_module._next_limit({"max_usd": max_usd, "limit_step": max_usd}, spent) == expected

    def test_a_tiny_limit_steps_by_a_cent_and_answers_at_once(self):
        assert app_module._next_limit({"max_usd": 1e-300, "limit_step": 1e-300}, 0.5) == 0.51

    def test_the_next_limit_stops_at_the_highest_there_is(self):
        top = app_module.MAX_RUN_USD
        assert app_module._next_limit({"max_usd": top - 1, "limit_step": 5}, top - 1) == top
        assert app_module._next_limit({"max_usd": top, "limit_step": 5}, top) is None

    def test_nothing_changes_unless_the_limit_is_what_stops_the_run(self, client, dollar_a_chunk):
        under = self.make_run(max_usd=5.0)
        self.resume(client, under)
        assert db.get_analysis_run(under)["max_usd"] == 5.0
        unlimited = self.make_run()
        self.resume(client, unlimited)
        assert db.get_analysis_run(unlimited)["max_usd"] is None

    def test_without_the_flag_the_limit_holds(self, client, dollar_a_chunk):
        run_id = self.make_run(max_usd=1.0)
        TestSpendingLimit.process(self, client, run_id)
        self.resume(client, run_id, extend=False)
        jobs_module.drain()
        assert db.get_analysis_run(run_id)["max_usd"] == 1.0
        assert len(dollar_a_chunk.calls) == 1

    def test_an_older_run_steps_by_its_current_limit(self, client, dollar_a_chunk):
        run_id = self.make_run(max_usd=1.0)
        with closing(db._connect()) as conn:
            conn.execute("UPDATE analysis_run SET limit_step = NULL, max_usd = 2.0 WHERE id = ?", (run_id,))
            conn.commit()
        for _ in range(2):
            TestSpendingLimit.process(self, client, run_id)
        self.resume(client, run_id)
        assert db.get_analysis_run(run_id)["max_usd"] == 4.0

    def test_two_resumes_together_raise_it_once(self, client, dollar_a_chunk):
        run_id = self.make_run(max_usd=1.0)
        TestSpendingLimit.process(self, client, run_id)
        self.resume(client, run_id)
        self.resume(client, run_id)
        assert db.get_analysis_run(run_id)["max_usd"] == 2.0

    @pytest.mark.parametrize("value", ["yes", 1, None, [True]])
    def test_a_flag_that_is_not_true_or_false_is_refused(self, client, value):
        run_id = self.make_run(max_usd=1.0)
        assert self.resume(client, run_id, extend=value).status_code == 400
        assert client.get("/api/jobs").get_json()["jobs"] == []

    def test_a_run_at_the_highest_limit_is_refused(self, client, dollar_a_chunk, monkeypatch):
        run_id = self.make_run(max_usd=1.0)
        TestSpendingLimit.process(self, client, run_id)
        monkeypatch.setattr(app_module, "MAX_RUN_USD", 1.0)
        response = self.resume(client, run_id)
        assert response.status_code == 400 and "highest spending limit" in response.get_json()["error"]
        assert db.get_analysis_run(run_id)["max_usd"] == 1.0


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
