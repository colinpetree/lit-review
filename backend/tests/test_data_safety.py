"""Backing up, restoring a backup, and the trash. Everything here runs against the temp data
folder the conftest sets up, never the real one."""

import sqlite3
import threading
from contextlib import closing

import pytest

import app as app_module
import credentials
import db
import llm
from test_db_layer import OLD_DATA, OLDEST_SCHEMA, write_old_database

ABSTRACT = "This study measures the effect of coral growth on reef output in field conditions. " * 2
USAGE = llm.Usage(1000, 500, model="claude-haiku-4-5", provider="anthropic")


def paper(i):
    return {"id": f"W{i}", "title": f"Paper {i}", "abstract": ABSTRACT, "year": 2020, "authors": [], "citation_count": 0, "source": "openalex"}


def make_dataset(papers=(1, 2), name="Dataset"):
    return db.save_retrieved_dataset("coral", ["coral reef"], [paper(i) for i in papers], USAGE, name=name)


def paper_id_of(source_id):
    with closing(db._connect()) as conn:
        row = conn.execute("SELECT id FROM paper WHERE source_id = ?", (source_id,)).fetchone()
        return row[0] if row else None


def scalar(sql, *params):
    with closing(db._connect()) as conn:
        return conn.execute(sql, params).fetchone()[0]


def counts():
    tables = ("paper", "dataset", "dataset_paper", "analysis_run", "analysis_result", "prompt", "prompt_example", "llm_call")
    return {t: scalar(f"SELECT COUNT(*) FROM {t}") for t in tables}


def spent():
    return scalar("SELECT COALESCE(SUM(usd), 0) FROM llm_call")


def integrity_ok():
    with closing(db._connect()) as conn:
        checked = [tuple(row) for row in conn.execute("PRAGMA integrity_check")]
        return checked == [("ok",)] and conn.execute("PRAGMA foreign_key_check").fetchall() == []


def populate():
    """A dataset with papers, a prompt with an example, and a run with results and spending."""
    dataset_id = make_dataset((1, 2, 3))
    prompt_id = db.create_prompt("Coral prompt", "find coral papers")
    run_id = db.create_analysis_run([dataset_id], "find coral papers", "anthropic", "claude-haiku-4-5", prompt_id)
    ids = [paper_id_of(f"W{i}") for i in (1, 2, 3)]
    db.record_analysis_chunk(run_id, {i: {"score": 70, "rationale": "r"} for i in ids}, USAGE)
    db.add_prompt_example(prompt_id, ids[0], run_id, 70, "r")
    return {"dataset": dataset_id, "prompt": prompt_id, "run": run_id, "papers": ids}


@pytest.fixture
def stranger(client):
    """A browser that was never connected: the right address, no secret."""
    browser = app_module.app.test_client()
    browser.environ_base.pop("HTTP_AUTHORIZATION", None)
    return browser


def backup_bytes(client):
    response = client.get("/api/data/backup")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.data


def restore(client, data, **kwargs):
    return client.post("/api/data/restore", data=data, content_type="application/octet-stream", **kwargs)


class TestBackup:
    def test_it_downloads_a_whole_database_with_a_dated_name(self, client):
        populate()
        response = client.get("/api/data/backup")
        assert response.status_code == 200
        assert response.headers["Content-Disposition"].startswith('attachment; filename="lit-review-backup-')
        assert response.headers["Content-Disposition"].endswith('.db"')
        assert int(response.headers["Content-Length"]) == len(response.data)
        path = db.DB_PATH.parent / "downloaded.db"
        path.write_bytes(response.data)
        with closing(sqlite3.connect(path)) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            assert conn.execute("SELECT COUNT(*) FROM paper").fetchone()[0] == 3
            assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        db.validate_backup_file(path)

    def test_no_temporary_folder_is_left_behind(self, client):
        populate()
        backup_bytes(client)
        assert [p.name for p in db.DB_PATH.parent.iterdir() if p.name.startswith("backup-")] == []

    def test_the_api_keys_are_not_in_it(self, client):
        populate()
        credentials.set_key("anthropic", "sk-ant-SECRET-KEY-VALUE")
        assert b"SECRET-KEY-VALUE" not in backup_bytes(client)

    def test_an_unconnected_browser_cannot_download_it(self, stranger):
        populate()
        assert stranger.get("/api/data/backup").status_code == 401


class TestRestore:
    def test_a_backup_restores_what_was_there_and_keeps_what_was_replaced(self, client):
        populate()
        backup = backup_bytes(client)
        before = counts()
        before_spent = spent()
        # Changes made after the backup, which the restore should discard.
        make_dataset((7, 8), name="Later")
        db.delete_analysis_run(scalar("SELECT id FROM analysis_run LIMIT 1"))
        assert counts() != before

        response = restore(client, backup)
        assert response.status_code == 200, response.get_data(as_text=True)
        body = response.get_json()
        assert body["ok"] is True and "before-restore" in body["safety_copy"]
        assert counts() == before
        assert spent() == pytest.approx(before_spent)
        assert integrity_ok()

        # What was replaced is kept whole, so the restore can be undone.
        safety = db.DB_PATH.with_name(body["safety_copy"])
        assert safety.exists()
        with closing(sqlite3.connect(safety)) as conn:
            assert conn.execute("SELECT COUNT(*) FROM dataset").fetchone()[0] == 2  # the original and "Later"

    def test_the_app_keeps_working_after_a_restore(self, client):
        populate()
        backup = backup_bytes(client)
        make_dataset((9,), name="Extra")
        assert restore(client, backup).status_code == 200
        names = [d["name"] for d in client.get("/api/datasets").get_json()["datasets"]]
        assert names == ["Dataset"]
        assert make_dataset((20,), name="New") > 0
        assert client.get("/api/health").status_code == 200

    def test_the_old_data_is_never_changed_by_a_refused_upload(self, client):
        populate()
        before = counts()
        for bad in (b"not a database at all", b"", b"SQLite format 3\x00" + b"\x00" * 100):
            response = restore(client, bad)
            assert response.status_code == 400, bad
            assert response.get_json()["error"]
        assert counts() == before and integrity_ok()
        assert [p.name for p in db.DB_PATH.parent.iterdir() if "before-restore" in p.name] == []
        assert [p.name for p in db.DB_PATH.parent.iterdir() if p.name.startswith("restore-")] == []

    def test_a_database_that_is_not_this_apps_is_refused(self, client, tmp_path):
        populate()
        other = tmp_path / "other.db"
        with closing(sqlite3.connect(other)) as conn:
            conn.execute("CREATE TABLE notes (id INTEGER)")
            conn.commit()
        response = restore(client, other.read_bytes())
        assert response.status_code == 400 and "not a Lit Review backup" in response.get_json()["error"]

    def test_a_damaged_backup_is_refused(self, client):
        populate()
        backup = bytearray(backup_bytes(client))
        before = counts()
        for offset in range(4096, len(backup) - 8, 4096):  # overwrite whole pages after the first
            backup[offset : offset + 64] = b"\xff" * 64
        response = restore(client, bytes(backup))
        assert response.status_code == 400
        assert counts() == before and integrity_ok()

    def test_a_backup_from_a_newer_version_is_refused(self, client, tmp_path):
        populate()
        backup = tmp_path / "newer.db"
        backup.write_bytes(backup_bytes(client))
        with closing(sqlite3.connect(backup)) as conn:
            conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
            conn.commit()
        response = restore(client, backup.read_bytes())
        assert response.status_code == 400 and "newer version" in response.get_json()["error"]

    def test_an_older_backup_is_upgraded(self, client, tmp_path):
        populate()
        old = tmp_path / "old.db"
        old.write_bytes(backup_bytes(client))
        with closing(sqlite3.connect(old)) as conn:
            conn.execute("PRAGMA user_version = 3")
            conn.commit()
        assert restore(client, old.read_bytes()).status_code == 200
        assert scalar("PRAGMA user_version") == db.SCHEMA_VERSION
        assert db.DB_PATH.with_name(f"{db.DB_PATH.name}.pre-upgrade-3-to-{db.SCHEMA_VERSION}").exists()
        assert counts()["paper"] == 3 and integrity_ok()

    def test_a_database_from_the_oldest_version_restores_and_is_upgraded(self, client, tmp_path):
        """What the app itself keeps as lit_review.db.pre-upgrade-*: no prompts, no dates, no
        deleted_at. A user may well restore one of those."""
        populate()
        old = tmp_path / "oldest.db"
        write_old_database(old, OLDEST_SCHEMA, OLD_DATA)
        response = restore(client, old.read_bytes())
        assert response.status_code == 200, response.get_data(as_text=True)
        assert counts()["paper"] == 3 and counts()["dataset"] == 1 and counts()["analysis_result"] == 1
        assert scalar("PRAGMA user_version") == db.SCHEMA_VERSION
        assert db.DB_PATH.with_name(f"{db.DB_PATH.name}.pre-upgrade-0-to-{db.SCHEMA_VERSION}").exists()
        assert integrity_ok()
        # And it behaves like any other data: the legacy run now has a prompt and a name.
        run = client.get("/api/analysis-runs").get_json()["runs"][0]
        assert run["name"] and client.get(f"/api/analysis-runs/{run['id']}").status_code == 200

    def test_it_needs_a_body_and_has_a_ceiling(self, client, monkeypatch):
        assert client.post("/api/data/restore").status_code == 400
        monkeypatch.setattr(app_module, "MAX_RESTORE_BYTES", 10)
        response = restore(client, b"x" * 11)
        assert response.status_code == 413 and "too large" in response.get_json()["error"]

    def test_a_body_larger_than_ordinary_requests_is_accepted(self, client):
        """The 1 MB limit on other requests does not apply: a real backup is much bigger."""
        populate()
        with closing(db._connect()) as conn:
            conn.execute("CREATE TABLE padding (data BLOB)")
            conn.execute("INSERT INTO padding VALUES (?)", (b"\x00" * (3 * 1024 * 1024),))
            conn.commit()
        big = backup_bytes(client)
        assert len(big) > app_module.MAX_REQUEST_BYTES
        assert restore(client, big).status_code == 200

    def test_an_unconnected_browser_cannot_restore(self, stranger):
        assert stranger.post("/api/data/restore", data=b"x", content_type="application/octet-stream").status_code == 401

    def test_a_foreign_website_cannot_restore(self, client):
        response = restore(client, b"x", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403

    def test_a_full_disk_while_saving_the_upload_changes_nothing_and_says_so(self, client, monkeypatch):
        populate()
        backup = backup_bytes(client)
        before = counts()

        class FullDisk:
            def __init__(self, descriptor):
                import os

                os.close(descriptor)

            def write(self, data):
                raise OSError(28, "No space left on device")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(app_module.os, "fdopen", lambda descriptor, mode: FullDisk(descriptor))
        response = restore(client, backup)
        assert response.status_code == 500 and "disk full" in response.get_json()["error"]
        assert counts() == before and integrity_ok()
        assert [p.name for p in db.DB_PATH.parent.iterdir() if p.name.startswith("restore-")] == []
        assert not app_module._GATE.closed

    def test_a_second_restore_at_the_same_time_is_refused(self, client):
        populate()
        backup = backup_bytes(client)
        with app_module._exclusive("restore", 0) as acquired:
            assert acquired
            assert restore(client, backup).status_code == 409
        assert restore(client, backup).status_code == 200

    def test_if_the_backup_cannot_be_opened_the_previous_data_is_put_back(self, client, monkeypatch):
        populate()
        backup = backup_bytes(client)
        make_dataset((50,), name="Kept")
        before = counts()
        real_migrate = db._migrate
        calls = []

        def failing_once(conn):
            calls.append(1)
            if len(calls) == 1:
                raise sqlite3.OperationalError("simulated failure while upgrading")
            return real_migrate(conn)

        monkeypatch.setattr(db, "_migrate", failing_once)
        response = restore(client, backup)
        assert response.status_code == 500
        assert "previous data was put back" in response.get_json()["error"]
        assert counts() == before and integrity_ok()
        assert client.get("/api/datasets").status_code == 200  # and the gate is open again

    def test_requests_during_the_swap_are_turned_away_and_the_gate_reopens(self, client, monkeypatch):
        populate()
        backup = backup_bytes(client)
        seen = {}
        real = db.replace_with_backup

        def swap_while_another_request_arrives(upload):
            def other():
                seen["status"] = app_module.app.test_client().get("/api/datasets").status_code

            thread = threading.Thread(target=other)
            thread.start()
            thread.join(10)
            return real(upload)

        monkeypatch.setattr(db, "replace_with_backup", swap_while_another_request_arrives)
        assert restore(client, backup).status_code == 200
        assert seen["status"] == 503
        assert client.get("/api/datasets").status_code == 200
        assert not app_module._GATE.closed


class TestRestoreWaitsForRunningWork:
    @pytest.fixture
    def slow_model(self, fake_llm):
        fake_llm.started = threading.Event()
        fake_llm.release = threading.Event()

        def respond(system, user, schema):
            import re

            fake_llm.started.set()
            assert fake_llm.release.wait(10), "the test never released the model call"
            ids = re.findall(r'<paper id="(\d+)">', user)
            return {"scores": [{"id": i, "comparison": "Compared.", "bracket": "strong", "score": 70} for i in ids]}

        fake_llm.respond = respond
        yield fake_llm
        fake_llm.release.set()

    def test_a_restore_does_not_swap_the_file_under_a_scoring_request(self, client, slow_model, monkeypatch):
        data = populate()
        run_id = db.create_analysis_run([data["dataset"]], "g", "anthropic", "claude-haiku-4-5")
        backup = backup_bytes(client)
        make_dataset((60,), name="After")
        before = counts()
        monkeypatch.setattr(app_module, "RESTORE_WAIT_SECONDS", 0.3)

        out = {}

        def score():
            out["response"] = app_module.app.test_client().post(f"/api/analysis-runs/{run_id}/process")

        thread = threading.Thread(target=score)
        thread.start()
        assert slow_model.started.wait(5)

        refused = restore(client, backup)
        assert refused.status_code == 409 and "still running" in refused.get_json()["error"]
        assert counts() == before  # nothing was swapped
        assert not app_module._GATE.closed  # and requests are accepted again

        slow_model.release.set()
        thread.join(10)
        assert out["response"].status_code == 200
        assert restore(client, backup).status_code == 200
        assert integrity_ok()


class TestTrashList:
    def test_it_lists_deleted_datasets_and_prompts(self, client):
        data = populate()
        db.delete_analysis_run(data["run"])
        db.delete_dataset(data["dataset"])
        db.delete_prompt(data["prompt"])
        trash = client.get("/api/trash").get_json()
        assert [d["name"] for d in trash["datasets"]] == ["Dataset"]
        assert trash["datasets"][0]["paper_count"] == 3
        assert [p["name"] for p in trash["prompts"]] == ["Coral prompt"]
        assert trash["prompts"][0]["example_count"] == 1
        assert trash["runs"] == []

    def test_live_things_are_not_in_it(self, client):
        populate()
        trash = client.get("/api/trash").get_json()
        assert trash == {"datasets": [], "prompts": [], "runs": []}


def trash_dataset(papers=(1, 2), name="Dataset"):
    dataset_id = make_dataset(papers, name=name)
    db.delete_dataset(dataset_id)
    return dataset_id


class TestRestoreFromTrash:
    def test_a_dataset_and_a_prompt_come_back(self, client):
        dataset_id = trash_dataset()
        prompt_id = db.create_prompt("P", "d")
        db.delete_prompt(prompt_id)
        assert client.post(f"/api/trash/dataset/{dataset_id}/restore").status_code == 200
        assert client.post(f"/api/trash/prompt/{prompt_id}/restore").status_code == 200
        assert [d["id"] for d in client.get("/api/datasets").get_json()["datasets"]] == [dataset_id]
        assert [p["id"] for p in client.get("/api/prompts").get_json()["prompts"]] == [prompt_id]
        assert client.get("/api/trash").get_json() == {"datasets": [], "prompts": [], "runs": []}

    def test_a_run_deleted_by_an_older_version_gets_a_free_name_back(self, client):
        data = populate()
        with closing(db._connect()) as conn:
            conn.execute("UPDATE analysis_run SET deleted_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (data["run"],))
            conn.commit()
        taken = db.create_analysis_run([data["dataset"]], "g", "anthropic", "claude-haiku-4-5", data["prompt"])
        name_in_use = db.get_analysis_run(taken)["name"]
        with closing(db._connect()) as conn:
            conn.execute("UPDATE analysis_run SET name = ? WHERE id = ?", (name_in_use, data["run"]))
            conn.commit()
        response = client.post(f"/api/trash/run/{data['run']}/restore")
        assert response.status_code == 200
        assert response.get_json()["name"] == f"{name_in_use} (2)"
        assert db.get_analysis_run(data["run"])["name"] == f"{name_in_use} (2)"

    def test_something_not_in_the_trash_is_a_404_and_stays_as_it_is(self, client):
        dataset_id = make_dataset()
        assert client.post(f"/api/trash/dataset/{dataset_id}/restore").status_code == 404
        assert client.post("/api/trash/dataset/999/restore").status_code == 404

    @pytest.mark.parametrize("path", ["/api/trash/nothing/1/restore", f"/api/trash/dataset/{2**63}/restore"])
    def test_an_unknown_kind_or_an_id_the_database_cannot_hold_is_a_404(self, client, path):
        assert client.post(path).status_code == 404


class TestPurge:
    def test_a_dataset_goes_with_its_own_papers_but_not_the_ones_others_use(self, client):
        shared = make_dataset((1, 2), name="Keeper")
        gone = trash_dataset((2, 3, 4), name="Gone")
        paper_in_example = paper_id_of("W4")
        prompt_id = db.create_prompt("P", "d")
        db.add_prompt_example(prompt_id, paper_in_example, None, 80, "r")
        response = client.delete(f"/api/trash/dataset/{gone}")
        assert response.status_code == 200
        assert response.get_json()["papers_removed"] == 1  # only W3: W2 is in Keeper, W4 is an example
        assert paper_id_of("W3") is None
        assert paper_id_of("W2") is not None and paper_id_of("W4") is not None
        assert scalar("SELECT COUNT(*) FROM dataset WHERE id = ?", gone) == 0
        assert [p["title"] for p in db.get_dataset_papers(shared)] != []
        assert integrity_ok()

    def test_what_was_spent_stays_counted(self, client):
        before_spent = None
        gone = trash_dataset()
        before_spent = spent()
        assert before_spent > 0  # the dataset's query expansion
        assert client.delete(f"/api/trash/dataset/{gone}").status_code == 200
        assert spent() == pytest.approx(before_spent)
        assert scalar("SELECT COUNT(*) FROM llm_call WHERE dataset_id = ?", gone) == 0

    def test_a_dataset_a_run_still_uses_is_refused_and_left_alone(self, client):
        data = populate()
        db.delete_dataset(data["dataset"])
        before = counts()
        response = client.delete(f"/api/trash/dataset/{data['dataset']}")
        assert response.status_code == 409
        assert "result run still uses this dataset" in response.get_json()["error"]
        assert counts() == before
        assert len(client.get("/api/trash").get_json()["datasets"]) == 1

    def test_the_refusal_says_run_or_runs_to_match_how_many_use_it(self, client):
        data = populate()
        db.delete_prompt(data["prompt"])
        one = client.delete(f"/api/trash/prompt/{data['prompt']}").get_json()["error"]
        assert one == "1 result run still uses this prompt. Delete that run first."
        db.create_analysis_run([data["dataset"]], "g", "anthropic", "claude-haiku-4-5", data["prompt"])
        db.create_analysis_run([data["dataset"]], "g", "anthropic", "claude-haiku-4-5", data["prompt"])
        many = client.delete(f"/api/trash/prompt/{data['prompt']}").get_json()["error"]
        assert many == "3 result runs still use this prompt. Delete those runs first."

    def test_a_prompt_goes_with_its_examples_and_is_refused_while_a_run_uses_it(self, client):
        data = populate()
        db.delete_prompt(data["prompt"])
        assert client.delete(f"/api/trash/prompt/{data['prompt']}").status_code == 409
        db.delete_analysis_run(data["run"])
        response = client.delete(f"/api/trash/prompt/{data['prompt']}")
        assert response.status_code == 200
        assert scalar("SELECT COUNT(*) FROM prompt_example") == 0
        assert scalar("SELECT COUNT(*) FROM paper") == 3  # still in the live dataset
        assert integrity_ok()

    def test_a_run_deleted_by_an_older_version_goes_and_its_spending_stays(self, client):
        data = populate()
        with closing(db._connect()) as conn:
            conn.execute("UPDATE analysis_run SET deleted_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (data["run"],))
            conn.commit()
        before_spent = spent()
        assert client.delete(f"/api/trash/run/{data['run']}").status_code == 200
        assert scalar("SELECT COUNT(*) FROM analysis_run") == 0 and scalar("SELECT COUNT(*) FROM analysis_result") == 0
        assert scalar("SELECT source_run_id FROM prompt_example") is None
        assert spent() == pytest.approx(before_spent)
        assert integrity_ok()

    def test_only_what_is_in_the_trash_can_be_purged(self, client):
        data = populate()
        before = counts()
        for kind, item in (("dataset", data["dataset"]), ("prompt", data["prompt"]), ("run", data["run"])):
            assert client.delete(f"/api/trash/{kind}/{item}").status_code == 404
        assert counts() == before

    def test_unknown_kinds_are_a_404(self, client):
        assert client.delete("/api/trash/paper/1").status_code == 404


class TestEmptyTrash:
    def test_it_removes_what_can_go_and_says_what_could_not(self, client):
        data = populate()
        db.delete_dataset(data["dataset"])  # still used by the live run: stays
        free = trash_dataset((10, 11), name="Free")
        prompt = db.create_prompt("Old", "d")
        db.delete_prompt(prompt)
        response = client.delete("/api/trash")
        assert response.status_code == 200
        body = response.get_json()
        assert body["purged"] == {"run": 0, "dataset": 1, "prompt": 1}
        assert body["papers_removed"] == 2
        assert [s["id"] for s in body["skipped"]] == [data["dataset"]]
        assert "still uses" in body["skipped"][0]["reason"]
        assert scalar("SELECT COUNT(*) FROM dataset WHERE id = ?", free) == 0
        assert integrity_ok()

    def test_runs_go_first_so_what_they_used_is_free(self, client):
        data = populate()
        with closing(db._connect()) as conn:
            conn.execute("UPDATE analysis_run SET deleted_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (data["run"],))
            conn.commit()
        db.delete_dataset(data["dataset"])
        db.delete_prompt(data["prompt"])
        body = client.delete("/api/trash").get_json()
        assert body["purged"] == {"run": 1, "dataset": 1, "prompt": 1} and body["skipped"] == []
        assert counts()["paper"] == 0 and counts()["dataset"] == 0
        assert integrity_ok()

    def test_an_empty_trash_is_fine(self, client):
        assert client.delete("/api/trash").get_json() == {"purged": {"run": 0, "dataset": 0, "prompt": 0}, "papers_removed": 0, "skipped": []}
