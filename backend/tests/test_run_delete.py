"""Deleting a run removes it for good, and keeps what other things still need."""

from contextlib import closing

import db
import llm
from tests.test_run_processing import make_run


def count(sql, *args):
    with closing(db._connect()) as conn:
        return conn.execute(sql, args).fetchone()[0]


def test_delete_removes_the_run_its_scores_and_dataset_links(client):
    dataset_id, ids, run_id = make_run()
    db.record_analysis_chunk(run_id, {ids[0]: {"score": 80, "rationale": "Good."}}, llm.Usage(1, 1, model="claude-haiku-4-5"))

    assert client.delete(f"/api/analysis-runs/{run_id}").status_code == 200

    assert count("SELECT COUNT(*) FROM analysis_run WHERE id = ?", run_id) == 0
    assert count("SELECT COUNT(*) FROM analysis_result WHERE run_id = ?", run_id) == 0
    assert count("SELECT COUNT(*) FROM analysis_run_dataset WHERE run_id = ?", run_id) == 0
    assert client.get(f"/api/analysis-runs/{run_id}").status_code == 404
    assert client.delete(f"/api/analysis-runs/{run_id}").status_code == 404


def test_delete_leaves_the_dataset_and_papers_alone(client):
    dataset_id, ids, run_id = make_run()
    client.delete(f"/api/analysis-runs/{run_id}")
    assert db.get_dataset(dataset_id) is not None
    assert count("SELECT COUNT(*) FROM paper") == len(ids)


def test_delete_keeps_total_spend_and_prompt_examples(client):
    _, ids, run_id = make_run()
    prompt_id = db.create_prompt("P", "ideal paper")
    db.record_analysis_chunk(run_id, {ids[0]: {"score": 80, "rationale": "Good."}}, llm.Usage(1000, 1000, model="claude-haiku-4-5"))
    db.add_prompt_example(prompt_id, ids[0], run_id, 80, "Good.")
    spent = db.get_cost()
    assert spent > 0

    client.delete(f"/api/analysis-runs/{run_id}")

    assert db.get_cost() == spent
    assert count("SELECT COUNT(*) FROM llm_call WHERE run_id IS NOT NULL") == 0
    examples = db.list_prompt_examples(prompt_id)
    assert len(examples) == 1 and examples[0]["source_run_id"] is None
