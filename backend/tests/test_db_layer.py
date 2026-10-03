"""Phase 2 of the data layer: one-time init, pragmas, indexes, title keys, batch
inserts and the upgrade of databases made by older versions."""

import sqlite3
import threading
import time
from contextlib import closing

import pytest

import db
import source_http
from title_match import title_key


def paper(paper_id, title="Coral growth modeling", doi=None, year=2020, source="openalex"):
    return {"id": paper_id, "source": source, "title": title, "doi": doi, "year": year, "abstract": "", "authors": []}


class TestTitleKey:
    def test_markup_case_accents_and_punctuation_are_ignored(self):
        assert title_key("Coral <i>growth</i> modeling.") == title_key("coral GROWTH  modeling") == "coral growth modeling"
        assert title_key("Café: a study") == title_key("Cafe - a study")

    def test_subscript_tags_join_like_plain_text(self):
        assert title_key("H<sub>2</sub>O splitting") == title_key("H2O splitting")

    def test_blank_or_symbol_only_titles_have_no_key(self):
        assert title_key(None) == title_key("") == title_key("?!") == ""

    def test_a_bare_less_than_is_not_markup(self):
        title = "Effect of x<5 and y>3 on yield"
        assert source_http.clean_title(title) == title
        assert title_key(title) != title_key("Effect of x<7 and y>3 on yield")

    def test_a_less_than_before_a_tag_letter_is_not_markup(self):
        for title in ("a<b and c>d", "Is x<i and y>j ok", "if p<q then r>s"):
            assert source_http.clean_title(title) == title

    def test_real_markup_is_still_removed(self):
        assert source_http.clean_title("<i>Foo</i> H<sub>2</sub>O<br/>x") == "Foo H2Ox"
        assert source_http.clean_title("<mml:math xmlns:mml='u'>x</mml:math> y") == "x y"

    def test_symbols_that_distinguish_titles_are_kept(self):
        assert title_key("Na+ channels") != title_key("Na channels")
        assert title_key("C++ and C#") != title_key("C and C")

    def test_clean_title_keeps_a_leading_abstract_word(self):
        assert source_http.clean_title("Abstract algebra for <i>engineers</i>") == "Abstract algebra for engineers"


def test_newer_data_message_does_not_blame_the_folder(capsys):
    import app

    assert app._data_folder_problem("/data", db.DatabaseTooNew("made by a newer version")) == 1
    err = capsys.readouterr().err
    assert "newer version" in err and "written to" not in err
    app._data_folder_problem("/data", OSError("disk full"))
    assert "written to" in capsys.readouterr().err


class TestReadyOnce:
    def test_schema_and_migration_run_once_for_many_connections(self, monkeypatch):
        calls = []
        real = db._migrate
        monkeypatch.setattr(db, "_migrate", lambda conn: (calls.append(1), real(conn)))
        for _ in range(100):
            db._connect().close()
        assert len(calls) == 1

    def test_a_new_database_path_is_set_up_again(self, tmp_path, monkeypatch):
        db._connect().close()
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "other" / "lit_review.db")
        with closing(db._connect()) as conn:
            assert conn.execute("SELECT COUNT(*) FROM paper").fetchone()[0] == 0

    def test_connections_enforce_foreign_keys_and_use_wal(self):
        with closing(db._connect()) as conn:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO dataset_paper (dataset_id, paper_id, added_at) VALUES (99, 99, 'x')")

    def test_indexes_exist(self):
        with closing(db._connect()) as conn:
            names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert {"idx_paper_doi", "idx_paper_title_key", "idx_dataset_paper_paper", "idx_llm_call_run"} <= names

    def test_threads_starting_on_a_fresh_database_do_not_fail(self):
        errors = []

        def work():
            try:
                db.list_datasets()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


class TestBatchInsert:
    def test_ids_come_back_in_input_order_with_duplicates_merged(self):
        results = [paper("W1", title="One"), paper("W2", title="Two"), paper("W3", title="One.")]
        ids = db.get_or_create_papers(results)
        assert ids[0] == ids[2] != ids[1]

    def test_matches_the_one_by_one_path(self):
        results = [paper(f"W{i}", title=f"Paper number {i}") for i in range(50)]
        assert db.get_or_create_papers(results) == [db.get_or_create_paper(r) for r in results]

    def test_a_failure_part_way_saves_nothing(self):
        with pytest.raises(KeyError):
            db.get_or_create_papers([paper("W1"), {"title": "No id"}])
        with closing(db._connect()) as conn:
            assert conn.execute("SELECT COUNT(*) FROM paper").fetchone()[0] == 0

    def test_a_thousand_papers_are_fast(self):
        results = [paper(f"W{i}", title=f"Distinct title {i}", year=2000 + i % 20) for i in range(1000)]
        start = time.monotonic()
        ids = db.get_or_create_papers(results)
        assert len(set(ids)) == 1000
        assert time.monotonic() - start < 5

    def test_papers_without_a_usable_title_are_never_merged(self):
        a, b = db.get_or_create_papers([paper("W1", title=""), paper("W2", title="")])
        assert a != b

    def test_editing_a_title_updates_its_key(self):
        paper_id = db.get_or_create_paper(paper("W1", title="Old name"))
        db.update_paper(paper_id, {"title": "New <i>name</i>."})
        assert db.get_or_create_paper(paper("W2", title="new name")) == paper_id


# The shapes older versions of the app left on disk, frozen here so a later change to
# db._SCHEMA cannot quietly change what the upgrade is tested against.
OLDEST_SCHEMA = """
CREATE TABLE paper (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, source_id TEXT NOT NULL,
    doi TEXT, title TEXT, abstract TEXT, year INTEGER, citation_count INTEGER, venue TEXT,
    authors TEXT NOT NULL, url TEXT, is_review INTEGER NOT NULL, first_seen_at TEXT NOT NULL,
    UNIQUE (source, source_id));
CREATE TABLE dataset (id INTEGER PRIMARY KEY AUTOINCREMENT, verbose_query TEXT NOT NULL, from_year INTEGER,
    to_year INTEGER, expanded_queries TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE dataset_paper (dataset_id INTEGER NOT NULL REFERENCES dataset(id),
    paper_id INTEGER NOT NULL REFERENCES paper(id), added_at TEXT NOT NULL, excluded_at TEXT,
    PRIMARY KEY (dataset_id, paper_id));
CREATE TABLE analysis_run (id INTEGER PRIMARY KEY AUTOINCREMENT, grading_prompt TEXT NOT NULL,
    ai_api TEXT NOT NULL, ai_model TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
    completed_at TEXT);
CREATE TABLE analysis_run_dataset (run_id INTEGER NOT NULL REFERENCES analysis_run(id),
    dataset_id INTEGER NOT NULL REFERENCES dataset(id), PRIMARY KEY (run_id, dataset_id));
CREATE TABLE analysis_result (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES analysis_run(id),
    paper_id INTEGER NOT NULL REFERENCES paper(id), rationale TEXT, score INTEGER, created_at TEXT NOT NULL,
    UNIQUE (run_id, paper_id));
CREATE TABLE llm_call (id INTEGER PRIMARY KEY AUTOINCREMENT, purpose TEXT NOT NULL,
    dataset_id INTEGER REFERENCES dataset(id), run_id INTEGER REFERENCES analysis_run(id),
    ai_api TEXT NOT NULL, ai_model TEXT NOT NULL, input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL, usd REAL NOT NULL, created_at TEXT NOT NULL);
"""

OLD_DATA = """
INSERT INTO paper (source, source_id, doi, title, abstract, year, citation_count, authors, is_review, first_seen_at)
VALUES ('openalex', 'W1', 'https://doi.org/10.1/a', 'Coral <i>growth</i> modeling.', 'abs', 2020, 3, '[]', 0, 't'),
       ('openalex', 'W2', NULL, 'Carbon storage', '', 2021, 0, '[]', 0, 't'),
       ('openalex', 'W3', NULL, NULL, '', NULL, 0, '[]', 0, 't');
INSERT INTO dataset (verbose_query, from_year, to_year, expanded_queries, created_at)
VALUES ('coral reef monitoring', 2019, 2022, '["coral"]', 't');
INSERT INTO dataset_paper (dataset_id, paper_id, added_at) VALUES (1, 1, 't'), (1, 2, 't');
INSERT INTO analysis_run (grading_prompt, ai_api, ai_model, status, created_at)
VALUES ('Find coral control papers', 'anthropic', 'm', 'completed', 't');
INSERT INTO analysis_run_dataset VALUES (1, 1);
INSERT INTO analysis_result (run_id, paper_id, rationale, score, created_at) VALUES (1, 1, 'good', 80, 't');
INSERT INTO llm_call (purpose, dataset_id, ai_api, ai_model, input_tokens, output_tokens, usd, created_at)
VALUES ('query_expansion', 1, 'anthropic', 'm', 10, 5, 0.01, 't');
"""

TABLES = ("paper", "dataset", "dataset_paper", "analysis_run", "analysis_run_dataset", "analysis_result", "llm_call")


def write_old_database(path, schema, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(schema)
    conn.executescript(data)
    conn.commit()
    conn.close()


def counts(path):
    conn = sqlite3.connect(str(path))
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        conn.close()


class TestUpgrade:
    def upgrade(self, schema=OLDEST_SCHEMA, data=OLD_DATA):
        write_old_database(db.DB_PATH, schema, data)
        before = counts(db.DB_PATH)
        db.ensure_ready()
        return before

    def test_every_row_survives_and_the_new_pieces_appear(self):
        before = self.upgrade()
        assert counts(db.DB_PATH) == before
        with closing(db._connect()) as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(paper)")}
            assert {"publication_date", "read_at", "title_key"} <= columns
            keys = {row["source_id"]: row["title_key"] for row in conn.execute("SELECT source_id, title_key FROM paper")}
            assert keys == {"W1": "coral growth modeling", "W2": "carbon storage", "W3": ""}
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
            names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
            assert "idx_paper_title_key" in names

    def test_a_copy_of_the_old_database_is_kept_untouched(self):
        self.upgrade()
        copy = db.DB_PATH.with_name(f"{db.DB_PATH.name}.pre-upgrade-0-to-{db.SCHEMA_VERSION}")
        assert copy.exists()
        conn = sqlite3.connect(str(copy))
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
            assert "title_key" not in {row[1] for row in conn.execute("PRAGMA table_info(paper)")}
            assert conn.execute("SELECT COUNT(*) FROM paper").fetchone()[0] == 3
        finally:
            conn.close()

    def test_no_copy_for_a_new_database_or_an_up_to_date_one(self):
        db.ensure_ready()
        assert list(db.DB_PATH.parent.glob("*.pre-upgrade-*")) == []
        db._ready_for = None
        db.ensure_ready()
        assert list(db.DB_PATH.parent.glob("*.pre-upgrade-*")) == []

    def test_a_paper_without_a_doi_matches_an_upgraded_row_by_its_new_key(self):
        self.upgrade()
        assert db.get_or_create_paper(paper("1", title="Carbon storage.", year=2021, source="pubmed")) == 2

    def test_the_upgrade_can_be_repeated(self):
        before = self.upgrade()
        db._ready_for = None
        db.ensure_ready()
        assert counts(db.DB_PATH) == before

    def test_a_database_from_a_newer_version_is_not_opened(self):
        db.ensure_ready()
        conn = sqlite3.connect(str(db.DB_PATH))
        conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
        conn.close()
        db._ready_for = None
        with pytest.raises(db.DatabaseTooNew):
            db.ensure_ready()

    def test_a_database_with_orphan_rows_still_opens(self):
        orphan = OLD_DATA + "INSERT INTO dataset_paper (dataset_id, paper_id, added_at) VALUES (1, 999, 't');"
        before = self.upgrade(data=orphan)
        assert counts(db.DB_PATH) == before
