"""Abstract lookup by DOI: a source having trouble must not be recorded as
"asked, not found", and DOIs must reach the sources intact."""

import re
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
    callable returning one); `fake.answer[label]`, if set, is called with the request
    instead, for replies that depend on what was asked. Every request is recorded in
    `fake.requests` (with "method")."""

    class Fake:
        def __init__(self):
            self.reply = {}
            self.answer = {}
            self.requests = []

        def of(self, label, method=None):
            return [r for r in self.requests if r["label"] == label and (method is None or r["method"] == method)]

    fake = Fake()
    lock = threading.Lock()

    def send(method):
        def request(label, url, **kwargs):
            sent = {"label": label, "url": url, "method": method, **kwargs}
            with lock:
                fake.requests.append(sent)
            if label in fake.answer:
                return fake.answer[label](sent)
            reply = fake.reply.get(label, FakeResponse(404))
            return reply() if callable(reply) else reply

        return request

    monkeypatch.setattr(abstracts, "get", send("GET"))
    monkeypatch.setattr(source_http, "get", send("GET"))
    monkeypatch.setattr(source_http, "post", send("POST"))
    monkeypatch.setattr(source_http, "_SEMANTIC_SCHOLAR_MIN_INTERVAL", 0)
    monkeypatch.setattr(source_http, "PAGE_RETRY_SECONDS", 0)
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


def asked_dois(request):
    """The DOIs a faked Semantic Scholar batch or Europe PMC search asked about."""
    if request["method"] == "POST":
        return [i.removeprefix("DOI:") for i in request["json"]["ids"]]
    return re.findall(r'DOI:"([^"]+)"', request["params"]["query"])


def paper_title(doi):
    return f"Coral reef growth survey number {doi.rsplit('p', 1)[1]}"


def abstract_source(paper_id):
    from contextlib import closing

    with closing(db._connect()) as conn:
        return conn.execute("SELECT abstract_source FROM paper WHERE id = ?", (paper_id,)).fetchone()[0]


def paper_abstract(doi):
    return f"An abstract for the paper at {doi}, long enough to be a real one. " * 2


def s2_batch(found=lambda doi: True, title=paper_title):
    """A Semantic Scholar batch reply: the paper for each DOI where found(doi), else null."""

    def answer(request):
        assert request["method"] == "POST", "a batch should go in one POST"
        return FakeResponse(
            200,
            [{"abstract": paper_abstract(d), "title": title(d)} if found(d) else None for d in asked_dois(request)],
        )

    return answer


def epmc_search(found=lambda doi: True, hit_count=None):
    """A Europe PMC reply holding a record for each DOI asked about where found(doi)."""

    def answer(request):
        results = [
            {"doi": d, "abstractText": paper_abstract(d), "title": paper_title(d)}
            for d in asked_dois(request)
            if found(d)
        ]
        count = len(results) if hit_count is None else hit_count
        return FakeResponse(200, {"hitCount": count, "resultList": {"result": results}})

    return answer


class TestAChunkIsLookedUpInBatches:
    """Semantic Scholar and Europe PMC are each asked about a whole chunk in one request.
    Asked one paper at a time, Semantic Scholar's rate limit alone cost over a second a paper.
    None of this may mark a paper "asked, not found" when it was not really asked."""

    @pytest.fixture
    def many_papers(self):
        dataset_id = db.create_dataset("topic", ["q"], name="Dataset")
        ids = [
            db.get_or_create_paper(
                {"id": f"W{i}", "title": paper_title(f"10.1/p{i}"), "doi": f"https://doi.org/10.1/p{i}", "year": 2020}
            )
            for i in range(12)
        ]
        db.add_papers_to_dataset(dataset_id, ids)
        return dataset_id, ids

    def lookup(self, client, dataset_id, **body):
        response = client.post(f"/api/datasets/{dataset_id}/find-abstracts", json=body)
        assert response.status_code == 200
        return response.get_json()

    def test_one_request_per_source_for_the_whole_chunk(self, client, sources, many_papers):
        dataset_id, ids = many_papers
        even = lambda doi: int(doi.rsplit("p", 1)[1]) % 2 == 0  # noqa: E731
        sources.answer["Semantic Scholar"] = s2_batch(found=even)
        sources.answer["Europe PMC"] = epmc_search()
        body = self.lookup(client, dataset_id)
        assert len(sources.of("Semantic Scholar")) == 1 and len(sources.of("Europe PMC")) == 1
        # Europe PMC is asked only about the papers Semantic Scholar did not find.
        assert sorted(asked_dois(sources.of("Europe PMC")[0])) == sorted(f"10.1/p{i}" for i in range(1, 12, 2))
        assert sorted(p["id"] for p in body["filled"]) == sorted(ids)
        assert abstract_source(ids[0]) == "semanticscholar" and abstract_source(ids[1]) == "europepmc"

    def test_a_chunk_is_25_papers(self, client, sources):
        dataset_id = db.create_dataset("topic", ["q"], name="Big")
        ids = [
            db.get_or_create_paper({"id": f"W{i}", "title": f"Paper {i}", "doi": f"https://doi.org/10.1/p{i}", "year": 2020})
            for i in range(30)
        ]
        db.add_papers_to_dataset(dataset_id, ids)
        sources.answer["Semantic Scholar"] = s2_batch()
        body = self.lookup(client, dataset_id)
        assert len(body["attempted"]) == app_module.FIND_ABSTRACTS_CHUNK_SIZE == 25
        assert body["remaining"] == 5 and len(sources.of("Semantic Scholar")) == 1

    def test_not_known_anywhere_is_a_real_answer(self, client, sources, many_papers):
        dataset_id, ids = many_papers
        sources.answer["Semantic Scholar"] = s2_batch(found=lambda doi: False)
        sources.answer["Europe PMC"] = epmc_search(found=lambda doi: False)
        body = self.lookup(client, dataset_id)
        assert body["filled"] == [] and sorted(body["checked"]) == sorted(ids)
        assert db.get_abstract_answers(ids[:1]) == {ids[0]: {"semanticscholar", "europepmc"}}

    def test_a_batch_refused_for_one_doi_is_narrowed_down_to_that_doi(self, client, sources, many_papers):
        # One unreadable id makes Semantic Scholar answer 400 to the whole batch (seen live). The
        # batch is split in half until that id is on its own, so the other papers still go in
        # batches instead of one paced request each.
        dataset_id, ids = many_papers

        def s2(request):
            if request["method"] == "POST":
                if "DOI:10.1/p5" in request["json"]["ids"]:
                    return FakeResponse(400, {"error": "No valid paper ids given"})
                return s2_batch()(request)
            if request["url"].endswith("p5"):
                return FakeResponse(404)
            doi = request["url"].rsplit("DOI:", 1)[1]
            return FakeResponse(200, semanticscholar_body(abstract=paper_abstract(doi), title=paper_title(doi)))

        sources.answer["Semantic Scholar"] = s2
        sources.answer["Europe PMC"] = epmc_search(found=lambda doi: False)
        body = self.lookup(client, dataset_id)
        assert len(body["filled"]) == 11 and body["checked"] == [ids[5]]
        # The refused batch was never taken as "not found" for the other eleven.
        assert len(sources.of("Semantic Scholar")) < 12
        assert len(sources.of("Semantic Scholar", "GET")) <= 3

    def test_a_source_refusing_every_batch_is_not_split_down_to_single_papers(self, client, sources, many_papers):
        # Splitting only pays when one odd DOI is to blame. When both halves are refused too,
        # each paper is asked on its own instead of halving all the way down (which cost about
        # twice as many paced requests).
        dataset_id, ids = many_papers
        sources.answer["Semantic Scholar"] = lambda request: FakeResponse(400 if request["method"] == "POST" else 404)
        sources.answer["Europe PMC"] = epmc_search(found=lambda doi: False)
        body = self.lookup(client, dataset_id)
        assert len(sources.of("Semantic Scholar", "POST")) == 3  # the batch, then its two halves
        assert len(sources.of("Semantic Scholar", "GET")) == 12
        assert sorted(body["checked"]) == sorted(ids)

    def test_a_refused_batch_whose_single_requests_fail_leaves_every_paper_to_try_again(self, client, sources, many_papers):
        dataset_id, ids = many_papers

        def s2(request):
            return FakeResponse(400 if request["method"] == "POST" else 503)

        sources.answer["Semantic Scholar"] = s2
        sources.answer["Europe PMC"] = epmc_search(found=lambda doi: False)
        body = self.lookup(client, dataset_id)
        assert body["checked"] == [] and "semanticscholar" in body["source_errors"]
        assert db.get_abstract_answers(ids[:1]) == {ids[0]: {"europepmc"}}
        # Once it failed, the rest of the chunk was not sent to it: the second half of the
        # refused batch was never asked one paper at a time.
        asked_alone = {r["url"].rsplit("DOI:", 1)[1] for r in sources.of("Semantic Scholar", "GET")}
        assert asked_alone and asked_alone <= {f"10.1/p{i}" for i in range(6)}

    def test_a_reply_of_the_wrong_length_is_not_trusted(self, client, sources, many_papers):
        dataset_id, ids = many_papers

        def s2(request):
            if request["method"] == "POST":
                return FakeResponse(200, [None])  # one entry for twelve papers
            return FakeResponse(404)

        sources.answer["Semantic Scholar"] = s2
        sources.answer["Europe PMC"] = epmc_search(found=lambda doi: False)
        body = self.lookup(client, dataset_id)
        assert len(sources.of("Semantic Scholar", "GET")) == 12  # asked one at a time instead
        assert sorted(body["checked"]) == sorted(ids)

    def test_a_europe_pmc_reply_that_was_cut_short_answers_only_for_what_it_holds(self, client, sources, many_papers):
        dataset_id, ids = many_papers
        sources.answer["Semantic Scholar"] = s2_batch(found=lambda doi: False)
        sources.answer["Europe PMC"] = epmc_search(found=lambda doi: doi == "10.1/p0", hit_count=500)
        body = self.lookup(client, dataset_id)
        assert [p["id"] for p in body["filled"]] == [ids[0]]
        assert body["checked"] == []  # the other DOIs may be in the hits not sent
        assert db.get_abstract_answers(ids[1:2]) == {ids[1]: {"semanticscholar"}}

    def test_a_failed_batch_leaves_every_paper_in_it_to_try_again(self, client, sources, many_papers):
        dataset_id, ids = many_papers
        sources.reply["Semantic Scholar"] = FakeResponse(503)
        sources.answer["Europe PMC"] = epmc_search(found=lambda doi: False)
        body = self.lookup(client, dataset_id)
        assert body["checked"] == [] and list(body["source_errors"]) == ["semanticscholar"]
        # Asked as one batch (a few tries), never paper by paper.
        assert len(sources.of("Semantic Scholar")) == source_http.PAGE_ATTEMPTS
        assert db.get_paper(ids[0])["abstract_checked"] is False

    def test_a_source_that_failed_is_not_asked_by_the_next_chunk(self, client, sources, many_papers):
        dataset_id, ids = many_papers
        sources.reply["Semantic Scholar"] = FakeResponse(503)
        sources.answer["Europe PMC"] = epmc_search(found=lambda doi: False)
        first = self.lookup(client, dataset_id)
        sources.requests.clear()
        self.lookup(client, dataset_id, skip_sources=list(first["source_errors"]))
        assert sources.of("Semantic Scholar") == []

    def test_the_title_is_checked_paper_by_paper(self, client, sources, many_papers):
        dataset_id, ids = many_papers
        wrong = lambda doi: "A different paper about tides" if doi == "10.1/p1" else paper_title(doi)  # noqa: E731
        sources.answer["Semantic Scholar"] = s2_batch(title=wrong)
        sources.answer["Europe PMC"] = epmc_search()
        body = self.lookup(client, dataset_id)
        assert asked_dois(sources.of("Europe PMC")[0]) == ["10.1/p1"]
        assert len(body["filled"]) == 12 and abstract_source(ids[1]) == "europepmc"

    def test_a_publisher_is_still_asked_per_paper_and_only_for_its_dois(self, sources, monkeypatch):
        monkeypatch.setattr(credentials_module(), "has_key", lambda name: True)
        papers = [(i, f"10.1016/j.x.{i}" if i < 3 else f"10.1/p{i}", None) for i in range(6)]
        sources.answer["Semantic Scholar"] = s2_batch(found=lambda doi: False)
        abstracts.lookup_batch(papers)
        assert len(sources.of("Elsevier")) == 3
        assert sources.of("Springer Nature") == []
        assert len(sources.of("Semantic Scholar")) == 1

    def test_a_batch_that_crashes_is_asked_one_paper_at_a_time(self, client, sources, many_papers, monkeypatch, caplog):
        import dataclasses

        dataset_id, ids = many_papers

        def boom(dois):
            raise RuntimeError("boom https://x/y?api_key=SECRET77")

        monkeypatch.setattr(
            abstracts,
            "SOURCES",
            [dataclasses.replace(s, batch=boom) if s.id == "semanticscholar" else s for s in abstracts.SOURCES],
        )
        sources.answer["Europe PMC"] = epmc_search(found=lambda doi: doi != "10.1/p3")
        body = self.lookup(client, dataset_id)
        assert len(sources.of("Semantic Scholar", "GET")) == 12
        assert len(body["filled"]) == 11 and body["checked"] == [ids[3]]
        assert "SECRET77" not in caplog.text and "boom" in caplog.text

    def test_a_crash_for_one_paper_keeps_the_others_answers(self, sources, monkeypatch, caplog):
        monkeypatch.setattr(credentials_module(), "has_key", lambda name: True)

        def elsevier(request):
            if request["url"].endswith("j.x.1"):
                return FakeResponse(200, ["not", "what", "Elsevier sends"])  # .get on a list raises
            coredata = {"dc:description": ABSTRACT, "dc:title": TITLE}
            return FakeResponse(200, {"abstracts-retrieval-response": {"coredata": coredata}})

        sources.answer["Elsevier"] = elsevier
        found = abstracts.lookup_batch([(i, f"10.1016/j.x.{i}", TITLE) for i in range(3)])
        assert found[0].source == found[2].source == "elsevier"
        assert found[1].abstract is None and "elsevier" not in found[1].answered
        assert found[1].complete is False and "j.x.1" in caplog.text

    def test_an_odd_looking_doi_is_asked_on_its_own(self, sources):
        odd = "10.1002/(sici)1097-4571(199806)49:8<693::aid-asi4>3.0.co;2-o"
        sources.answer["Semantic Scholar"] = lambda request: (
            s2_batch(found=lambda doi: False)(request) if request["method"] == "POST" else FakeResponse(404)
        )
        found = abstracts.lookup_batch([(0, "10.1/p0", None), (1, "10.1/p1", None), (2, odd, None)])
        (batch,) = sources.of("Semantic Scholar", "POST")
        assert batch["json"]["ids"] == ["DOI:10.1/p0", "DOI:10.1/p1"]
        assert len(sources.of("Semantic Scholar", "GET")) == 1
        assert all("semanticscholar" in found[i].answered for i in range(3))


class TestEuropePmcBatch:
    def test_a_doi_with_two_records_takes_the_one_with_an_abstract(self, sources):
        sources.reply["Europe PMC"] = FakeResponse(
            200,
            {
                "hitCount": 3,
                "resultList": {
                    "result": [
                        {"doi": "10.1/A", "abstractText": "", "title": "Preprint"},
                        {"doi": "10.1/a", "abstractText": ABSTRACT, "title": TITLE},
                        {"doi": "10.1/b", "abstractText": ABSTRACT, "title": TITLE},
                    ]
                },
            },
        )
        found = abstracts._europepmc_batch(["10.1/a", "10.1/b", "10.1/c"])
        assert found["10.1/a"].abstract == ABSTRACT.strip()
        assert found["10.1/c"] is None  # every hit was sent, so a missing DOI is a real "not found"

    def test_quotes_cannot_break_out_of_the_query(self, sources):
        sources.reply["Europe PMC"] = FakeResponse(200, {"hitCount": 0, "resultList": {"result": []}})
        abstracts._europepmc_batch(['10.1/x" OR DOI:"y', "10.1/z"])
        assert sources.requests[0]["params"]["query"] == 'DOI:"10.1/x OR DOI:y" OR DOI:"10.1/z"'

    @pytest.mark.parametrize("status", [500, 503])
    def test_a_server_error_is_a_source_error(self, sources, status):
        sources.reply["Europe PMC"] = FakeResponse(status)
        with pytest.raises(SourceError, match="Europe PMC"):
            abstracts._europepmc_batch(["10.1/a", "10.1/b"])

    def test_the_batch_gets_longer_to_answer_than_a_single_lookup(self, sources):
        # Europe PMC is often slow, and one batch stands in for up to 25 single requests.
        sources.reply["Europe PMC"] = FakeResponse(200, {"hitCount": 0, "resultList": {"result": []}})
        abstracts._europepmc_batch(["10.1/a", "10.1/b"])
        connect, answer = sources.requests[0]["timeout"]
        assert connect == source_http.LOOKUP_TIMEOUT[0] and answer >= 60

    def test_a_refusal_means_ask_one_at_a_time(self, sources):
        sources.reply["Europe PMC"] = FakeResponse(400)
        assert abstracts._europepmc_batch(["10.1/a", "10.1/b"]) is None


class TestSemanticScholarBatch:
    def test_the_dois_go_in_the_body_untouched(self, sources):
        doi = "10.1002/(sici)1097-4571(199806)49:8<693::aid-asi4>3.0.co;2-o"
        sources.reply["Semantic Scholar"] = FakeResponse(200, [None, None])
        abstracts._semanticscholar_batch([doi, "10.1/a?b#c"])
        request = sources.requests[0]
        assert request["method"] == "POST" and request["url"].endswith("/graph/v1/paper/batch")
        assert request["json"] == {"ids": [f"DOI:{doi}", "DOI:10.1/a?b#c"]}

    @pytest.mark.parametrize("status", [500, 503])
    def test_a_server_error_is_a_source_error(self, sources, status):
        sources.reply["Semantic Scholar"] = FakeResponse(status)
        with pytest.raises(SourceError, match="Semantic Scholar"):
            abstracts._semanticscholar_batch(["10.1/a", "10.1/b"])

    def test_a_lookup_uses_the_shorter_timeout(self, sources):
        sources.reply["Semantic Scholar"] = FakeResponse(200, [None, None])
        abstracts._semanticscholar_batch(["10.1/a", "10.1/b"])
        assert sources.requests[0]["timeout"] == source_http.LOOKUP_TIMEOUT


class TestSemanticScholarPacing:
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
