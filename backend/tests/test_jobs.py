"""Background jobs: queueing work, running it away from any request, stopping and resuming it,
and what the lists say about it. The worker threads are never started in tests; `jobs.drain()`
runs whatever is queued on the test's own thread."""

import re
from contextlib import closing

import pytest

import abstracts
import app as app_module
import db
import jobs
import llm
import openalex
from providers import LLMError
from test_refresh import recent_date

ABSTRACT = "This study measures the effect of coral growth on reef output in field conditions. " * 2


@pytest.fixture(autouse=True)
def quick_jobs(monkeypatch):
    monkeypatch.setattr(jobs, "RETRY_WAITS", (0, 0, 0))
    jobs._stop_all.clear()


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
    ids = re.findall(r'<paper id="(\d+)">', user)
    return {"scores": [{"id": i, "comparison": "Compared.", "bracket": "strong", "score": score} for i in ids]}


@pytest.fixture
def scoring(fake_llm):
    fake_llm.respond = lambda system, user, schema: scores_for(user)
    return fake_llm


def queue(client, kind, **fields):
    response = client.post("/api/jobs", json={"kind": kind, **fields})
    assert response.status_code in (200, 202), response.get_data(as_text=True)
    return response.get_json()


def run_info(client, run_id):
    return client.get(f"/api/analysis-runs/{run_id}").get_json()


class TestScoringJob:
    def test_a_queued_run_is_graded_in_the_background(self, client, scoring):
        _, paper_ids, run_id = make_run(3)
        job = queue(client, "run_score", run_id=run_id)["job"]
        assert job["status"] == "queued"
        assert run_info(client, run_id)["state"] == "queued"
        assert scoring.calls == []  # queueing grades nothing

        assert jobs.drain() == 1

        run = run_info(client, run_id)
        assert run["state"] == "completed" and run["remaining"] == 0
        assert {r["id"] for r in run["results"]} == set(paper_ids)
        finished = db.get_job(job["id"])
        assert finished["status"] == "completed" and finished["progress"]["remaining"] == 0

    def test_a_finished_run_does_not_send_its_papers_twice(self, client, scoring):
        _, _, run_id = make_run(3)
        before = run_info(client, run_id)
        assert len(before["candidate_papers"]) == 3 and before["results"] == []  # still to be graded
        queue(client, "run_score", run_id=run_id)
        jobs.drain()
        after = run_info(client, run_id)
        assert len(after["results"]) == 3 and after["candidate_papers"] == []

    def test_a_run_in_progress_sends_only_the_papers_still_to_grade(self, client, scoring):
        _, _, run_id = make_run(45)  # three batches of 20
        queue(client, "run_score", run_id=run_id)
        job_id = db.list_jobs()[0]["id"]
        seen = []
        original = scoring.respond

        def respond(system, user, schema):
            seen.append(run_info(client, run_id))
            if len(seen) == 2:
                db.request_stop(job_id)
            return original(system, user, schema)

        scoring.respond = respond
        jobs.drain()
        # Before the first batch nothing is graded, so all 45 are listed; after it the 20 graded are not.
        assert (len(seen[0]["results"]), len(seen[0]["candidate_papers"])) == (0, 45)
        assert (len(seen[1]["results"]), len(seen[1]["candidate_papers"])) == (20, 25)
        listed = {p["id"] for p in seen[1]["candidate_papers"]}
        assert listed.isdisjoint({p["id"] for p in seen[1]["results"]})

    def test_a_run_can_be_created_and_queued_in_one_request(self, client, scoring):
        dataset_id, _, _ = make_run(2)
        body = {"dataset_ids": [dataset_id], "grading_prompt": "coral", "ai_api": "anthropic", "ai_model": "claude-haiku-4-5"}
        run = client.post("/api/analysis-runs", json={**body, "start": True}).get_json()
        assert run["state"] == "queued" and run["job"]["kind"] == "run_score"
        plain = client.post("/api/analysis-runs", json=body).get_json()
        assert plain["job"] is None and plain["state"] == "incomplete"  # nothing has graded it yet
        assert client.post("/api/analysis-runs", json={**body, "start": "yes"}).status_code == 400

    def test_asking_twice_returns_the_same_job(self, client, scoring):
        _, _, run_id = make_run()
        first = queue(client, "run_score", run_id=run_id)["job"]
        second = queue(client, "run_score", run_id=run_id)["job"]
        assert first["id"] == second["id"]
        assert len(db.list_jobs()) == 1

    def test_jobs_run_one_at_a_time_in_the_order_they_were_queued(self, client, scoring):
        _, _, first = make_run(2, name="First")
        _, _, second = make_run(2, name="Second")
        queue(client, "run_score", run_id=first)
        queue(client, "run_score", run_id=second)
        jobs.drain()
        a, b = [db.get_job(j["id"]) for j in db.list_jobs()]
        assert a["status"] == b["status"] == "completed"
        assert a["finished_at"] <= b["started_at"]

    def test_a_waiting_job_can_be_stopped_and_picked_up_again(self, client, scoring):
        _, _, run_id = make_run()
        job = queue(client, "run_score", run_id=run_id)["job"]
        stopped = client.post(f"/api/jobs/{job['id']}/stop").get_json()["job"]
        assert stopped["status"] == "incomplete"
        assert jobs.drain() == 0 and scoring.calls == []

        resumed = client.post(f"/api/jobs/{job['id']}/resume").get_json()["job"]
        assert resumed["status"] == "queued"
        jobs.drain()
        assert run_info(client, run_id)["state"] == "completed"

    def test_stopping_a_running_job_ends_it_after_the_batch_it_is_on(self, client, scoring):
        _, _, run_id = make_run(45)  # three batches of 20
        job = queue(client, "run_score", run_id=run_id)["job"]
        stops = []

        def respond(system, user, schema):
            if not stops:
                stops.append(client.post(f"/api/jobs/{job['id']}/stop").get_json()["job"])
            return scores_for(user)

        scoring.respond = respond
        jobs.drain()

        assert stops[0]["stop_requested"] is True
        ended = db.get_job(job["id"])
        assert ended["status"] == "incomplete" and "Stopped" in ended["error"]
        run = run_info(client, run_id)
        assert len(run["results"]) == 20 and run["remaining"] == 25  # the batch in flight finished
        assert run["state"] == "incomplete"

        scoring.respond = lambda system, user, schema: scores_for(user)
        client.post(f"/api/jobs/{job['id']}/resume")
        jobs.drain()
        assert run_info(client, run_id)["remaining"] == 0
        assert len(scoring.calls) == 3  # no batch was graded twice

    def test_only_a_stopped_job_can_be_resumed(self, client, scoring):
        _, _, run_id = make_run()
        job = queue(client, "run_score", run_id=run_id)["job"]
        assert client.post(f"/api/jobs/{job['id']}/resume").status_code == 409
        assert client.post("/api/jobs/9999/resume").status_code == 404
        assert client.post("/api/jobs/9999/stop").status_code == 404

    def test_a_failure_that_may_pass_is_tried_again(self, client, fake_llm):
        _, _, run_id = make_run(2)
        job = queue(client, "run_score", run_id=run_id)["job"]
        attempts = []

        def respond(system, user, schema):
            attempts.append(1)
            if len(attempts) < 3:
                raise LLMError("Anthropic rate limit reached.", retryable=True)
            return scores_for(user)

        fake_llm.respond = respond
        jobs.drain()
        assert db.get_job(job["id"])["status"] == "completed"
        assert len(attempts) == 3

    def test_a_failure_that_will_not_pass_is_not_asked_again_and_is_kept_for_resuming(self, client, fake_llm):
        _, _, run_id = make_run(2)
        job = queue(client, "run_score", run_id=run_id)["job"]

        def respond(system, user, schema):
            raise LLMError("Anthropic rejected the API key - check it in Settings.")

        fake_llm.respond = respond
        jobs.drain()
        ended = db.get_job(job["id"])
        assert ended["status"] == "incomplete" and "rejected the API key" in ended["error"]
        assert len(fake_llm.calls) == 1  # asking again would only have been billed again
        info = run_info(client, run_id)
        assert info["state"] == "incomplete" and info["job"]["error"] == ended["error"]

    def test_retries_stop_after_a_few_tries(self, client, fake_llm):
        _, _, run_id = make_run(2)
        job = queue(client, "run_score", run_id=run_id)["job"]

        def respond(system, user, schema):
            raise LLMError("Anthropic rate limit reached.", retryable=True)

        fake_llm.respond = respond
        jobs.drain()
        assert db.get_job(job["id"])["status"] == "incomplete"
        assert len(fake_llm.calls) == len(jobs.RETRY_WAITS) + 1

    def test_an_answer_that_was_billed_but_unusable_is_charged_once_and_not_retried(self, client, fake_llm):
        _, _, run_id = make_run(2)
        queue(client, "run_score", run_id=run_id)

        def respond(system, user, schema):
            raise LLMError(
                "The AI returned grades in an unexpected format.",
                usage=llm.Usage(100, 50, model="claude-haiku-4-5", provider="anthropic"),
            )

        fake_llm.respond = respond
        jobs.drain()
        assert len(fake_llm.calls) == 1
        assert db.get_run_scoring_cost(run_id) > 0

    def test_a_spending_limit_ends_the_job_incomplete_and_raising_it_carries_on(self, client, scoring):
        _, _, run_id = make_run(45)
        db.set_run_max_usd(run_id, 0.0000001)
        job = queue(client, "run_score", run_id=run_id)["job"]
        jobs.drain()
        ended = db.get_job(job["id"])
        assert ended["status"] == "incomplete" and "spending limit" in ended["error"]
        assert run_info(client, run_id)["limit_reached"] is True

        db.set_run_max_usd(run_id, 50)
        client.post(f"/api/jobs/{job['id']}/resume")
        jobs.drain()
        assert run_info(client, run_id)["state"] == "completed"

    def test_a_failure_on_the_follow_up_call_keeps_what_the_first_call_graded(self, client, fake_llm):
        _, paper_ids, run_id = make_run(3)
        queue(client, "run_score", run_id=run_id)
        calls = []

        def respond(system, user, schema):
            calls.append(re.findall(r'<paper id="(\d+)">', user))
            if len(calls) == 1:  # the model skips the last paper
                return scores_for(user.replace(f'<paper id="{paper_ids[-1]}">', '<paper id="x">'))
            if len(calls) == 2:  # and the call asking again about it fails
                raise LLMError("Anthropic rate limit reached.", retryable=True)
            return scores_for(user)

        fake_llm.respond = respond
        jobs.drain()
        assert [len(c) for c in calls] == [3, 1, 1]  # the first batch was not asked (and paid for) again
        assert run_info(client, run_id)["state"] == "completed"

    def test_a_run_whose_papers_all_came_back_empty_does_not_loop(self, client, fake_llm):
        _, _, run_id = make_run(2)
        queue(client, "run_score", run_id=run_id)
        fake_llm.respond = lambda system, user, schema: {"scores": []}
        jobs.drain()
        assert len(fake_llm.calls) <= 4  # two tries for the skipped papers, then it gives up


class TestInterruptions:
    def test_a_job_cut_off_by_closing_comes_back_incomplete_and_lookups_start_again(self, client, scoring):
        _, _, run_id = make_run()
        dataset_id = make_run(1, name="Other")[0]
        score = queue(client, "run_score", run_id=run_id)["job"]
        look = queue(client, "find_abstracts", dataset_id=dataset_id)["job"]
        db.claim_next_job(jobs.PAID_KINDS)  # now "running", as if the app was closed mid-job
        db.claim_next_job(jobs.LOOKUP_KINDS)

        db.interrupt_stale_jobs()

        assert db.get_job(score["id"])["status"] == "incomplete"
        assert "interrupted" in db.get_job(score["id"])["error"]
        assert db.get_job(look["id"])["status"] == "queued"

    def test_a_restore_during_a_job_makes_it_leave_without_writing(self, client, scoring):
        _, _, run_id = make_run(45)
        job = queue(client, "run_score", run_id=run_id)["job"]
        original = scoring.respond

        def respond(system, user, schema):
            db._EPOCH += 1  # as if a backup replaced the data while this batch was out
            return original(system, user, schema)

        scoring.respond = respond
        jobs.drain()
        assert db.get_job(job["id"])["status"] == "running"  # it did not record an ending
        assert len(scoring.calls) == 1  # and it did not go on to the next batch

    def test_a_job_waits_while_the_gate_is_closed(self, client, scoring, monkeypatch):
        _, _, run_id = make_run(2)
        queue(client, "run_score", run_id=run_id)
        attempts = []

        class Gate:
            def enter(self):
                attempts.append(1)
                return len(attempts) > 3  # closed for the first three tries

            def leave(self):
                pass

        monkeypatch.setattr(jobs, "_gate", Gate())
        monkeypatch.setattr(jobs, "GATE_POLL_SECONDS", 0)
        jobs.drain()
        assert len(attempts) >= 4 and run_info(client, run_id)["state"] == "completed"

    def test_a_job_stopped_with_the_old_wording_reads_the_current_message_after_an_upgrade(self, client):
        _, _, run_id = make_run()
        old = queue(client, "run_score", run_id=run_id)["job"]
        other = queue(client, "run_score", run_id=make_run(1, name="Other")[2])["job"]
        with closing(db.sqlite3.connect(str(db.DB_PATH))) as conn:
            conn.execute(
                "UPDATE job SET status = 'incomplete', error = ? WHERE id = ?",
                ("Stopped. What was finished is kept; resume it to carry on.", old["id"]),
            )
            conn.execute("UPDATE job SET status = 'incomplete', error = 'Out of credit.' WHERE id = ?", (other["id"],))
            conn.commit()
        db._ready_for = None
        db.ensure_ready()
        assert db.get_job(old["id"])["error"] == db.STOPPED_BY_USER == "Stopped by user."
        assert db.get_job(other["id"])["error"] == "Out of credit."  # other reasons are left alone


class TestDeleting:
    def test_deleting_a_run_stops_its_waiting_job(self, client, scoring):
        _, _, run_id = make_run()
        job = queue(client, "run_score", run_id=run_id)["job"]
        assert client.delete(f"/api/analysis-runs/{run_id}").status_code == 200
        assert db.get_job(job["id"])["status"] == "incomplete"
        assert jobs.drain() == 0

    def test_a_job_whose_run_was_deleted_while_it_ran_ends_quietly(self, client, scoring):
        _, _, run_id = make_run(45)
        job = queue(client, "run_score", run_id=run_id)["job"]
        original = scoring.respond

        def respond(system, user, schema):
            db.delete_analysis_run(run_id)
            return original(system, user, schema)

        scoring.respond = respond
        jobs.drain()
        assert db.get_job(job["id"])["status"] == "incomplete"
        assert len(scoring.calls) == 1

    def test_something_being_worked_on_cannot_be_purged_from_the_trash(self, client, scoring):
        _, _, run_id = make_run()
        job = queue(client, "run_score", run_id=run_id)["job"]
        db.delete_analysis_run(run_id)  # soft delete only: the job is still queued
        with pytest.raises(db.TrashError):
            db.purge_from_trash("run", run_id)
        db.request_stop(job["id"])
        assert db.purge_from_trash("run", run_id) is not None
        assert db.get_job(job["id"]) is None  # its record went with it


class TestDatasetSearchJob:
    @pytest.fixture
    def searching(self, fake_llm, monkeypatch):
        state = {"papers": [], "asked": []}

        def search_all(query, from_date=None, to_date=None, max_results=None):
            state["asked"].append(query)
            return state["papers"], len(state["papers"])

        monkeypatch.setattr(openalex, "search_all", search_all)
        fake_llm.respond = lambda system, user, schema: {"queries": ["coral reef growth", "reef fish"], "title": "Coral Reefs"}

        def lookup(doi, skip_sources=frozenset(), title=None, answered_before=frozenset()):
            return abstracts.Lookup(None, None, {}, frozenset(), True)

        monkeypatch.setattr(abstracts, "lookup_abstract", lookup)
        state["llm"] = fake_llm
        return state

    def paper(self, i):
        return {
            "id": f"W{i}", "source": "openalex", "title": f"Paper number {i}", "year": 2024,
            "publication_date": "2024-05-01", "abstract": ABSTRACT, "authors": [], "citation_count": 1,
            "doi": f"https://doi.org/10.1/x{i}",
        }

    def start(self, client, **extra):
        return client.post("/api/jobs", json={"kind": "dataset_search", "question": "coral reef growth", **extra})

    def test_the_dataset_appears_at_once_and_is_filled_in_by_the_job(self, client, searching):
        searching["papers"] = [self.paper(1), self.paper(2)]
        body = self.start(client).get_json()
        dataset_id = body["dataset"]["id"]
        assert body["dataset"]["pending"] is True and body["dataset"]["state"] == "queued"
        listed = client.get("/api/datasets").get_json()["datasets"]
        assert [(d["id"], d["pending"], d["state"], d["paper_count"]) for d in listed] == [(dataset_id, True, "queued", 0)]

        jobs.drain()

        dataset = client.get(f"/api/datasets/{dataset_id}").get_json()
        assert dataset["pending"] is False and dataset["state"] == "completed"
        assert dataset["name"] == "Coral Reefs" and dataset["expanded_queries"] == ["coral reef growth", "reef fish"]
        assert len(dataset["papers"]) == 2
        assert dataset["expansion"] is not None  # the AI step was paid for and recorded once

    def test_a_dataset_still_being_searched_cannot_be_evaluated_or_checked(self, client, searching):
        dataset_id = self.start(client).get_json()["dataset"]["id"]
        body = {"dataset_ids": [dataset_id], "grading_prompt": "x", "ai_api": "anthropic", "ai_model": "claude-haiku-4-5"}
        assert client.post("/api/analysis-runs/estimate", json=body).status_code == 400
        assert client.post("/api/analysis-runs", json=body).status_code == 400
        assert client.post("/api/jobs", json={"kind": "dataset_refresh", "dataset_id": dataset_id}).status_code == 400
        assert client.post("/api/jobs", json={"kind": "find_abstracts", "dataset_id": dataset_id}).status_code == 400
        assert client.post(f"/api/datasets/{dataset_id}/refresh").status_code == 400

    def test_a_finished_search_is_reused_and_a_repeat_while_it_waits_is_the_same_job(self, client, searching):
        first = self.start(client).get_json()
        again = self.start(client).get_json()
        assert again["existing"] is True and again["job"]["id"] == first["job"]["id"]
        assert len(client.get("/api/datasets").get_json()["datasets"]) == 1
        jobs.drain()
        reused = self.start(client).get_json()
        assert reused["reused"] is True and reused["dataset"]["id"] == first["dataset"]["id"]

    def test_a_failed_search_stays_incomplete_and_resuming_does_not_pay_for_the_ai_again(self, client, searching):
        def failing(query, from_date=None, to_date=None, max_results=None):
            raise openalex.requests.ConnectionError("boom")

        original = openalex.search_all
        openalex.search_all = failing
        try:
            body = self.start(client).get_json()
            jobs.drain()
        finally:
            openalex.search_all = original
        dataset = client.get(f"/api/datasets/{body['dataset']['id']}").get_json()
        assert dataset["pending"] is True and dataset["state"] == "incomplete"
        assert "Failed to reach OpenAlex" in dataset["job"]["error"]
        ai_calls = len(searching["llm"].calls)
        assert ai_calls == 1

        searching["papers"] = [self.paper(1)]
        resumed = self.start(client).get_json()  # the same search again picks the stopped one up
        assert resumed["job"]["id"] == body["job"]["id"] and resumed["job"]["status"] == "queued"
        jobs.drain()
        assert len(searching["llm"].calls) == ai_calls  # the saved queries were used
        assert client.get(f"/api/datasets/{body['dataset']['id']}").get_json()["state"] == "completed"
        assert len(client.get("/api/datasets").get_json()["datasets"]) == 1

    def test_a_finished_search_queues_the_abstract_lookup(self, client, searching):
        searching["papers"] = [{**self.paper(1), "abstract": ""}]
        dataset_id = self.start(client).get_json()["dataset"]["id"]
        jobs.drain()
        kinds = [(j["kind"], j["status"]) for j in db.list_jobs() if j["dataset_id"] == dataset_id]
        assert kinds == [("dataset_search", "completed"), ("find_abstracts", "completed")]

    def test_searching_again_right_after_deleting_a_running_search_gets_its_own_job(self, client, searching):
        first = self.start(client).get_json()
        assert db.claim_next_job(jobs.PAID_KINDS)["id"] == first["job"]["id"]  # the worker has it
        client.delete(f"/api/datasets/{first['dataset']['id']}")
        second = self.start(client).get_json()
        assert second["dataset"]["id"] != first["dataset"]["id"]
        assert second["job"]["id"] != first["job"]["id"]
        assert [j["dataset_id"] for j in db.list_jobs() if j["status"] == "queued"] == [second["dataset"]["id"]]

    def test_a_dataset_can_be_stopped_before_its_search_starts_and_deleted(self, client, searching):
        body = self.start(client).get_json()
        client.post(f"/api/jobs/{body['job']['id']}/stop")
        dataset = client.get(f"/api/datasets/{body['dataset']['id']}").get_json()
        assert dataset["state"] == "incomplete" and dataset["pending"] is True
        assert client.delete(f"/api/datasets/{body['dataset']['id']}").status_code == 200
        assert client.get("/api/datasets").get_json()["datasets"] == []


class TestLookupAndRefreshJobs:
    def dataset_with(self, count, abstract="", tag="W"):
        dataset_id = db.create_dataset("topic", ["q"], name="D")
        ids = [
            db.get_or_create_paper(
                {"id": f"{tag}{i}", "title": f"{tag} paper {i}", "abstract": abstract, "year": 2020, "doi": f"https://doi.org/10.1/{tag}{i}"}
            )
            for i in range(count)
        ]
        db.add_papers_to_dataset(dataset_id, ids)
        return dataset_id, ids

    def test_abstracts_are_looked_up_in_the_background_across_batches(self, client, monkeypatch):
        dataset_id, ids = self.dataset_with(25)

        def find(doi, skip_sources=frozenset(), title=None, answered_before=frozenset()):
            return abstracts.Lookup(ABSTRACT, "europepmc", {}, frozenset({"europepmc"}), True)

        monkeypatch.setattr(abstracts, "lookup_abstract", find)
        job = queue(client, "find_abstracts", dataset_id=dataset_id)["job"]
        jobs.drain()
        done = db.get_job(job["id"])
        assert done["status"] == "completed" and done["progress"]["filled"] == 25
        assert all(db.get_paper(i)["abstract"] for i in ids)

    def test_a_source_having_trouble_is_reported_but_is_not_a_failed_job(self, client, monkeypatch):
        dataset_id, _ = self.dataset_with(3)

        def find(doi, skip_sources=frozenset(), title=None, answered_before=frozenset()):
            return abstracts.Lookup(None, None, {"europepmc": "Could not reach Europe PMC"}, frozenset(), False)

        monkeypatch.setattr(abstracts, "lookup_abstract", find)
        job = queue(client, "find_abstracts", dataset_id=dataset_id)["job"]
        jobs.drain()
        done = db.get_job(job["id"])
        assert done["status"] == "completed" and "europepmc" in done["progress"]["source_errors"]
        assert client.get(f"/api/datasets/{dataset_id}").get_json()["state"] == "completed"

    def test_a_dataset_shows_running_while_a_lookup_is_under_way(self, client):
        dataset_id, _ = self.dataset_with(2)
        queue(client, "find_abstracts", dataset_id=dataset_id)
        assert client.get(f"/api/datasets/{dataset_id}").get_json()["state"] == "queued"
        db.claim_next_job(jobs.LOOKUP_KINDS)
        assert client.get("/api/datasets").get_json()["datasets"][0]["state"] == "running"

    def test_saving_a_lookup_key_queues_lookups_for_datasets_with_papers_left_to_try(self, client):
        wanted, _ = self.dataset_with(2)
        done, _ = self.dataset_with(2, abstract=ABSTRACT, tag="X")
        client.post("/api/settings/api-key", json={"provider": "semanticscholar", "api_key": "k"})
        queued = [j["dataset_id"] for j in db.list_jobs() if j["kind"] == "find_abstracts"]
        assert queued == [wanted] and done not in queued

    def test_a_check_for_new_papers_runs_as_a_job_and_then_looks_up_abstracts(self, client, monkeypatch):
        dataset_id, _ = self.dataset_with(1, abstract=ABSTRACT)
        published = recent_date()
        paper = {
            "id": "W99", "source": "openalex", "title": "A brand new paper", "year": published.year,
            "publication_date": published.isoformat(), "abstract": ABSTRACT, "authors": [], "citation_count": 0,
        }
        monkeypatch.setattr(openalex, "search_all", lambda query, from_date=None, to_date=None, max_results=None: ([paper], 1))
        job = queue(client, "dataset_refresh", dataset_id=dataset_id)["job"]
        jobs.drain()
        assert db.get_job(job["id"])["progress"]["new_count"] == 1
        assert len(client.get(f"/api/datasets/{dataset_id}").get_json()["papers"]) == 2

    def test_a_check_job_adds_only_the_datasets_limit_of_new_papers(self, client, monkeypatch):
        dataset_id, _ = self.dataset_with(1, abstract=ABSTRACT)
        with closing(db._connect()) as conn:
            conn.execute("UPDATE dataset SET search_limit = 50 WHERE id = ?", (dataset_id,))
            conn.commit()
        published = recent_date()
        papers = [
            {
                "id": f"N{i}", "source": "openalex", "title": f"Fresh paper {i}", "year": published.year,
                "publication_date": published.isoformat(), "abstract": ABSTRACT, "authors": [], "citation_count": 0,
            }
            for i in range(120)
        ]
        monkeypatch.setattr(
            openalex, "search_all", lambda query, from_date=None, to_date=None, max_results=None: (papers, 9000)
        )
        job = queue(client, "dataset_refresh", dataset_id=dataset_id)["job"]
        jobs.drain()
        assert db.get_job(job["id"])["progress"]["new_count"] == 50
        held = {p["title"] for p in client.get(f"/api/datasets/{dataset_id}").get_json()["papers"]}
        assert {f"Fresh paper {i}" for i in range(50)} <= held and "Fresh paper 50" not in held

    def test_a_check_whose_search_ended_in_the_past_is_refused_up_front(self, client):
        dataset_id = db.create_dataset("topic", ["q"], name="Old", from_date="2020-01-01", to_date="2020-12-31")
        response = client.post("/api/jobs", json={"kind": "dataset_refresh", "dataset_id": dataset_id})
        assert response.status_code == 400 and "no newer papers" in response.get_json()["error"]
        assert db.list_jobs() == []


class TestStates:
    def job(self, kind, status, id=1, stop=False):
        return {"id": id, "kind": kind, "status": status, "stop_requested": stop}

    def test_a_dataset_that_has_finished_is_completed_whatever_its_old_jobs_say(self):
        assert jobs.dataset_state(False, [self.job("find_abstracts", "incomplete")]) == ("completed", None)

    def test_a_dataset_shows_the_job_working_on_it(self):
        running = self.job("find_abstracts", "running", 3)
        waiting = self.job("dataset_refresh", "queued", 2)
        assert jobs.dataset_state(False, [waiting, running])[0] == "running"

    def test_a_dataset_whose_search_has_not_finished_follows_that_search(self):
        assert jobs.dataset_state(True, [self.job("dataset_search", "incomplete")])[0] == "incomplete"
        assert jobs.dataset_state(True, [self.job("dataset_search", "running", stop=True)])[0] == "stopping"
        assert jobs.dataset_state(True, [])[0] == "incomplete"

    def test_a_run_with_papers_left_and_nothing_working_on_them_is_incomplete(self):
        assert jobs.run_state(5, []) == ("incomplete", None)
        assert jobs.run_state(0, []) == ("completed", None)
        assert jobs.run_state(0, [self.job("run_score", "incomplete")]) == ("completed", None)
        assert jobs.run_state(5, [self.job("run_score", "completed")]) == ("incomplete", None)


class TestJobRoutes:
    def test_the_list_holds_what_is_waiting_or_running_and_what_just_ended(self, client, scoring):
        _, _, run_id = make_run()
        queue(client, "run_score", run_id=run_id)
        body = client.get("/api/jobs").get_json()
        assert [j["status"] for j in body["jobs"]] == ["queued"]
        assert "params" not in body["jobs"][0]
        jobs.drain()
        assert [j["status"] for j in client.get("/api/jobs").get_json()["jobs"]] == ["completed"]

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"kind": "nope"},
            {"kind": "run_score"},
            {"kind": "run_score", "run_id": "x"},
            {"kind": "run_score", "run_id": True},
            {"kind": "find_abstracts", "dataset_id": -1},
            {"kind": "dataset_search"},
            {"kind": "dataset_search", "question": "x" * 5000},
            {"kind": "dataset_search", "question": "ok", "sources": "openalex"},
        ],
    )
    def test_a_bad_request_is_refused(self, client, body):
        assert client.post("/api/jobs", json=body).status_code == 400

    def test_work_on_something_that_does_not_exist_is_a_404(self, client):
        assert client.post("/api/jobs", json={"kind": "run_score", "run_id": 999}).status_code == 404
        assert client.post("/api/jobs", json={"kind": "find_abstracts", "dataset_id": 999}).status_code == 404

    def test_the_lanes_start_once_and_stop(self):
        jobs.start()
        try:
            assert jobs.running()
            jobs.start()
            assert len(jobs._threads) == 2
        finally:
            jobs.stop()
        assert not jobs.running()
