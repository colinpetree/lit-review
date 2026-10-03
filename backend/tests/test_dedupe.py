from contextlib import closing

import db
import openalex


def result(paper_id, title="Coral growth modeling", doi=None, year=2020, abstract="", source="openalex"):
    return {
        "id": paper_id,
        "source": source,
        "title": title,
        "doi": doi,
        "year": year,
        "abstract": abstract,
        "authors": ["A. Author"],
    }


class TestDedupe:
    def test_same_doi_merges_regardless_of_case(self):
        a = result("W1", doi="https://doi.org/10.1/ABC")
        b = result("W2", doi="https://doi.org/10.1/abc", title="Another title")
        assert openalex.dedupe([[a], [b]]) == [a]

    def test_same_title_and_year_merge_without_a_doi(self):
        a = result("W1", title="Coral Growth Modeling")
        b = result("W2", title="  coral growth modeling ")
        assert len(openalex.dedupe([[a, b]])) == 1

    def test_same_title_in_different_years_stay_separate(self):
        assert len(openalex.dedupe([[result("W1", year=2019), result("W2", year=2020)]])) == 2

    def test_a_later_abstract_fills_a_blank_one(self):
        a = result("W1", doi="https://doi.org/10.1/x", abstract="")
        b = result("W2", doi="https://doi.org/10.1/x", abstract="Real abstract text.")
        assert openalex.dedupe([[a], [b]])[0]["abstract"] == "Real abstract text."

    def test_an_existing_abstract_is_not_replaced(self):
        a = result("W1", doi="https://doi.org/10.1/x", abstract="First.")
        b = result("W2", doi="https://doi.org/10.1/x", abstract="Second.")
        assert openalex.dedupe([[a], [b]])[0]["abstract"] == "First."

    def test_first_occurrence_wins_and_order_is_kept(self):
        a, b, c = result("W1", title="One"), result("W2", title="Two"), result("W3", title="One")
        assert [r["id"] for r in openalex.dedupe([[a, b], [c]])] == ["W1", "W2"]

    def test_trailing_period_and_markup_do_not_split_a_paper(self):
        pubmed = result("1", title="Coral growth modeling.", source="pubmed")
        alex = result("W1", title="Coral <i>growth</i> modeling")
        assert len(openalex.dedupe([[alex], [pubmed]])) == 1


class TestGetOrCreatePaper:
    def count(self):
        with closing(db._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM paper").fetchone()[0]

    def test_same_doi_from_two_sources_is_one_paper(self):
        first = db.get_or_create_paper(result("W1", doi="https://doi.org/10.1/x"))
        second = db.get_or_create_paper(result("123", doi="https://doi.org/10.1/X", source="pubmed"))
        assert first == second
        assert self.count() == 1

    def test_repeated_insert_returns_the_same_id(self):
        paper = result("W1", doi="https://doi.org/10.1/x")
        assert db.get_or_create_paper(paper) == db.get_or_create_paper(paper)

    def test_blank_abstract_is_backfilled(self):
        paper_id = db.get_or_create_paper(result("W1", doi="https://doi.org/10.1/x", abstract=""))
        db.get_or_create_paper(result("W2", doi="https://doi.org/10.1/x", abstract="Filled in later."))
        assert db.get_paper(paper_id)["abstract"] == "Filled in later."

    def test_existing_abstract_is_never_overwritten(self):
        paper_id = db.get_or_create_paper(result("W1", doi="https://doi.org/10.1/x", abstract="Original."))
        db.get_or_create_paper(result("W2", doi="https://doi.org/10.1/x", abstract="Different."))
        assert db.get_paper(paper_id)["abstract"] == "Original."

    def test_no_doi_matches_on_title_and_year(self):
        first = db.get_or_create_paper(result("W1", title="Coral Growth Modeling", year=2020))
        second = db.get_or_create_paper(result("W2", title=" coral growth modeling", year=2020))
        assert first == second

    def test_no_doi_different_year_is_a_different_paper(self):
        first = db.get_or_create_paper(result("W1", year=2019))
        second = db.get_or_create_paper(result("W2", year=2020))
        assert first != second

    def test_same_source_id_does_not_create_a_second_row(self):
        db.get_or_create_paper(result("W1", title="Original title"))
        db.get_or_create_paper(result("W1", title="Different title", year=2025))
        assert self.count() == 1

    def test_trailing_period_does_not_split_a_paper(self):
        first = db.get_or_create_paper(result("W1", title="Coral growth modeling"))
        second = db.get_or_create_paper(result("1", title="Coral growth modeling.", source="pubmed"))
        assert first == second
