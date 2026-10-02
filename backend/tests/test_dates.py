import datetime
import xml.etree.ElementTree as ET

import pytest

import app as app_module
import search_sources as ss


class TestSpan:
    def test_full_date(self):
        assert ss._span({"publication_date": "2024-03-05", "year": 2024}) == ("2024-03-05", "2024-03-05")

    def test_month_precision_covers_the_month(self):
        result = {"publication_date": "2024-02-01", "date_precision": "month"}
        assert ss._span(result) == ("2024-02-01", "2024-02-29")

    def test_year_precision_covers_the_year(self):
        result = {"publication_date": "2023-01-01", "date_precision": "year"}
        assert ss._span(result) == ("2023-01-01", "2023-12-31")

    def test_year_only(self):
        assert ss._span({"year": 2020}) == ("2020-01-01", "2020-12-31")

    def test_nothing_known(self):
        assert ss._span({}) == (None, None)


class TestInRange:
    def test_inside_and_boundaries(self):
        paper = {"publication_date": "2024-03-05"}
        assert ss._in_range(paper, "2024-03-05", "2024-03-05")
        assert ss._in_range(paper, "2024-01-01", None)
        assert ss._in_range(paper, None, "2024-12-31")

    def test_outside(self):
        paper = {"publication_date": "2024-03-05"}
        assert not ss._in_range(paper, "2024-03-06", None)
        assert not ss._in_range(paper, None, "2024-03-04")

    def test_month_precision_is_kept_if_any_day_overlaps(self):
        paper = {"publication_date": "2024-03-01", "date_precision": "month"}
        assert ss._in_range(paper, "2024-03-20", "2024-04-10")
        assert not ss._in_range(paper, "2024-04-01", None)

    def test_undated_papers_are_kept(self):
        assert ss._in_range({}, "2024-01-01", "2024-12-31")


class TestFilteredDefaultEnd:
    def run(self, from_date, to_date):
        seen = {}

        @ss._filtered
        def search(query, from_d, to_d):
            seen["to"] = to_d
            return [{"publication_date": "2000-01-01"}]

        results = search("q", from_date, to_date)
        return seen["to"], results

    def test_open_end_defaults_to_today(self):
        to_date, _ = self.run(None, None)
        assert to_date == datetime.date.today().isoformat()

    def test_open_end_with_a_past_start_defaults_to_today(self):
        to_date, _ = self.run("2020-01-01", None)
        assert to_date == datetime.date.today().isoformat()

    def test_a_future_start_with_no_end_stays_open(self):
        to_date, _ = self.run("2999-01-01", None)
        assert to_date is None

    def test_an_end_the_user_typed_is_kept_even_if_in_the_future(self):
        to_date, _ = self.run(None, "2999-12-31")
        assert to_date == "2999-12-31"

    def test_results_outside_the_range_are_dropped(self):
        _, results = self.run("2010-01-01", None)
        assert results == []


def article(pub_date_xml):
    return ET.fromstring(
        f"<PubmedArticle><MedlineCitation><Article><Journal><JournalIssue>{pub_date_xml}"
        "</JournalIssue></Journal></Article></MedlineCitation></PubmedArticle>"
    )


class TestPubmedDate:
    def test_day_precision(self):
        xml = "<PubDate><Year>2024</Year><Month>Mar</Month><Day>5</Day></PubDate>"
        assert ss._pubmed_date(article(xml)) == (2024, "2024-03-05", "day")

    def test_numeric_month_means_month_precision(self):
        xml = "<PubDate><Year>2024</Year><Month>11</Month></PubDate>"
        assert ss._pubmed_date(article(xml)) == (2024, "2024-11-01", "month")

    def test_year_only(self):
        assert ss._pubmed_date(article("<PubDate><Year>2019</Year></PubDate>")) == (2019, "2019-01-01", "year")

    def test_medline_date_gives_a_year(self):
        xml = "<PubDate><MedlineDate>2020 Sep-Oct</MedlineDate></PubDate>"
        assert ss._pubmed_date(article(xml))[0] == 2020

    def test_electronic_date_is_preferred(self):
        node = ET.fromstring(
            "<PubmedArticle><MedlineCitation><Article>"
            "<ArticleDate><Year>2023</Year><Month>12</Month><Day>30</Day></ArticleDate>"
            "<Journal><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal>"
            "</Article></MedlineCitation></PubmedArticle>"
        )
        assert ss._pubmed_date(node) == (2023, "2023-12-30", "day")

    def test_no_date(self):
        node = ET.fromstring("<PubmedArticle><MedlineCitation><Article/></MedlineCitation></PubmedArticle>")
        assert ss._pubmed_date(node) == (None, None, None)


class TestOptionalRange:
    def test_dates(self):
        assert app_module._optional_range({"from_date": "2020-02-01", "to_date": "2021-03-04"}) == (
            "2020-02-01",
            "2021-03-04",
        )

    def test_bare_years_become_whole_year_bounds(self):
        assert app_module._optional_range({"from_year": 2020, "to_year": 2021}) == ("2020-01-01", "2021-12-31")

    def test_nothing_given(self):
        assert app_module._optional_range({}) == (None, None)

    @pytest.mark.parametrize(
        "body",
        [
            {"from_date": "2020-13-01"},
            {"from_date": "2020-1-1"},
            {"from_date": 2020},
            {"from_year": "2020"},
            {"from_year": True},
            {"from_year": 0},
            {"to_year": 10000},
            {"from_date": "2022-01-01", "to_date": "2021-01-01"},
        ],
    )
    def test_bad_values_raise(self, body):
        with pytest.raises(ValueError):
            app_module._optional_range(body)
