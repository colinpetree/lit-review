"""Semantic Scholar search: a rejected query is an error, not "no results"."""

import pytest

import search_sources as ss
from source_http import SourceError


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def search_with(monkeypatch, response):
    monkeypatch.setattr(ss, "semanticscholar_get", lambda url, params, **kwargs: response)
    return ss._search_semanticscholar("coral reefs", None, None)


class TestSemanticScholarSearch:
    def test_a_rejected_query_is_an_error_so_the_dataset_is_not_silently_short_a_source(self, monkeypatch):
        with pytest.raises(SourceError, match="rejected the query"):
            search_with(monkeypatch, FakeResponse(400))

    def test_a_404_means_nothing_found(self, monkeypatch):
        assert search_with(monkeypatch, FakeResponse(404)) == []

    @pytest.mark.parametrize("status", [401, 403, 500, 503])
    def test_other_failures_are_errors(self, monkeypatch, status):
        with pytest.raises(SourceError, match=str(status)):
            search_with(monkeypatch, FakeResponse(status))

    def test_results_are_read(self, monkeypatch):
        body = {
            "data": [
                {
                    "paperId": "abc",
                    "title": "Coral growth",
                    "abstract": "An abstract.",
                    "year": 2023,
                    "publicationDate": "2023-04-05",
                    "citationCount": 4,
                    "externalIds": {"DOI": "10.1/x"},
                    "authors": [{"name": "Ada"}],
                    "publicationTypes": ["Review"],
                },
                {"paperId": "no-title"},
            ]
        }
        results = search_with(monkeypatch, FakeResponse(200, body))
        assert [r["id"] for r in results] == ["abc"]
        assert results[0]["doi"] == "https://doi.org/10.1/x"
        assert results[0]["is_review"] is True

    def test_no_results_in_a_good_reply_is_an_empty_list(self, monkeypatch):
        assert search_with(monkeypatch, FakeResponse(200, {"data": []})) == []
        assert search_with(monkeypatch, FakeResponse(200, {})) == []
