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


class TestFindAbstract:
    def test_a_source_in_trouble_is_reported_and_does_not_count_as_an_answer(self, sources):
        sources.reply["Europe PMC"] = FakeResponse(503)
        sources.reply["Semantic Scholar"] = FakeResponse(503)

        abstract, source, errors, answered = abstracts.find_abstract(DOI, title=TITLE)

        assert abstract is None and source is None
        assert set(errors) == {"europepmc", "semanticscholar"}
        assert answered == 0  # so the caller must not mark the paper "checked"

    def test_trouble_at_one_source_still_lets_the_next_one_answer(self, sources):
        sources.reply["Europe PMC"] = FakeResponse(503)
        sources.reply["Semantic Scholar"] = FakeResponse(200, semanticscholar_body())

        abstract, source, errors, answered = abstracts.find_abstract(DOI, title=TITLE)

        assert abstract == ABSTRACT.strip() and source == "semanticscholar"
        assert set(errors) == {"europepmc"}
        assert answered == 1

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
