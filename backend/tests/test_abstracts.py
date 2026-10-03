"""Abstract lookup by DOI: a source having trouble must not be recorded as
"asked, not found", and DOIs must reach the sources intact."""

import threading

import pytest

import abstracts
import app as app_module
import db
import source_http
from source_http import SourceError

DOI = "10.1234/example.5"
TITLE = "Coral growth modeling in coral reefs"
ABSTRACT = "This study measures the effect of coral growth on reef output in field conditions. " * 2


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body
        self.headers = {}

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


def europepmc_body(doi=DOI, abstract=ABSTRACT, title=TITLE):
    return {"resultList": {"result": [{"doi": doi, "abstractText": abstract, "title": title}]}}


def semanticscholar_body(abstract=ABSTRACT, title=TITLE):
    return {"abstract": abstract, "title": title}


@pytest.fixture
def sources(monkeypatch):
    """Fake the four sources' HTTP. `fake.reply[label]` is a FakeResponse (or a
    callable returning one); every request is recorded in `fake.requests`."""

    class Fake:
        def __init__(self):
            self.reply = {}
            self.requests = []

    fake = Fake()

    def get(label, url, **kwargs):
        fake.requests.append({"label": label, "url": url, **kwargs})
        reply = fake.reply.get(label, FakeResponse(404))
        return reply() if callable(reply) else reply

    monkeypatch.setattr(abstracts, "get", get)
    monkeypatch.setattr(source_http, "get", get)
    monkeypatch.setattr(source_http, "_SEMANTIC_SCHOLAR_MIN_INTERVAL", 0)
    return fake


class TestRaiseIfUnavailable:
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_trouble_raises(self, status):
        with pytest.raises(SourceError, match=str(status)):
            source_http.raise_if_unavailable("Europe PMC", FakeResponse(status))

    @pytest.mark.parametrize("status", [200, 204, 400, 401, 403, 404, 410])
    def test_a_normal_answer_does_not(self, status):
        source_http.raise_if_unavailable("Europe PMC", FakeResponse(status))


@pytest.mark.parametrize("label, lookup", [
    ("Elsevier", abstracts._elsevier),
    ("Springer Nature", abstracts._springer),
    ("Europe PMC", abstracts._europepmc),
    ("Semantic Scholar", abstracts._semanticscholar),
])
class TestEachSourceTellsTroubleFromNotFound:
    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_a_server_error_is_a_source_error_not_a_miss(self, sources, label, lookup, status):
        sources.reply[label] = FakeResponse(status)
        with pytest.raises(SourceError, match=label):
            lookup(DOI)

    def test_a_404_is_a_miss(self, sources, label, lookup):
        sources.reply[label] = FakeResponse(404)
        assert lookup(DOI) is None

    def test_an_unexpected_client_error_is_a_miss(self, sources, label, lookup):
        sources.reply[label] = FakeResponse(400)
        assert lookup(DOI) is None


class TestAPassingProblemDoesNotSwitchASourceOff:
    """One timeout or dropped connection used to switch Europe PMC off for every paper left
    in the run. A few tries per paper come first, and the message says what went wrong."""

    # These use the real source_http.get (the `sources` fixture replaces it), faking only
    # requests.get underneath, since turning a requests error into a SourceUnavailable
    # is what is being tested.

    def test_a_dropped_connection_then_an_answer_still_finds_the_abstract(self, monkeypatch):
        import requests

        calls = []

        def requests_get(url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise requests.ConnectionError("reset")
            return FakeResponse(200, europepmc_body())

        monkeypatch.setattr(source_http.requests, "get", requests_get)
        abstract, source, errors, answered = abstracts.find_abstract(
            DOI, skip_sources={"semanticscholar"}, title=TITLE
        )
        assert (source, errors, answered) == ("europepmc", {}, 1)
        assert abstract == ABSTRACT.strip() and len(calls) == 2

    def test_a_source_too_slow_to_answer_is_asked_once_not_three_times(self, monkeypatch):
        import requests

        calls = []

        def requests_get(url, **kwargs):
            calls.append(url)
            raise requests.ReadTimeout("read timed out")

        monkeypatch.setattr(source_http.requests, "get", requests_get)
        _, source, errors, answered = abstracts.find_abstract(DOI, skip_sources={"semanticscholar"})
        assert source is None and answered == 0
        assert errors == {"europepmc": "Could not reach Europe PMC (it took too long to answer)."}
        assert len(calls) == 1

    def test_the_next_source_takes_over_after_a_slow_one(self, monkeypatch):
        import requests

        def requests_get(url, **kwargs):
            if "semanticscholar" in url:
                raise requests.ReadTimeout("read timed out")
            return FakeResponse(200, europepmc_body())

        monkeypatch.setattr(source_http.requests, "get", requests_get)
        abstract, source, errors, answered = abstracts.find_abstract(DOI, title=TITLE)
        assert source == "europepmc" and abstract == ABSTRACT.strip()
        assert errors == {"semanticscholar": "Could not reach Semantic Scholar (it took too long to answer)."}
        assert answered == 1

    def test_it_gives_up_after_three_tries_and_the_message_says_why(self, monkeypatch):
        import requests

        calls = []

        def requests_get(url, **kwargs):
            calls.append(url)
            raise requests.ConnectionError("reset by peer")

        monkeypatch.setattr(source_http.requests, "get", requests_get)
        _, source, errors, answered = abstracts.find_abstract(DOI, skip_sources={"semanticscholar"})
        assert source is None and answered == 0
        assert errors == {"europepmc": "Could not reach Europe PMC (the connection failed or was closed)."}
        assert len(calls) == source_http.PAGE_ATTEMPTS

    @pytest.mark.parametrize(
        "exc_name, words",
        [
            ("Timeout", "took too long to answer"),
            ("SSLError", "secure connection could not be made"),
            ("ConnectionError", "connection failed or was closed"),
            ("TooManyRedirects", "request failed"),
        ],
    )
    def test_the_cause_is_named(self, exc_name, words):
        import requests

        exc = getattr(requests, exc_name, None) or getattr(requests.exceptions, exc_name)
        assert words in source_http._why(exc("x"))

    def test_the_real_cause_is_logged_without_a_key(self, monkeypatch, caplog):
        import requests

        def requests_get(url, **kwargs):
            raise requests.ConnectionError("failed: https://example/x?api_key=SECRET99&q=1")

        monkeypatch.setattr(source_http.requests, "get", requests_get)
        with pytest.raises(SourceError):
            source_http.get("Europe PMC", "https://example/x")
        assert "ConnectionError" in caplog.text and "SECRET99" not in caplog.text

    def test_a_rejected_key_is_not_retried(self, sources):
        calls = []

        def reply():
            calls.append(1)
            return FakeResponse(401)

        sources.reply["Elsevier"] = reply
        monkey = pytest.MonkeyPatch()
        monkey.setattr(credentials_module(), "has_key", lambda name: True)
        try:
            _, _, errors, _ = abstracts.find_abstract("10.1016/j.x.2020.1", skip_sources={"europepmc", "semanticscholar"})
        finally:
            monkey.undo()
        assert "elsevier" in errors and len(calls) == 1


source_http_real_get = source_http.get


def credentials_module():
    import credentials

    return credentials


class TestFindAbstract:
    def test_a_source_in_trouble_is_reported_and_does_not_count_as_an_answer(self, sources):
        sources.reply["Europe PMC"] = FakeResponse(503)
        sources.reply["Semantic Scholar"] = FakeResponse(503)

        abstract, source, errors, answered = abstracts.find_abstract(DOI, title=TITLE)

        assert abstract is None and source is None
        assert set(errors) == {"europepmc", "semanticscholar"}
        assert answered == 0  # so the caller must not mark the paper "checked"

    def test_trouble_at_one_source_still_lets_the_next_one_answer(self, sources):
        sources.reply["Semantic Scholar"] = FakeResponse(503)
        sources.reply["Europe PMC"] = FakeResponse(200, europepmc_body())

        abstract, source, errors, answered = abstracts.find_abstract(DOI, title=TITLE)

        assert abstract == ABSTRACT.strip() and source == "europepmc"
        assert set(errors) == {"semanticscholar"}
        assert answered == 1

    def test_europe_pmc_is_asked_last_so_a_paper_found_earlier_never_waits_for_it(self, sources):
        sources.reply["Semantic Scholar"] = FakeResponse(200, semanticscholar_body())
        sources.reply["Europe PMC"] = FakeResponse(200, europepmc_body())

        _, source, _, _ = abstracts.find_abstract(DOI, title=TITLE)

        assert source == "semanticscholar"
        assert [r["label"] for r in sources.requests] == ["Semantic Scholar"]
        assert [s.id for s in abstracts.SOURCES][-1] == "europepmc"

    def test_not_found_everywhere_is_a_real_answer(self, sources):
        sources.reply["Europe PMC"] = FakeResponse(200, {"resultList": {"result": []}})
        sources.reply["Semantic Scholar"] = FakeResponse(404)

        abstract, _, errors, answered = abstracts.find_abstract(DOI, title=TITLE)

        assert abstract is None and errors == {} and answered == 2

    def test_a_source_that_failed_earlier_in_the_run_is_not_asked_again(self, sources):
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        abstracts.find_abstract(DOI, skip_sources={"europepmc"}, title=TITLE)
        assert [r["label"] for r in sources.requests] == ["Semantic Scholar"]


class TestDoisReachTheSourcesIntact:
    TRICKY = [
        "10.1002/(SICI)1097-4571(199806)49:8<693::AID-ASI4>3.0.CO;2-O",
        "10.1/a?b#c",
        "10.1000/with space",
        "10.1000/100%",
    ]

    @pytest.mark.parametrize("doi", TRICKY)
    def test_semantic_scholar_path_keeps_the_whole_doi(self, sources, doi):
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        abstracts._semanticscholar(doi)
        url = sources.requests[0]["url"]
        assert url.startswith("https://api.semanticscholar.org/graph/v1/paper/DOI:10.")
        for raw in ("?", "#", " ", "<", ">"):
            assert raw not in url[len("https://api.semanticscholar.org/graph/v1/paper/") :]

    @pytest.mark.parametrize("doi", TRICKY)
    def test_elsevier_path_keeps_the_whole_doi(self, sources, doi):
        sources.reply["Elsevier"] = FakeResponse(404)
        abstracts._elsevier(doi)
        path = sources.requests[0]["url"][len("https://api.elsevier.com/content/abstract/doi/") :]
        for raw in ("?", "#", " ", "<", ">"):
            assert raw not in path
        assert path.startswith("10.")

    def test_the_encoding_round_trips(self):
        from urllib.parse import unquote

        for doi in self.TRICKY:
            assert unquote(source_http.quote_doi(doi)) == doi.lower()

    def test_slashes_and_parentheses_stay_readable(self):
        assert source_http.quote_doi("10.1002/(SICI)1097") == "10.1002/(sici)1097"

    def test_quotes_cannot_break_out_of_a_search_expression(self, sources):
        sources.reply["Europe PMC"] = FakeResponse(404)
        abstracts._europepmc('10.1/x" OR DOI:"y')
        query = sources.requests[0]["params"]["query"]
        assert query == 'DOI:"10.1/x OR DOI:y"'
        sources.reply["Springer Nature"] = FakeResponse(404)
        abstracts._springer('10.1007/x"y')
        assert '"' not in sources.requests[1]["params"]["q"]

    def test_a_doi_in_a_url_form_is_normalized_first(self):
        assert source_http.quote_doi("https://doi.org/10.1/ABC") == "10.1/abc"


@pytest.fixture
def dataset_with_one_paper():
    dataset_id = db.create_dataset("topic", ["q"], name="D")
    paper_id = db.get_or_create_paper(
        {"id": "W1", "title": TITLE, "abstract": "", "year": 2020, "doi": f"https://doi.org/{DOI}"}
    )
    db.add_papers_to_dataset(dataset_id, [paper_id])
    return dataset_id, paper_id


class TestLookupsRunTogether:
    """A batch of papers is looked up at the same time, so a slow source holds up only its
    own paper."""

    @pytest.fixture
    def many_papers(self):
        dataset_id = db.create_dataset("topic", ["q"], name="Dataset")
        ids = [
            db.get_or_create_paper({"id": f"W{i}", "title": f"Paper {i}", "doi": f"https://doi.org/10.1/p{i}", "year": 2020})
            for i in range(12)
        ]
        db.add_papers_to_dataset(dataset_id, ids)
        return dataset_id, ids

    def test_ten_lookups_are_in_flight_together(self, client, many_papers, monkeypatch):
        dataset_id, ids = many_papers
        together = threading.Barrier(10, timeout=10)

        def find(doi, skip_sources=frozenset(), title=None, answered_before=frozenset()):
            together.wait()  # only returns once ten lookups are running at once
            return abstracts.Lookup(ABSTRACT, "europepmc", {}, frozenset({"europepmc"}), True)

        monkeypatch.setattr(abstracts, "lookup_abstract", find)
        response = client.post(f"/api/datasets/{dataset_id}/find-abstracts", json={})
        body = response.get_json()
        assert response.status_code == 200
        assert len(body["attempted"]) == 10 and len(body["filled"]) == 10
        assert body["remaining"] == 2

    def test_the_results_come_back_in_the_batch_order(self, client, many_papers, monkeypatch):
        import time

        dataset_id, ids = many_papers

        def find(doi, skip_sources=frozenset(), title=None, answered_before=frozenset()):
            # The first papers finish last.
            time.sleep(0.2 - 0.015 * int(doi.rsplit("p", 1)[1]))
            return abstracts.Lookup(ABSTRACT, "europepmc", {}, frozenset({"europepmc"}), True)

        monkeypatch.setattr(abstracts, "lookup_abstract", find)
        body = client.post(f"/api/datasets/{dataset_id}/find-abstracts", json={}).get_json()
        assert body["attempted"] == sorted(body["attempted"]) == [p["id"] for p in body["filled"]]

    def test_one_slow_paper_does_not_hold_up_the_others_being_found(self, client, many_papers, monkeypatch):
        import time

        dataset_id, ids = many_papers
        started = {}

        def find(doi, skip_sources=frozenset(), title=None, answered_before=frozenset()):
            started[doi] = time.monotonic()
            time.sleep(1.0 if doi.endswith("p0") else 0.05)
            return abstracts.Lookup(ABSTRACT, "europepmc", {}, frozenset({"europepmc"}), True)

        monkeypatch.setattr(abstracts, "lookup_abstract", find)
        begin = time.monotonic()
        client.post(f"/api/datasets/{dataset_id}/find-abstracts", json={})
        # One second for the slow one, not one second plus nine more waits.
        assert time.monotonic() - begin < 1.6
        assert max(started.values()) - min(started.values()) < 0.5

    def test_a_lookup_that_crashes_leaves_the_others_and_the_paper_to_retry(self, client, many_papers, monkeypatch, caplog):
        dataset_id, ids = many_papers

        def find(doi, skip_sources=frozenset(), title=None, answered_before=frozenset()):
            if doi.endswith("p3"):
                raise RuntimeError("boom https://x/y?api_key=SECRET77")
            return abstracts.Lookup(ABSTRACT, "europepmc", {}, frozenset({"europepmc"}), True)

        monkeypatch.setattr(abstracts, "lookup_abstract", find)
        response = client.post(f"/api/datasets/{dataset_id}/find-abstracts", json={})
        body = response.get_json()
        assert response.status_code == 200
        assert len(body["filled"]) == 9 and body["checked"] == []
        # Not marked checked, so a later lookup tries it again; and the log has no key.
        assert ids[3] in body["attempted"] and db.get_paper(ids[3])["abstract_checked"] is False
        assert "SECRET77" not in caplog.text and "boom" in caplog.text

    def test_a_source_that_fails_is_reported_once_and_skipped_afterwards(self, client, many_papers, monkeypatch):
        dataset_id, ids = many_papers

        def find(doi, skip_sources=frozenset(), title=None, answered_before=frozenset()):
            return abstracts.Lookup(
                None, None, {"europepmc": "Could not reach Europe PMC (it took too long to answer)."}, frozenset(), False
            )

        monkeypatch.setattr(abstracts, "lookup_abstract", find)
        body = client.post(f"/api/datasets/{dataset_id}/find-abstracts", json={}).get_json()
        assert body["source_errors"] == {"europepmc": "Could not reach Europe PMC (it took too long to answer)."}
        assert body["checked"] == []  # every source errored, so nothing is recorded as checked

    def test_semantic_scholar_requests_stay_one_interval_apart_however_many_are_waiting(self, monkeypatch):
        import time

        monkeypatch.setattr(source_http, "_SEMANTIC_SCHOLAR_MIN_INTERVAL", 0.06)
        monkeypatch.setattr(source_http, "_last_semantic_scholar_call", 0.0)
        sent = []

        def get(label, url, **kwargs):
            sent.append(time.monotonic())
            return FakeResponse(200, semanticscholar_body())

        monkeypatch.setattr(source_http, "get", get)
        threads = [
            threading.Thread(target=source_http.semanticscholar_get, args=("https://s2/x", {"fields": "abstract"}))
            for _ in range(6)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        sent.sort()
        gaps = [b - a for a, b in zip(sent, sent[1:])]
        # Without the lock all six would go out within a millisecond or two of each other; the
        # margin allows for the timer's precision on Windows (about 15 ms).
        assert len(sent) == 6 and min(gaps) > 0.03


class TestEverySourceMustAnswer:
    """A paper is recorded as looked up only once every source that applies has answered. A
    source that was down, too slow or skipped has not been asked, so the paper must be
    tried again, and only the sources that never answered are asked the next time."""

    def test_all_sources_saying_not_found_is_complete(self, sources):
        sources.reply["Europe PMC"] = FakeResponse(200, {"resultList": {"result": []}})
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        found = abstracts.lookup_abstract(DOI, title=TITLE)
        assert found.abstract is None and found.complete is True
        assert found.answered == {"semanticscholar", "europepmc"}

    def test_a_source_that_failed_leaves_it_incomplete(self, sources):
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        sources.reply["Europe PMC"] = FakeResponse(503)
        found = abstracts.lookup_abstract(DOI, title=TITLE)
        assert found.complete is False
        assert found.answered == {"semanticscholar"} and list(found.errors) == ["europepmc"]

    def test_a_source_skipped_because_it_failed_earlier_leaves_it_incomplete(self, sources):
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        found = abstracts.lookup_abstract(DOI, skip_sources={"europepmc"}, title=TITLE)
        assert found.complete is False and found.answered == {"semanticscholar"}
        assert [r["label"] for r in sources.requests] == ["Semantic Scholar"]

    def test_sources_that_answered_before_are_not_asked_again_and_count_toward_complete(self, sources):
        sources.reply["Europe PMC"] = FakeResponse(200, {"resultList": {"result": []}})
        found = abstracts.lookup_abstract(DOI, title=TITLE, answered_before={"semanticscholar"})
        assert [r["label"] for r in sources.requests] == ["Europe PMC"]
        assert found.complete is True and found.answered == {"europepmc"}

    def test_a_source_that_does_not_apply_is_not_waited_for(self, sources):
        # No Elsevier or Springer key is saved, so only the two open sources count.
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        sources.reply["Europe PMC"] = FakeResponse(404)
        assert abstracts.lookup_abstract("10.1016/j.x.2020.1", title=TITLE).complete is True

    def test_a_publisher_source_with_a_key_must_answer_too(self, sources, monkeypatch):
        monkeypatch.setattr(credentials_module(), "has_key", lambda name: True)
        sources.reply["Elsevier"] = FakeResponse(503)
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        sources.reply["Europe PMC"] = FakeResponse(404)
        found = abstracts.lookup_abstract("10.1016/j.x.2020.1", title=TITLE)
        assert found.complete is False and "elsevier" in found.errors

    def test_a_found_abstract_is_complete_and_a_missing_doi_is_not(self, sources):
        sources.reply["Semantic Scholar"] = FakeResponse(200, semanticscholar_body())
        assert abstracts.lookup_abstract(DOI, title=TITLE).complete is True
        assert abstracts.lookup_abstract("", title=TITLE).complete is False

    def test_the_old_four_value_form_still_works(self, sources):
        sources.reply["Semantic Scholar"] = FakeResponse(200, semanticscholar_body())
        abstract, source, errors, answered = abstracts.find_abstract(DOI, title=TITLE)
        assert (source, errors, answered) == ("semanticscholar", {}, 1) and abstract == ABSTRACT.strip()


class TestWhatHasAnsweredIsRemembered:
    def test_answers_accumulate_and_are_read_back(self):
        paper = db.get_or_create_paper({"id": "W1", "title": "A paper", "year": 2020})
        other = db.get_or_create_paper({"id": "W2", "title": "Another paper", "year": 2021})
        assert db.get_abstract_answers([paper, other]) == {}
        db.add_abstract_answers(paper, {"semanticscholar"})
        db.add_abstract_answers(paper, {"europepmc", "semanticscholar"})
        assert db.get_abstract_answers([paper, other]) == {paper: {"semanticscholar", "europepmc"}}

    def test_an_unreadable_record_is_ignored(self):
        from contextlib import closing

        paper = db.get_or_create_paper({"id": "W1", "title": "A paper", "year": 2020})
        with closing(db._connect()) as conn:
            conn.execute("UPDATE paper SET abstract_answered = 'not json' WHERE id = ?", (paper,))
            conn.commit()
        assert db.get_abstract_answers([paper]) == {}
        db.add_abstract_answers(paper, {"europepmc"})  # does not crash, starts again
        assert db.get_abstract_answers([paper]) == {paper: {"europepmc"}}

    def test_a_version_5_database_gets_the_column(self):
        db.ensure_ready()
        paper = db.get_or_create_paper({"id": "W1", "title": "A paper", "year": 2020})
        conn = db.sqlite3.connect(str(db.DB_PATH))
        conn.execute("ALTER TABLE paper DROP COLUMN abstract_answered")
        conn.execute("PRAGMA user_version = 5")
        conn.commit()
        conn.close()
        db._ready_for = None
        db.ensure_ready()
        assert db.get_abstract_answers([paper]) == {}
        assert db.DB_PATH.with_name(f"{db.DB_PATH.name}.pre-upgrade-5-to-{db.SCHEMA_VERSION}").exists()


class TestARunThatCouldNotReachEverySource:
    def lookup(self, client, dataset_id, **body):
        return client.post(f"/api/datasets/{dataset_id}/find-abstracts", json=body).get_json()

    def test_the_paper_is_not_recorded_as_looked_up_while_a_source_is_down(self, client, sources, dataset_with_one_paper):
        dataset_id, paper_id = dataset_with_one_paper
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        sources.reply["Europe PMC"] = FakeResponse(503)
        body = self.lookup(client, dataset_id)
        assert body["checked"] == [] and body["filled"] == []
        assert list(body["source_errors"]) == ["europepmc"]
        assert db.get_paper(paper_id)["abstract_checked"] is False
        assert db.get_abstract_answers([paper_id]) == {paper_id: {"semanticscholar"}}

    def test_the_next_lookup_asks_only_the_source_that_never_answered(self, client, sources, dataset_with_one_paper):
        dataset_id, paper_id = dataset_with_one_paper
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        sources.reply["Europe PMC"] = FakeResponse(503)
        self.lookup(client, dataset_id)
        sources.requests.clear()

        sources.reply["Europe PMC"] = FakeResponse(200, {"resultList": {"result": []}})
        body = self.lookup(client, dataset_id)
        assert [r["label"] for r in sources.requests] == ["Europe PMC"]
        assert body["checked"] == [paper_id]
        assert db.get_paper(paper_id)["abstract_checked"] is True

    def test_the_next_lookup_can_still_find_the_abstract(self, client, sources, dataset_with_one_paper):
        dataset_id, paper_id = dataset_with_one_paper
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        sources.reply["Europe PMC"] = FakeResponse(503)
        self.lookup(client, dataset_id)

        sources.reply["Europe PMC"] = FakeResponse(200, europepmc_body())
        body = self.lookup(client, dataset_id)
        assert [p["id"] for p in body["filled"]] == [paper_id]
        assert db.get_paper(paper_id)["abstract"] == ABSTRACT.strip()

    def test_a_source_skipped_by_the_client_leaves_the_paper_to_try_again(self, client, sources, dataset_with_one_paper):
        dataset_id, paper_id = dataset_with_one_paper
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        body = self.lookup(client, dataset_id, skip_sources=["europepmc"])
        assert body["checked"] == [] and db.get_paper(paper_id)["abstract_checked"] is False

    def test_saving_a_new_key_re_opens_checked_papers_but_keeps_what_answered(self, client, sources, dataset_with_one_paper):
        dataset_id, paper_id = dataset_with_one_paper
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        sources.reply["Europe PMC"] = FakeResponse(200, {"resultList": {"result": []}})
        assert self.lookup(client, dataset_id)["checked"] == [paper_id]
        client.post("/api/settings/api-key", json={"provider": "semanticscholar", "api_key": "k" * 20})
        assert db.get_paper(paper_id)["abstract_checked"] is False
        assert db.get_abstract_answers([paper_id]) == {paper_id: {"semanticscholar", "europepmc"}}


class TestFindAbstractsRoute:
    def lookup(self, client, dataset_id, **body):
        return client.post(f"/api/datasets/{dataset_id}/find-abstracts", json=body).get_json()

    def test_a_source_outage_leaves_the_paper_to_be_tried_again(self, client, sources, dataset_with_one_paper):
        dataset_id, paper_id = dataset_with_one_paper
        sources.reply["Europe PMC"] = FakeResponse(503)
        sources.reply["Semantic Scholar"] = FakeResponse(500)

        first = self.lookup(client, dataset_id)

        assert first["attempted"] == [paper_id]
        assert first["checked"] == []
        assert first["filled"] == []
        assert set(first["source_errors"]) == {"europepmc", "semanticscholar"}
        assert db.get_paper(paper_id)["abstract_checked"] is False

        # The next lookup (sources back) finds it, because it was never marked.
        sources.reply["Europe PMC"] = FakeResponse(200, europepmc_body())
        second = self.lookup(client, dataset_id)
        assert [p["id"] for p in second["filled"]] == [paper_id]
        assert db.get_paper(paper_id)["abstract"] == ABSTRACT.strip()

    def test_not_found_everywhere_marks_the_paper_checked(self, client, sources, dataset_with_one_paper):
        dataset_id, paper_id = dataset_with_one_paper
        sources.reply["Europe PMC"] = FakeResponse(200, {"resultList": {"result": []}})
        sources.reply["Semantic Scholar"] = FakeResponse(404)

        result = self.lookup(client, dataset_id)

        assert result["checked"] == [paper_id]
        assert db.get_paper(paper_id)["abstract_checked"] is True
        # And it is left alone from then on.
        assert self.lookup(client, dataset_id)["attempted"] == []

    def test_a_found_abstract_is_saved_with_its_source(self, client, sources, dataset_with_one_paper):
        dataset_id, paper_id = dataset_with_one_paper
        sources.reply["Europe PMC"] = FakeResponse(200, europepmc_body())

        result = self.lookup(client, dataset_id)

        assert [p["id"] for p in result["filled"]] == [paper_id]
        assert result["remaining"] == 0

    def test_a_second_lookup_on_the_same_dataset_is_refused_while_one_runs(self, client, sources, dataset_with_one_paper):
        dataset_id, _ = dataset_with_one_paper
        started, release = threading.Event(), threading.Event()

        def slow():
            started.set()
            assert release.wait(10)
            return FakeResponse(200, europepmc_body())

        sources.reply["Europe PMC"] = slow
        out = {}
        worker = threading.Thread(
            target=lambda: out.update(r=app_module.app.test_client().post(f"/api/datasets/{dataset_id}/find-abstracts", json={}))
        )
        worker.start()
        try:
            assert started.wait(5)
            refused = client.post(f"/api/datasets/{dataset_id}/find-abstracts", json={})
            assert refused.status_code == 409
            assert "already running" in refused.get_json()["error"]
        finally:
            release.set()
            worker.join(10)
        assert out["r"].status_code == 200
        assert len([r for r in sources.requests if r["label"] == "Europe PMC"]) == 1

    def test_a_different_dataset_is_not_blocked(self, client, sources, dataset_with_one_paper):
        other = db.create_dataset("other topic", ["q"], name="Other")
        sources.reply["Europe PMC"] = FakeResponse(200, {"resultList": {"result": []}})
        sources.reply["Semantic Scholar"] = FakeResponse(404)
        assert client.post(f"/api/datasets/{other}/find-abstracts", json={}).status_code == 200

    def test_bad_input_is_still_a_400_before_any_lock_or_lookup(self, client, sources, dataset_with_one_paper):
        dataset_id, _ = dataset_with_one_paper
        assert client.post(f"/api/datasets/{dataset_id}/find-abstracts", json={"skip_ids": "x"}).status_code == 400
        assert client.post(f"/api/datasets/{dataset_id}/find-abstracts", json={"skip_sources": ["nope"]}).status_code == 400
        assert sources.requests == []

    def test_an_unknown_dataset_is_a_404(self, client, sources):
        assert client.post("/api/datasets/999/find-abstracts", json={}).status_code == 404
