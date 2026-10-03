"""A search reads every hit, page by page, and says how complete it was."""

import pytest

import db
import openalex
import search_sources as ss
from source_http import SourceError


class FakeResponse:
    def __init__(self, status_code=200, body=None, content=b""):
        self.status_code = status_code
        self._body = body
        self.content = content

    def json(self):
        return self._body


def work(i):
    return {"id": f"W{i}", "title": f"Paper {i}", "publication_year": 2020, "publication_date": "2020-06-01"}


class TestOpenAlexPaging:
    def pages(self, monkeypatch, total, page_size=200):
        """A fake OpenAlex holding `total` works, served by cursor."""
        calls = []

        def fetch(params):
            calls.append(dict(params))
            start = 0 if params["cursor"] == "*" else int(params["cursor"])
            page = [work(i) for i in range(start, min(start + page_size, total))]
            nxt = start + page_size
            return {"meta": {"count": total, "next_cursor": str(nxt) if nxt < total else None}, "results": page}

        monkeypatch.setattr(openalex, "_fetch_page", fetch)
        return calls

    def test_every_page_is_read(self, monkeypatch):
        calls = self.pages(monkeypatch, 450)
        results, total = openalex.search_all("coral")
        assert (len(results), total) == (450, 450)
        assert [c["cursor"] for c in calls] == ["*", "200", "400"]
        assert all(c["per_page"] == 200 for c in calls)

    def test_a_search_with_no_hits_is_one_call(self, monkeypatch):
        calls = self.pages(monkeypatch, 0)
        assert openalex.search_all("coral") == ([], 0)
        assert len(calls) == 1

    def test_it_stops_at_the_ceiling_and_still_reports_the_total(self, monkeypatch):
        self.pages(monkeypatch, 1000)
        results, total = openalex.search_all("coral", max_results=300)
        assert (len(results), total) == (300, 1000)

    def test_a_cursor_that_never_advances_cannot_loop_forever(self, monkeypatch):
        monkeypatch.setattr(
            openalex, "_fetch_page", lambda params: {"meta": {"count": 9, "next_cursor": "same"}, "results": [work(1)]}
        )
        results, _ = openalex.search_all("coral")
        assert len(results) == 2

    def test_dates_and_key_are_sent_with_every_page(self, monkeypatch):
        calls = self.pages(monkeypatch, 300)
        openalex.search_all("coral", from_date="2020-01-01", to_date="2021-01-01")
        assert all(c["filter"] == "from_publication_date:2020-01-01,to_publication_date:2021-01-01" for c in calls)

    def test_an_unreadable_page_is_an_error(self, monkeypatch):
        monkeypatch.setattr(openalex, "_get_with_retry", lambda params: FakeResponse(200, ["not", "an", "object"]))
        with pytest.raises(Exception, match="unreadable"):
            openalex.search_all("coral")


class TestCeiling:
    def test_a_search_is_read_up_to_2500_papers_and_the_message_points_to_combining_datasets(self):
        assert ss.MAX_RESULTS_PER_SEARCH == 2500
        reason = ss._capped_reason(9000, 2500, None, "OpenAlex")
        assert "2,500" in reason and "narrow the question" in reason and "combine the datasets" in reason


class TestSourceCompleteness:
    def test_openalex_says_when_everything_matched_was_fetched(self, monkeypatch):
        monkeypatch.setattr(openalex, "search_all", lambda *a, **k: ([{**work(i), "source": "openalex"} for i in range(3)], 3))
        found = ss._search_openalex("coral", None, None)
        assert (found.total, found.fetched, found.capped) == (3, 3, None)

    def test_openalex_says_when_the_ceiling_stopped_it(self, monkeypatch):
        monkeypatch.setattr(ss, "MAX_RESULTS_PER_SEARCH", 3)
        monkeypatch.setattr(openalex, "search_all", lambda *a, **k: ([work(i) for i in range(3)], 50))
        found = ss._search_openalex("coral", None, None)
        assert (found.total, found.fetched) == (50, 3)
        assert "narrow the question" in found.capped

    def test_papers_outside_the_dates_are_dropped_but_still_counted_as_fetched(self, monkeypatch):
        papers = [work(1), {**work(2), "publication_year": 1990, "publication_date": "1990-01-01"}]
        monkeypatch.setattr(openalex, "search_all", lambda *a, **k: (papers, 2))
        found = ss._search_openalex("coral", "2019-01-01", "2021-01-01")
        assert (len(found), found.fetched, found.total, found.capped) == (1, 2, 2, None)

    def test_a_plain_list_from_a_source_still_filters(self):
        @ss._filtered
        def search(query, from_date, to_date):
            return [{"publication_date": "2000-01-01"}]

        found = search("q", None, None)
        assert (len(found), found.total, found.fetched, found.capped) == (1, None, 1, None)


class TestSemanticScholarPaging:
    def serve(self, monkeypatch, total):
        calls = []

        def get(url, params, **kwargs):
            calls.append(dict(params))
            start = params["offset"]
            page = [
                {"paperId": f"p{i}", "title": f"Paper {i}", "year": 2020}
                for i in range(start, min(start + params["limit"], total))
            ]
            return FakeResponse(200, {"total": total, "data": page})

        monkeypatch.setattr(ss, "semanticscholar_get", get)
        return calls

    def test_pages_of_100_until_everything_is_read(self, monkeypatch):
        calls = self.serve(monkeypatch, 250)
        found = ss._search_semanticscholar("coral", None, None)
        assert (len(found), found.total, found.capped) == (250, 250, None)
        assert [c["offset"] for c in calls] == [0, 100, 200]

    def test_it_reads_no_further_than_the_depth_semantic_scholar_allows_and_says_so(self, monkeypatch):
        calls = self.serve(monkeypatch, 5000)
        found = ss._search_semanticscholar("coral", None, None)
        assert (found.fetched, found.total) == (1000, 5000)
        assert "1,000" in found.capped
        assert calls[-1]["offset"] == 900

    def test_a_400_past_the_first_page_is_the_depth_limit_not_a_failure(self, monkeypatch):
        page = [{"paperId": str(i), "title": "t"} for i in range(100)]
        responses = iter([FakeResponse(200, {"total": 5000, "data": page})])
        monkeypatch.setattr(ss, "semanticscholar_get", lambda url, params, **kw: next(responses, FakeResponse(400)))
        found = ss._search_semanticscholar("coral", None, None)
        assert (found.fetched, found.total) == (100, 5000)
        assert "100 of the 5,000" in found.capped

    def test_an_error_on_a_later_page_fails_the_search(self, monkeypatch):
        responses = iter([FakeResponse(200, {"total": 300, "data": [{"paperId": str(i), "title": "t"} for i in range(100)]})])
        monkeypatch.setattr(ss, "semanticscholar_get", lambda url, params, **kw: next(responses, FakeResponse(503)))
        with pytest.raises(SourceError, match="503"):
            ss._search_semanticscholar("coral", None, None)


class TestScopusPaging:
    def serve(self, monkeypatch, total):
        calls = []

        def get(label, url, params=None, headers=None):
            calls.append(dict(params))
            start = params["start"]
            entries = [
                {"dc:identifier": f"SCOPUS_ID:{i}", "dc:title": f"Paper {i}", "prism:coverDate": "2020-06-01"}
                for i in range(start, min(start + params["count"], total))
            ] or [{"error": "Result set was empty"}]
            return FakeResponse(200, {"search-results": {"opensearch:totalResults": str(total), "entry": entries}})

        monkeypatch.setattr(ss, "get", get)
        return calls

    def test_pages_by_start_until_everything_is_read(self, monkeypatch):
        calls = self.serve(monkeypatch, 60)
        found = ss._search_scopus("coral", None, None)
        assert (len(found), found.total, found.capped) == (60, 60, None)
        assert [c["start"] for c in calls] == [0, 25, 50]

    def test_no_hits_is_an_empty_search_not_an_error(self, monkeypatch):
        self.serve(monkeypatch, 0)
        found = ss._search_scopus("coral", None, None)
        assert (len(found), found.total, found.fetched) == (0, 0, 0)

    def test_it_stops_at_the_depth_scopus_allows_and_says_so(self, monkeypatch):
        monkeypatch.setattr(ss, "SCOPUS_DEPTH", 100)
        self.serve(monkeypatch, 500)
        found = ss._search_scopus("coral", None, None)
        assert (found.fetched, found.total) == (100, 500)
        assert "100" in found.capped


def article(pmid):
    return (
        f"<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article><ArticleTitle>Paper {pmid}</ArticleTitle>"
        "<Journal><JournalIssue><PubDate><Year>2020</Year><Month>Jun</Month><Day>1</Day></PubDate></JournalIssue>"
        "<Title>Journal</Title></Journal></Article></MedlineCitation></PubmedArticle>"
    )


class TestPubMedPaging:
    def serve(self, monkeypatch, ids, total=None):
        calls = {"esearch": [], "efetch": []}

        def ncbi_get(url, params):
            if url.endswith("esearch.fcgi"):
                calls["esearch"].append(dict(params))
                return FakeResponse(200, {"esearchresult": {"count": str(total or len(ids)), "idlist": ids}})
            calls["efetch"].append(params["id"].split(","))
            xml = "<PubmedArticleSet>" + "".join(article(i) for i in params["id"].split(",")[::-1]) + "</PubmedArticleSet>"
            return FakeResponse(200, content=xml.encode())

        monkeypatch.setattr(ss, "ncbi_get", ncbi_get)
        return calls

    def test_every_id_is_fetched_in_batches_and_kept_in_search_order(self, monkeypatch):
        ids = [str(1000 + i) for i in range(450)]
        calls = self.serve(monkeypatch, ids)
        found = ss._search_pubmed("coral", None, None)
        assert [r["id"] for r in found] == ids
        assert [len(batch) for batch in calls["efetch"]] == [200, 200, 50]
        assert len(calls["esearch"]) == 1
        assert (found.total, found.fetched, found.capped) == (450, 450, None)

    def test_a_search_with_no_hits_fetches_nothing(self, monkeypatch):
        calls = self.serve(monkeypatch, [])
        found = ss._search_pubmed("coral", None, None)
        assert (len(found), calls["efetch"]) == (0, [])

    def test_more_matches_than_pubmed_will_list_is_reported(self, monkeypatch):
        ids = [str(i) for i in range(1, 11)]
        self.serve(monkeypatch, ids, total=25_000)
        monkeypatch.setattr(ss, "PUBMED_DEPTH", 10)
        found = ss._search_pubmed("coral", None, None)
        assert (found.fetched, found.total) == (10, 25_000)
        assert "PubMed will not return more than 10" in found.capped

    def test_the_ceiling_is_applied_to_the_ids(self, monkeypatch):
        ids = [str(i) for i in range(1, 21)]
        self.serve(monkeypatch, ids, total=20)
        monkeypatch.setattr(ss, "MAX_RESULTS_PER_SEARCH", 5)
        found = ss._search_pubmed("coral", None, None)
        assert (found.fetched, found.total) == (5, 20)
        assert "narrow the question" in found.capped


class TestPassingProblemsAreRetriedPerPage:
    """One hiccup partway through a long search must not throw away the pages read."""

    def test_openalex_reads_on_after_a_server_error(self, monkeypatch):
        import requests

        replies = iter(
            [
                {"meta": {"count": 400, "next_cursor": "200"}, "results": [work(i) for i in range(200)]},
                "503",
                "timeout",
                {"meta": {"count": 400, "next_cursor": None}, "results": [work(i) for i in range(200, 400)]},
            ]
        )

        def read_page(params):
            reply = next(replies)
            if reply == "503":
                error = requests.HTTPError("503")
                error.response = FakeResponse(503)
                raise error
            if reply == "timeout":
                raise requests.Timeout("slow")
            return reply

        monkeypatch.setattr(openalex, "_read_page", read_page)
        results, total = openalex.search_all("coral")
        assert (len(results), total) == (400, 400)

    def test_openalex_gives_up_after_the_attempts_and_does_not_retry_a_rejected_key(self, monkeypatch):
        import requests

        calls = []

        def read_page(params):
            calls.append(1)
            error = requests.HTTPError("403")
            error.response = FakeResponse(403)
            raise error

        monkeypatch.setattr(openalex, "_read_page", read_page)
        with pytest.raises(requests.HTTPError):
            openalex.search_all("coral")
        assert len(calls) == 1

        calls.clear()

        def always_down(params):
            calls.append(1)
            raise requests.ConnectionError("down")

        monkeypatch.setattr(openalex, "_read_page", always_down)
        with pytest.raises(requests.ConnectionError):
            openalex.search_all("coral")
        assert len(calls) == 3

    def test_openalex_does_not_retry_a_rate_limit_because_that_means_the_budget_is_gone(self, monkeypatch):
        import requests

        calls = []

        def limited(params):
            calls.append(1)
            error = requests.HTTPError("429")
            error.response = FakeResponse(429)
            raise error

        monkeypatch.setattr(openalex, "_read_page", limited)
        with pytest.raises(requests.HTTPError):
            openalex.search_all("coral")
        assert len(calls) == 1

    def test_semantic_scholar_reads_on_after_a_503(self, monkeypatch):
        page = [{"paperId": str(i), "title": "t"} for i in range(100)]
        replies = iter(
            [FakeResponse(200, {"total": 150, "data": page}), FakeResponse(503), FakeResponse(200, {"total": 150, "data": page[:50]})]
        )
        monkeypatch.setattr(ss, "semanticscholar_get", lambda url, params, **kw: next(replies))
        assert len(ss._search_semanticscholar("coral", None, None)) == 150

    def test_scopus_reads_on_after_a_502_but_not_after_a_used_up_quota(self, monkeypatch):
        entry = {"dc:identifier": "SCOPUS_ID:1", "dc:title": "Paper", "prism:coverDate": "2020-06-01"}
        ok = FakeResponse(200, {"search-results": {"opensearch:totalResults": "1", "entry": [entry]}})
        replies = iter([FakeResponse(502), ok])
        monkeypatch.setattr(ss, "get", lambda *a, **k: next(replies))
        assert len(ss._search_scopus("coral", None, None)) == 1

        calls = []
        monkeypatch.setattr(ss, "get", lambda *a, **k: (calls.append(1), FakeResponse(429))[1])
        with pytest.raises(SourceError, match="quota"):
            ss._search_scopus("coral", None, None)
        assert len(calls) == 1

    def test_pubmed_reads_on_after_a_server_error(self, monkeypatch):
        sent = []

        def ncbi_get(url, params):
            sent.append(url)
            if url.endswith("esearch.fcgi"):
                return FakeResponse(200, {"esearchresult": {"count": "1", "idlist": ["7"]}})
            if sum(u.endswith("efetch.fcgi") for u in sent) == 1:
                return FakeResponse(500)
            return FakeResponse(200, content=f"<PubmedArticleSet>{article('7')}</PubmedArticleSet>".encode())

        monkeypatch.setattr(ss, "ncbi_get", ncbi_get)
        assert [r["id"] for r in ss._search_pubmed("coral", None, None)] == ["7"]


class TestOneSearchAtATime:
    def search_key(self, question="coral", queries=("coral",)):
        return (question.lower(), None, None, ("openalex",), tuple(q.lower() for q in queries))

    def test_the_same_search_started_twice_is_refused_while_the_first_runs(self, client, monkeypatch):
        import app as app_module

        searched = []
        monkeypatch.setattr(openalex, "search_all", lambda query, **kw: (searched.append(query), ([], 0))[1])
        with app_module._exclusive("search", self.search_key()) as acquired:
            assert acquired
            response = client.post("/api/datasets", json={"question": "Coral", "queries": ["CORAL"]})
        assert response.status_code == 409
        assert "already running" in response.get_json()["error"]
        assert searched == []
        assert db.list_datasets() == []
        # Once the first has finished the same search runs.
        assert client.post("/api/datasets", json={"question": "Coral", "queries": ["CORAL"]}).status_code == 200

    def test_a_different_search_is_not_blocked(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(openalex, "search_all", lambda query, **kw: ([], 0))
        with app_module._exclusive("search", self.search_key("coral")):
            assert client.post("/api/datasets", json={"question": "solar", "queries": ["solar"]}).status_code == 200

    def test_a_failed_search_frees_the_lock(self, client, monkeypatch):
        def fail(query, **kwargs):
            raise SourceError("down")

        monkeypatch.setattr(openalex, "search_all", fail)
        assert client.post("/api/datasets", json={"question": "coral", "queries": ["coral"]}).status_code == 502
        monkeypatch.setattr(openalex, "search_all", lambda query, **kw: ([], 0))
        assert client.post("/api/datasets", json={"question": "coral", "queries": ["coral"]}).status_code == 200


class TestRetryOnlyRepeatsWhatDidNotFinish:
    """A retrieval that fails part way keeps the searches that finished, for the retry."""

    @pytest.fixture
    def flaky(self, monkeypatch):
        """OpenAlex that fails on some queries until told to stop, counting every search."""
        state = {"calls": [], "fail": {"b"}}

        def search_all(query, **kwargs):
            state["calls"].append(query)
            if query in state["fail"]:
                raise SourceError("OpenAlex is having trouble right now (HTTP 503). Try again later.")
            return [work(ord(query))], 1

        monkeypatch.setattr(openalex, "search_all", search_all)
        return state

    def post(self, client, queries=("a", "b", "c"), **extra):
        return client.post("/api/datasets", json={"question": "coral", "queries": list(queries), **extra})

    def test_the_retry_does_not_repeat_the_searches_that_finished(self, client, flaky):
        assert self.post(client).status_code == 502
        assert flaky["calls"] == ["a", "b"]
        flaky["fail"].clear()
        response = self.post(client)
        assert response.status_code == 200
        # "a" came from the kept search; "b" ran again; "c" had not run yet.
        assert flaky["calls"] == ["a", "b", "b", "c"]
        assert [r["query"] for r in response.get_json()["retrieval"]] == ["a", "b", "c"]
        assert len(response.get_json()["papers"]) == 3

    def test_a_finished_retrieval_leaves_nothing_behind_so_a_later_search_asks_again(self, client, flaky):
        import app as app_module

        flaky["fail"].clear()
        assert self.post(client).status_code == 200
        assert app_module._SEARCH_CACHE == {}
        assert self.post(client).status_code == 200
        assert flaky["calls"] == ["a", "b", "c", "a", "b", "c"]

    def test_kept_searches_expire(self, client, flaky, monkeypatch):
        import app as app_module

        self.post(client)
        monkeypatch.setattr(app_module, "SEARCH_CACHE_SECONDS", 0)
        flaky["fail"].clear()
        self.post(client)
        assert flaky["calls"] == ["a", "b", "a", "b", "c"]

    def test_a_search_with_other_dates_does_not_reuse_them(self, client, flaky):
        self.post(client)
        flaky["fail"].clear()
        self.post(client, from_date="2020-01-01")
        assert flaky["calls"] == ["a", "b", "a", "b", "c"]

    def test_what_is_kept_is_bounded_by_the_papers_held_and_the_newest_stays(self, client, flaky, monkeypatch):
        import app as app_module

        # Each search here finds one paper, so a limit of 2 papers keeps two searches.
        monkeypatch.setattr(app_module, "SEARCH_CACHE_MAX_PAPERS", 2)
        flaky["fail"] = {"e"}
        self.post(client, queries=("a", "b", "c", "d", "e"))
        assert {key[1] for key in app_module._SEARCH_CACHE} == {"c", "d"}

    def test_one_search_larger_than_the_limit_is_still_kept(self, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "SEARCH_CACHE_MAX_PAPERS", 2)
        big = ss.SearchResult([work(i) for i in range(5)])
        app_module._remember_search(("openalex", "q", None, None), big)
        assert app_module._cached_search(("openalex", "q", None, None)) is big


class TestADatasetIsSavedAsOneUnit:
    def usage(self):
        import llm

        return llm.Usage(10, 5, model="claude-haiku-4-5", provider="anthropic")

    def counts(self):
        from contextlib import closing

        with closing(db._connect()) as conn:
            return {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("dataset", "dataset_paper", "paper", "llm_call")
            }

    def test_everything_is_saved_together(self):
        papers = [{**work(i), "source": "openalex", "authors": []} for i in range(3)]
        dataset_id = db.save_retrieved_dataset(
            "topic", ["q"], papers, self.usage(), name="Coral", sources=["openalex"], retrieval=[{"source": "openalex"}]
        )
        assert self.counts() == {"dataset": 1, "dataset_paper": 3, "paper": 3, "llm_call": 1}
        assert db.get_dataset(dataset_id)["retrieval"] == [{"source": "openalex"}]
        assert db.get_cost(dataset_id=dataset_id) > 0
        assert len(db.get_dataset_papers(dataset_id)) == 3

    def test_a_failure_part_way_leaves_nothing_behind(self, monkeypatch):
        real = db._get_or_create_paper
        seen = []

        def fail_on_the_second(conn, result):
            seen.append(result["id"])
            if len(seen) == 2:
                raise RuntimeError("disk full")
            return real(conn, result)

        monkeypatch.setattr(db, "_get_or_create_paper", fail_on_the_second)
        papers = [{**work(i), "source": "openalex", "authors": []} for i in range(3)]
        with pytest.raises(RuntimeError):
            db.save_retrieved_dataset("topic", ["q"], papers, self.usage())
        assert self.counts() == {"dataset": 0, "dataset_paper": 0, "paper": 0, "llm_call": 0}

    def test_the_retry_after_a_failed_save_makes_one_dataset(self, client, monkeypatch):
        monkeypatch.setattr(openalex, "search_all", lambda query, **kw: ([work(1)], 1))
        real = db._get_or_create_paper
        broken = {"on": True}

        def maybe_fail(conn, result):
            if broken["on"]:
                raise RuntimeError("database is locked")
            return real(conn, result)

        monkeypatch.setattr(db, "_get_or_create_paper", maybe_fail)
        body = {"question": "coral", "queries": ["coral"]}
        assert client.post("/api/datasets", json=body).status_code == 500
        assert db.list_datasets() == []
        broken["on"] = False
        assert client.post("/api/datasets", json=body).status_code == 200
        assert len(db.list_datasets()) == 1


class TestRetrievalIsKeptWithTheDataset:
    def test_each_source_and_query_is_recorded(self, client, monkeypatch):
        def search_all(query, **kwargs):
            return [work(i) for i in range(3)], (50 if query == "wide" else 3)

        monkeypatch.setattr(openalex, "search_all", search_all)
        monkeypatch.setattr(ss, "MAX_RESULTS_PER_SEARCH", 3)
        response = client.post("/api/datasets", json={"question": "coral", "queries": ["wide", "narrow"]})
        assert response.status_code == 200, response.get_data(as_text=True)
        rows = {r["query"]: r for r in response.get_json()["retrieval"]}
        assert rows["narrow"] == {"source": "openalex", "query": "narrow", "total": 3, "fetched": 3, "kept": 3, "capped": None}
        assert rows["wide"]["total"] == 50 and "narrow the question" in rows["wide"]["capped"]
        # And it is still there when the dataset is opened again.
        again = client.get(f"/api/datasets/{response.get_json()['id']}").get_json()
        assert again["retrieval"] == response.get_json()["retrieval"]

    def test_a_dataset_from_before_it_was_recorded_has_none(self):
        dataset_id = db.create_dataset("topic", ["q"])
        assert db.get_dataset(dataset_id)["retrieval"] is None

    def test_a_failing_page_saves_no_dataset(self, client, monkeypatch):
        def search_all(query, **kwargs):
            raise SourceError("Semantic Scholar is having trouble right now (HTTP 503). Try again later.")

        monkeypatch.setattr(openalex, "search_all", search_all)
        response = client.post("/api/datasets", json={"question": "coral", "queries": ["coral"]})
        assert response.status_code == 502
        assert db.list_datasets() == []
