"""Checking a dataset again for papers that appeared since it was searched."""

import datetime
from contextlib import closing

import pytest

import app as app_module
import db
import llm
import openalex
import search_sources
from app import InvalidRequest, _refresh_window
from source_http import SourceError

TODAY = datetime.date(2026, 10, 3)


def work(i, **extra):
    return {
        "id": f"W{i}",
        "source": "openalex",
        "title": f"Paper number {i}",
        "year": 2026,
        "publication_date": "2026-09-01",
        "abstract": "",
        "authors": [],
        "citation_count": 0,
        **extra,
    }


def make_dataset(papers=(1, 2), from_date=None, to_date=None, queries=("coral reef",), search_limit=None):
    usage = llm.Usage(10, 5, model="claude-haiku-4-5", provider="anthropic")
    dataset_id = db.save_retrieved_dataset(
        "coral reefs",
        list(queries),
        [work(i) for i in papers],
        usage,
        from_date=from_date,
        to_date=to_date,
        name="Coral",
        search_limit=search_limit,
    )
    return dataset_id


def paper_id_of(source_id):
    with closing(db._connect()) as conn:
        return conn.execute("SELECT id FROM paper WHERE source_id = ?", (source_id,)).fetchone()[0]


class TestWindow:
    def row(self, **changes):
        row = {"from_date": None, "to_date": None, "created_at": "2026-09-20T12:00:00+00:00", "last_refresh": None}
        row.update(changes)
        return row

    def test_the_first_check_goes_back_45_days_before_the_dataset_was_made(self):
        assert _refresh_window(self.row(), TODAY) == ("2026-08-06", None)

    def test_a_later_check_goes_back_from_the_last_check(self):
        row = self.row(last_refresh={"at": "2026-10-01T08:00:00+00:00"})
        assert _refresh_window(row, TODAY) == ("2026-08-17", None)

    def test_the_original_start_date_still_applies_when_it_is_later(self):
        assert _refresh_window(self.row(from_date="2026-09-15"), TODAY)[0] == "2026-09-15"
        assert _refresh_window(self.row(from_date="2020-01-01"), TODAY)[0] == "2026-08-06"

    def test_an_end_date_in_the_future_or_today_is_kept(self):
        assert _refresh_window(self.row(to_date="2026-12-31"), TODAY)[1] == "2026-12-31"
        assert _refresh_window(self.row(to_date="2026-10-03"), TODAY)[1] == "2026-10-03"

    def test_a_search_that_ended_in_the_past_cannot_find_newer_papers(self):
        with pytest.raises(InvalidRequest, match="ends on 2026-06-30, so no newer papers can appear"):
            _refresh_window(self.row(to_date="2026-06-30"), TODAY)


class TestRefreshRoute:
    @pytest.fixture
    def source(self, monkeypatch):
        """OpenAlex that returns what the test sets and records what it was asked."""
        state = {"asked": [], "papers": [], "total": None}

        def search_all(query, from_date=None, to_date=None, max_results=None):
            state["asked"].append((query, from_date, to_date))
            papers = state["papers"]
            return papers, state["total"] if state["total"] is not None else len(papers)

        monkeypatch.setattr(openalex, "search_all", search_all)
        return state

    def refresh(self, client, dataset_id):
        return client.post(f"/api/datasets/{dataset_id}/refresh")

    def test_only_new_papers_are_added_and_marked_new(self, client, source):
        dataset_id = make_dataset(papers=(1, 2))
        source["papers"] = [work(2), work(3)]
        response = self.refresh(client, dataset_id)
        assert response.status_code == 200, response.get_data(as_text=True)
        body = response.get_json()
        assert body["new_count"] == 1
        by_title = {p["title"]: p for p in body["dataset"]["papers"]}
        assert set(by_title) == {"Paper number 1", "Paper number 2", "Paper number 3"}
        assert by_title["Paper number 3"]["is_new"] is True
        assert by_title["Paper number 1"]["is_new"] is False and by_title["Paper number 2"]["is_new"] is False

    def test_it_asks_only_for_the_narrowed_window_with_the_saved_queries_and_costs_nothing(self, client, source):
        dataset_id = make_dataset(queries=("coral reef", "reef fish"))
        cost_before = db.get_cost()
        self.refresh(client, dataset_id)
        today = datetime.date.today()
        created = datetime.date.fromisoformat(db.get_dataset(dataset_id)["created_at"][:10])
        expected_from = (created - datetime.timedelta(days=45)).isoformat()
        # An open end date reaches the source as today (search_sources._filtered).
        end = today.isoformat()
        assert source["asked"] == [("coral reef", expected_from, end), ("reef fish", expected_from, end)]
        assert db.get_cost() == cost_before

    def test_excluded_and_read_papers_are_left_alone(self, client, source):
        dataset_id = make_dataset(papers=(1, 2))
        excluded, read = paper_id_of("W1"), paper_id_of("W2")
        db.set_dataset_paper_excluded(dataset_id, excluded, True)
        db.set_paper_read(read, True)
        source["papers"] = [work(1), work(2), work(3)]
        body = self.refresh(client, dataset_id).get_json()
        by_id = {p["id"]: p for p in body["dataset"]["papers"]}
        assert by_id[excluded]["excluded"] is True and by_id[excluded]["is_new"] is False
        assert by_id[read]["read"] is True and by_id[read]["is_new"] is False
        assert body["new_count"] == 1

    def test_the_check_is_recorded_and_only_the_latest_batch_is_new(self, client, source):
        dataset_id = make_dataset(papers=(1,))
        source["papers"] = [work(2)]
        first = self.refresh(client, dataset_id).get_json()["dataset"]
        assert first["last_refresh"]["new_count"] == 1
        assert first["last_refresh"]["retrieval"][0]["query"] == "coral reef"
        source["papers"] = [work(2), work(3)]
        second = self.refresh(client, dataset_id).get_json()["dataset"]
        new = [p["title"] for p in second["papers"] if p["is_new"]]
        assert new == ["Paper number 3"]
        assert second["last_refresh"]["at"] != first["last_refresh"]["at"]

    def test_a_check_with_nothing_new_still_records_it(self, client, source):
        dataset_id = make_dataset(papers=(1,))
        source["papers"] = [work(1)]
        body = self.refresh(client, dataset_id).get_json()
        assert body["new_count"] == 0
        assert body["dataset"]["last_refresh"]["new_count"] == 0
        assert not any(p["is_new"] for p in body["dataset"]["papers"])

    def test_a_check_that_hit_the_limit_says_so(self, client, source):
        dataset_id = make_dataset(papers=(1,))
        limit = search_sources.REFRESH_SEARCH_LIMIT
        source["papers"], source["total"] = [work(i) for i in range(100, 100 + limit)], limit * 4
        refresh = self.refresh(client, dataset_id).get_json()["dataset"]["last_refresh"]
        assert f"{limit:,} most relevant were kept" in refresh["retrieval"][0]["capped"]
        assert refresh["retrieval"][0]["capped_by"] == "limit"

    def test_the_check_reads_deeper_than_the_datasets_own_limit(self, client, monkeypatch):
        asked = []

        def search_all(query, **kwargs):
            asked.append(kwargs["max_results"])
            return [], 0

        monkeypatch.setattr(openalex, "search_all", search_all)
        for limit in (50, 200, None):
            self.refresh(client, make_dataset(search_limit=limit, queries=(f"q{limit}",)))
        # Known papers would otherwise use up a small limit and push new ones out.
        assert asked == [search_sources.REFRESH_SEARCH_LIMIT] * 3

    def test_known_papers_do_not_use_up_the_limit_that_new_ones_need(self, client, source):
        dataset_id = make_dataset(papers=tuple(range(1, 61)), search_limit=50)
        source["papers"] = [work(i) for i in range(1, 66)]  # 60 already held, 5 new
        body = self.refresh(client, dataset_id).get_json()
        assert body["new_count"] == 5
        assert body["dataset"]["last_refresh"]["retrieval"][0]["capped"] is None

    def test_a_search_that_ended_in_the_past_is_refused_with_the_reason(self, client, source):
        dataset_id = make_dataset(to_date="2020-12-31")
        response = self.refresh(client, dataset_id)
        assert response.status_code == 400
        assert "ends on 2020-12-31" in response.get_json()["error"]
        assert source["asked"] == []

    def test_an_unknown_dataset_is_a_404(self, client, source):
        assert self.refresh(client, 999).status_code == 404

    def test_a_failing_source_changes_nothing(self, client, monkeypatch):
        dataset_id = make_dataset(papers=(1,))

        def fail(query, **kwargs):
            raise SourceError("OpenAlex is having trouble right now (HTTP 503). Try again later.")

        monkeypatch.setattr(openalex, "search_all", fail)
        response = self.refresh(client, dataset_id)
        assert response.status_code == 502
        dataset = db.get_dataset(dataset_id)
        assert dataset["last_refresh"] is None
        assert len(db.get_dataset_papers(dataset_id, include_excluded=True)) == 1

    def test_a_source_that_now_needs_a_missing_key_is_a_clear_400(self, client, source):
        usage = llm.Usage(1, 1, model="claude-haiku-4-5", provider="anthropic")
        dataset_id = db.save_retrieved_dataset("topic", ["q"], [work(1)], usage, sources=["semanticscholar"])
        response = self.refresh(client, dataset_id)
        assert response.status_code == 400
        assert "needs an API key" in response.get_json()["error"]

    def test_the_same_dataset_cannot_be_checked_twice_at_once(self, client, source):
        dataset_id = make_dataset()
        with app_module._exclusive("search", ("refresh", dataset_id)) as acquired:
            assert acquired
            response = self.refresh(client, dataset_id)
        assert response.status_code == 409
        assert "already being checked" in response.get_json()["error"]
        assert source["asked"] == []
        assert self.refresh(client, dataset_id).status_code == 200

    def test_queries_saved_before_validation_existed_are_cleaned(self, client, source):
        usage = llm.Usage(1, 1, model="claude-haiku-4-5", provider="anthropic")
        dataset_id = db.save_retrieved_dataset("topic", ["  a ", "", "A", "b" * 400], [work(1)], usage)
        self.refresh(client, dataset_id)
        assert [q for q, _, _ in source["asked"]] == ["a", "b" * llm.MAX_QUERY_CHARS]

    def test_the_dataset_list_shows_when_it_was_updated_and_creation_is_kept(self, client, source):
        dataset_id = make_dataset()
        row = client.get("/api/datasets").get_json()["datasets"][0]
        assert row["updated_at"] is None and row["created_at"]
        created = row["created_at"]
        self.refresh(client, dataset_id)
        row = client.get("/api/datasets").get_json()["datasets"][0]
        last = db.get_dataset(dataset_id)["last_refresh"]["at"]
        assert (row["updated_at"], row["created_at"]) == (last, created)
        assert client.get(f"/api/datasets/{dataset_id}").get_json()["created_at"] == created

    def test_one_unreadable_record_does_not_break_the_list_or_the_page(self, client, source):
        good, bad = make_dataset(), make_dataset(papers=(3,), queries=("other",))
        self.refresh(client, good)
        with closing(db._connect()) as conn:
            conn.execute("UPDATE dataset SET last_refresh = 'not json {' WHERE id = ?", (bad,))
            conn.commit()
        response = client.get("/api/datasets")
        assert response.status_code == 200
        updated = {row["id"]: row["updated_at"] for row in response.get_json()["datasets"]}
        assert updated[good] is not None and updated[bad] is None
        page = client.get(f"/api/datasets/{bad}")
        assert page.status_code == 200 and page.get_json()["last_refresh"] is None

    def test_the_dataset_list_and_page_still_load(self, client, source):
        dataset_id = make_dataset()
        self.refresh(client, dataset_id)
        assert client.get(f"/api/datasets/{dataset_id}").get_json()["last_refresh"]["new_count"] == 0
        assert client.get("/api/datasets").status_code == 200


class TestCitationCounts:
    def test_a_paper_seen_again_keeps_the_highest_count(self):
        paper_id = db.get_or_create_paper(work(1, citation_count=3))
        db.get_or_create_paper(work(1, citation_count=10))
        assert db.get_paper(paper_id)["citation_count"] == 10
        db.get_or_create_paper(work(1, citation_count=0))
        db.get_or_create_paper(work(1, citation_count=None))
        assert db.get_paper(paper_id)["citation_count"] == 10

    def test_a_source_without_counts_does_not_lower_one_found_by_doi(self):
        first = db.get_or_create_paper(work(1, doi="https://doi.org/10.1/x", citation_count=7))
        second = db.get_or_create_paper(
            {**work(2, doi="https://doi.org/10.1/x", citation_count=0), "source": "pubmed", "id": "99"}
        )
        assert first == second
        assert db.get_paper(first)["citation_count"] == 7


class TestMigration:
    def test_a_version_2_database_gets_the_last_refresh_column(self):
        db.ensure_ready()
        dataset_id = make_dataset()
        conn = db.sqlite3.connect(str(db.DB_PATH))
        conn.execute("ALTER TABLE dataset DROP COLUMN last_refresh")
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
        conn.close()
        db._ready_for = None
        db.ensure_ready()
        assert db.get_dataset(dataset_id)["last_refresh"] is None
        assert db.DB_PATH.with_name(f"{db.DB_PATH.name}.pre-upgrade-2-to-{db.SCHEMA_VERSION}").exists()
