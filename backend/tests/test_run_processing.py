"""Scoring a run chunk by chunk: one request at a time per run, a finished run
reopening when its papers change, and what the Results list calls incomplete."""

import re
import threading

import pytest

import app as app_module
import db
import llm

ABSTRACT = "This study measures the effect of coral growth on reef output in field conditions. " * 2


def make_run(paper_count=3, name="Dataset"):
    dataset_id = db.create_dataset("topic", ["q"], name=name)
    paper_ids = [
        db.get_or_create_paper({"id": f"{name}-W{i}", "title": f"Paper {i}", "abstract": ABSTRACT, "year": 2020})
        for i in range(paper_count)
    ]
    db.add_papers_to_dataset(dataset_id, paper_ids)
    run_id = db.create_analysis_run([dataset_id], "find coral papers", "anthropic", "claude-haiku-4-5")
    return dataset_id, paper_ids, run_id


def scores_for(user, score=70):
    """What a well-behaved model returns for the papers in a prompt."""
    ids = re.findall(r'<paper id="(\d+)">', user)
    return {"scores": [{"id": i, "comparison": "Compared.", "bracket": "strong", "score": score} for i in ids]}


@pytest.fixture
def scoring(fake_llm):
    fake_llm.respond = lambda system, user, schema: scores_for(user)
    return fake_llm


def process(client, run_id):
    return client.post(f"/api/analysis-runs/{run_id}/process")


class TestOneRequestAtATime:
    @pytest.fixture
    def slow_model(self, fake_llm):
        """A model call that waits until the test lets it finish."""
        fake_llm.started = threading.Event()
        fake_llm.release = threading.Event()

        def respond(system, user, schema):
            fake_llm.started.set()
            assert fake_llm.release.wait(10), "the test never released the model call"
            return scores_for(user)

        fake_llm.respond = respond
        yield fake_llm
        fake_llm.release.set()  # never leave a worker thread hanging

    def start_in_background(self, run_id, out):
        def work():
            out["response"] = app_module.app.test_client().post(f"/api/analysis-runs/{run_id}/process")

        thread = threading.Thread(target=work)
        thread.start()
        return thread

    def test_a_second_request_while_one_is_scoring_is_refused_and_not_billed(self, client, slow_model):
        _, _, run_id = make_run()
        first = {}
        thread = self.start_in_background(run_id, first)
        assert slow_model.started.wait(5)

        second = process(client, run_id)

        assert second.status_code == 409
        assert "already being scored" in second.get_json()["error"]
        assert len(slow_model.calls) == 1  # the refused request never reached the model

        slow_model.release.set()
        thread.join(10)
        assert first["response"].status_code == 200
        assert first["response"].get_json()["processed"] == 3
        assert len(slow_model.calls) == 1
        assert len(db.get_run_results(run_id)) == 3

    def test_the_cost_is_charged_once_even_with_many_overlapping_requests(self, client, slow_model):
        _, _, run_id = make_run()
        first = {}
        thread = self.start_in_background(run_id, first)
        assert slow_model.started.wait(5)

        refused = [process(client, run_id).status_code for _ in range(5)]
        slow_model.release.set()
        thread.join(10)

        assert refused == [409] * 5
        with db.closing(db._connect()) as conn:
            calls = conn.execute("SELECT COUNT(*) FROM llm_call WHERE run_id = ?", (run_id,)).fetchone()[0]
        assert calls == 1

    def test_the_run_can_be_processed_again_once_the_first_request_finishes(self, client, slow_model):
        _, _, run_id = make_run()
        first = {}
        thread = self.start_in_background(run_id, first)
        assert slow_model.started.wait(5)
        slow_model.release.set()
        thread.join(10)

        again = process(client, run_id)

        assert again.status_code == 200
        assert again.get_json()["processed"] == 0

    def test_a_different_run_is_not_blocked(self, client, slow_model):
        _, _, busy_run = make_run(name="Busy")
        _, _, other_run = make_run(name="Other")
        first = {}
        thread = self.start_in_background(busy_run, first)
        assert slow_model.started.wait(5)

        # The same slow model answers this one too, so let it through first.
        slow_model.release.set()
        other = process(client, other_run)
        thread.join(10)

        assert other.status_code == 200

    def test_the_lock_is_released_when_the_model_fails(self, client, fake_llm):
        _, _, run_id = make_run()
        fake_llm.respond = lambda *_: (_ for _ in ()).throw(llm.LLMError("Rate limit reached."))
        failed = process(client, run_id)
        assert failed.status_code == 400

        fake_llm.respond = lambda system, user, schema: scores_for(user)
        retried = process(client, run_id)

        assert retried.status_code == 200
        assert retried.get_json()["processed"] == 3

    def test_the_lock_is_released_when_something_unexpected_breaks(self, client, fake_llm):
        _, _, run_id = make_run()
        fake_llm.respond = lambda *_: (_ for _ in ()).throw(RuntimeError("boom"))
        assert process(client, run_id).status_code == 500

        fake_llm.respond = lambda system, user, schema: scores_for(user)
        assert process(client, run_id).status_code == 200

    def test_an_unknown_run_is_a_404_and_takes_no_lock(self, client):
        assert process(client, 999).status_code == 404
        assert process(client, 999).status_code == 404


class TestFinishedRunsReopen:
    def test_a_restored_paper_reopens_a_finished_run_and_only_it_is_scored(self, client, scoring):
        dataset_id, paper_ids, run_id = make_run()
        db.set_dataset_paper_excluded(dataset_id, paper_ids[2], True)
        done = process(client, run_id).get_json()
        assert done["status"] == "completed" and done["processed"] == 2
        earlier = {r["id"]: (r["score"], r["rationale"]) for r in db.get_run_results(run_id)}
        calls_before = len(scoring.calls)

        db.set_dataset_paper_excluded(dataset_id, paper_ids[2], False)
        stale = client.get(f"/api/analysis-runs/{run_id}").get_json()
        assert stale["status"] == "completed" and stale["remaining"] == 1

        reopened = process(client, run_id).get_json()

        assert reopened["processed"] == 1
        assert reopened["status"] == "completed"
        assert reopened["remaining"] == 0
        assert len(scoring.calls) == calls_before + 1
        assert scoring.calls[-1]["user"].count("<paper id=") == 1
        assert {r["id"] for r in db.get_run_results(run_id)} == set(paper_ids)
        for result in db.get_run_results(run_id):
            if result["id"] in earlier:
                assert (result["score"], result["rationale"]) == earlier[result["id"]]

    def test_the_run_is_in_progress_while_the_new_papers_are_scored(self, client, scoring):
        dataset_id, paper_ids, run_id = make_run()
        db.set_dataset_paper_excluded(dataset_id, paper_ids[0], True)
        process(client, run_id)
        db.set_dataset_paper_excluded(dataset_id, paper_ids[0], False)

        scoring.respond = lambda *_: (_ for _ in ()).throw(llm.LLMError("Rate limit reached."))
        failed = process(client, run_id)
        assert failed.status_code == 400

        run = db.get_analysis_run(run_id)
        assert run["status"] == "running"
        assert run["completed_at"] is None
        assert client.get(f"/api/analysis-runs/{run_id}").get_json()["remaining"] == 1

        scoring.respond = lambda system, user, schema: scores_for(user)
        assert process(client, run_id).get_json()["status"] == "completed"
        assert db.get_analysis_run(run_id)["completed_at"] is not None

    def test_a_finished_run_with_nothing_new_is_left_alone(self, client, scoring):
        _, _, run_id = make_run()
        process(client, run_id)
        completed_at = db.get_analysis_run(run_id)["completed_at"]
        calls = len(scoring.calls)

        again = process(client, run_id).get_json()

        assert again["processed"] == 0
        assert again["status"] == "completed"
        assert len(scoring.calls) == calls
        assert db.get_analysis_run(run_id)["completed_at"] == completed_at

    def test_a_run_whose_last_unscored_papers_were_excluded_is_finished_without_the_model(self, client, scoring):
        dataset_id, paper_ids, run_id = make_run()
        for paper_id in paper_ids:
            db.set_dataset_paper_excluded(dataset_id, paper_id, True)
        assert db.get_analysis_run(run_id)["status"] == "running"

        result = process(client, run_id).get_json()

        assert result["status"] == "completed"
        assert result["processed"] == 0
        assert scoring.calls == []

    def test_reopening_keeps_the_runs_prompt_and_examples(self, client, scoring):
        dataset_id, paper_ids, run_id = make_run()
        db.set_dataset_paper_excluded(dataset_id, paper_ids[0], True)
        process(client, run_id)
        before = db.get_analysis_run(run_id)
        db.set_dataset_paper_excluded(dataset_id, paper_ids[0], False)

        process(client, run_id)

        after = db.get_analysis_run(run_id)
        for column in ("grading_prompt", "examples_snapshot", "ai_api", "ai_model", "prompt_id", "name"):
            assert after[column] == before[column]

    def test_reopen_run_only_touches_a_completed_run(self):
        _, _, run_id = make_run()
        db.reopen_run(run_id)
        assert db.get_analysis_run(run_id)["status"] == "running"


class TestResultsListIncomplete:
    def row(self, run_id):
        return next(r for r in db.list_all_runs() if r["id"] == run_id)

    def test_counts_the_papers_still_to_score(self, client, scoring):
        _, _, run_id = make_run()
        assert self.row(run_id)["unscored_count"] == 3
        process(client, run_id)
        assert self.row(run_id)["unscored_count"] == 0

    def test_a_finished_run_whose_papers_came_back_counts_as_unscored(self, client, scoring):
        dataset_id, paper_ids, run_id = make_run()
        process(client, run_id)
        db.set_dataset_paper_excluded(dataset_id, paper_ids[0], True)
        assert self.row(run_id)["unscored_count"] == 0
        db.set_dataset_paper_excluded(dataset_id, paper_ids[0], False)
        # Scored before it was excluded, so its result is still there.
        assert self.row(run_id)["unscored_count"] == 0

        late = db.get_or_create_paper({"id": "late", "title": "Late paper", "abstract": ABSTRACT, "year": 2021})
        db.add_papers_to_dataset(dataset_id, [late])
        row = self.row(run_id)
        assert row["status"] == "completed"
        assert row["unscored_count"] == 1

    def test_a_running_run_with_nothing_left_to_score_is_not_incomplete(self):
        dataset_id, paper_ids, run_id = make_run()
        for paper_id in paper_ids:
            db.set_dataset_paper_excluded(dataset_id, paper_id, True)
        row = self.row(run_id)
        assert row["status"] == "running"
        assert row["unscored_count"] == 0

    def test_a_paper_in_two_datasets_counts_once(self, client, scoring):
        dataset_a, paper_ids, run_id = make_run(name="A")
        dataset_b = db.create_dataset("topic b", ["q"], name="B")
        db.add_papers_to_dataset(dataset_b, paper_ids)
        with db.closing(db._connect()) as conn:
            conn.execute("INSERT INTO analysis_run_dataset (run_id, dataset_id) VALUES (?, ?)", (run_id, dataset_b))
            conn.commit()
        assert self.row(run_id)["unscored_count"] == 3

    def test_the_list_route_exposes_the_count(self, client, scoring):
        _, _, run_id = make_run()
        runs = client.get("/api/analysis-runs").get_json()["runs"]
        assert runs[0]["unscored_count"] == 3
