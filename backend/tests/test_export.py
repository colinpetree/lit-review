"""Exporting papers as CSV, RIS and BibTeX."""

import csv
import io
import re

import pytest

import db
import export
import llm

PAPER = {
    "id": 7,
    "title": "Coral & coral: 50% faster_growth",
    "authors": ["Ada Lovelace", "Møller, Åsa"],
    "year": 2024,
    "publication_date": "2024-03-05",
    "venue": "Journal of {Coral}",
    "doi": "https://doi.org/10.1000/abc",
    "url": "https://example.org/p",
    "abstract": "Line one.\nLine two.",
    "read": True,
    "source": "openalex",
}
SCORED = {**PAPER, "score": 82, "rationale": "Directly on topic.", "relevance": "relevant"}


def rows(data):
    text = data.decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.DictReader(io.StringIO(text[1:], newline="")))


class TestCsv:
    def test_a_row_per_paper_with_a_bare_doi_and_a_byte_order_mark(self):
        (row,) = rows(export.to_csv([PAPER]))
        assert row["title"] == PAPER["title"]
        assert row["authors"] == "Ada Lovelace; Møller, Åsa"
        assert row["doi"] == "10.1000/abc"
        assert row["read"] == "yes" and row["source"] == "openalex"
        assert row["abstract"] == "Line one.\nLine two."
        assert "score" not in row

    def test_a_runs_export_has_the_score_columns(self):
        (row,) = rows(export.to_csv([SCORED], scored=True))
        assert (row["score"], row["rationale"], row["relevance"]) == ("82", "Directly on topic.", "relevant")

    def test_a_retracted_paper_is_marked(self):
        rows_ = rows(export.to_csv([PAPER, {**PAPER, "is_retracted": True}]))
        assert [r["retracted"] for r in rows_] == ["no", "yes"]

    def test_lines_end_with_crlf(self):
        assert export.to_csv([PAPER]).count(b"\r\n") >= 2

    @pytest.mark.parametrize("start", ["=", "+", "-", "@", "\t", "\r"])
    def test_text_a_spreadsheet_would_run_as_a_formula_is_made_plain_text(self, start):
        (row,) = rows(export.to_csv([{**PAPER, "title": f"{start}HYPERLINK(1)", "abstract": f"{start}x"}]))
        assert row["title"] == f"'{start}HYPERLINK(1)"
        assert row["abstract"] == f"'{start}x"

    def test_a_number_is_not_turned_into_text(self):
        (row,) = rows(export.to_csv([{**SCORED, "score": -3}], scored=True))
        assert row["score"] == "-3"

    def test_missing_fields_are_empty_cells(self):
        (row,) = rows(export.to_csv([{"id": 1, "title": "Bare"}]))
        assert row["title"] == "Bare" and row["year"] == "" and row["authors"] == "" and row["read"] == "no"


def parse_ris(data):
    records, current = [], []
    for line in data.decode("utf-8").split("\r\n"):
        match = re.fullmatch(r"([A-Z][A-Z0-9])  - ?(.*)", line)
        if not match:
            assert line == ""
            continue
        current.append(match.groups())
        if match.group(1) == "ER":
            records.append(current)
            current = []
    assert not current
    return records


class TestRis:
    def test_a_record_with_one_author_tag_each_and_no_line_breaks_in_values(self):
        (record,) = parse_ris(export.to_ris([SCORED]))
        tags = [t for t, _ in record]
        assert tags[0] == "TY" and tags[-1] == "ER"
        assert [v for t, v in record if t == "AU"] == ["Ada Lovelace", "Møller, Åsa"]
        values = dict(record)
        assert values["TI"] == PAPER["title"] and values["PY"] == "2024" and values["DA"] == "2024/03/05"
        assert values["DO"] == "10.1000/abc"
        assert values["AB"] == "Line one. Line two."
        assert values["N1"] == "Relevance score: 82. Directly on topic."

    def test_a_retracted_paper_is_flagged_in_the_note_with_its_score(self):
        (record,) = parse_ris(export.to_ris([{**SCORED, "is_retracted": True}]))
        assert dict(record)["N1"] == "RETRACTED. Relevance score: 82. Directly on topic."
        (record,) = parse_ris(export.to_ris([{**PAPER, "is_retracted": True}]))
        assert dict(record)["N1"] == "RETRACTED."

    def test_a_value_that_looks_like_a_tag_stays_inside_its_value(self):
        (record,) = parse_ris(export.to_ris([{**PAPER, "abstract": "text\nER  - \nTY  - BOOK"}]))
        assert [t for t, _ in record].count("TY") == 1
        assert dict(record)["AB"] == "text ER - TY - BOOK"

    def test_every_paper_is_its_own_record_and_blank_fields_are_left_out(self):
        records = parse_ris(export.to_ris([PAPER, {"id": 2, "title": "Bare"}]))
        assert len(records) == 2
        assert [t for t, _ in records[1]] == ["TY", "TI", "ER"]


class TestBibtex:
    def test_special_characters_are_escaped_in_one_pass(self):
        text = export.to_bibtex([PAPER]).decode("utf-8")
        assert r"title = {{Coral \& coral: 50\% faster\_growth}}" in text
        assert r"journal = {Journal of \{Coral\}}" in text
        assert "abstract = {Line one. Line two.}" in text

    def test_a_backslash_is_not_escaped_twice(self):
        text = export.to_bibtex([{**PAPER, "title": r"a\b {c}"}]).decode("utf-8")
        assert r"{{a\textbackslash{}b \{c\}}}" in text

    def test_the_key_is_ascii_and_unique_by_paper_id(self):
        text = export.to_bibtex([{**PAPER, "authors": ["Åsa Møller"]}, {**PAPER, "id": 8, "authors": ["Åsa Møller"]}]).decode()
        keys = re.findall(r"@article\{([^,]+),", text)
        assert keys == ["mller2024-7", "mller2024-8"]

    def test_a_paper_with_no_authors_or_year_still_gets_a_valid_entry(self):
        text = export.to_bibtex([{"id": 3, "title": "Bare"}]).decode("utf-8")
        assert text.startswith("@article{paper-3,") and "author" not in text
        assert text.rstrip().endswith("}")

    def test_authors_are_joined_with_and(self):
        assert "author = {Ada Lovelace and Møller, Åsa}" in export.to_bibtex([PAPER]).decode("utf-8")


class TestFilename:
    def test_plain_words_and_the_date(self):
        assert export.safe_filename("Coral Reef Bleaching!", "csv", "2026-10-03") == "coral-reef-bleaching-2026-10-03.csv"

    def test_nothing_unsafe_survives(self):
        name = export.safe_filename('..\\/"; evil\r\nHeader: x é', "ris", "2026-10-03")
        assert re.fullmatch(r"[a-z0-9-]+\.ris", name)

    def test_a_blank_or_missing_name_gets_a_default(self):
        assert export.safe_filename(None, "bib", "2026-10-03") == "papers-2026-10-03.bib"
        assert export.safe_filename("???", "bib", "2026-10-03") == "papers-2026-10-03.bib"

    def test_a_long_name_is_cut(self):
        assert len(export.safe_filename("word " * 100, "csv", "2026-10-03")) < 80


def paper(i, **extra):
    return {"id": f"W{i}", "title": f"Paper {i}", "abstract": "An abstract that is long enough to count. " * 3, "year": 2020, **extra}


@pytest.fixture
def run_with_results():
    dataset_id = db.create_dataset("topic", ["q"], name="Coral Reefs")
    ids = [db.get_or_create_paper(paper(i)) for i in range(4)]
    db.add_papers_to_dataset(dataset_id, ids)
    run_id = db.create_analysis_run([dataset_id], "find coral papers", "anthropic", "claude-haiku-4-5")
    db.record_analysis_chunk(
        run_id,
        {ids[0]: {"score": 90, "rationale": "Best"}, ids[1]: {"score": 40, "rationale": "Meh"}, ids[2]: {"score": 70, "rationale": "Good"}},
        llm.Usage(10, 5, model="claude-haiku-4-5", provider="anthropic"),
    )
    return {"dataset": dataset_id, "run": run_id, "ids": ids}


class TestRoutes:
    def post(self, client, path, body):
        return client.post(path, json=body)

    def test_a_dataset_export_downloads_with_a_safe_name_and_type(self, client, run_with_results):
        r = self.post(client, f"/api/datasets/{run_with_results['dataset']}/export", {"format": "csv"})
        assert r.status_code == 200
        assert r.headers["Content-Disposition"].startswith('attachment; filename="coral-reefs-')
        assert r.headers["Content-Disposition"].endswith('.csv"')
        assert r.headers["Content-Type"].startswith("text/csv")
        assert len(rows(r.data)) == 4

    def test_a_dataset_export_leaves_out_excluded_papers(self, client, run_with_results):
        db.set_dataset_paper_excluded(run_with_results["dataset"], run_with_results["ids"][0], True)
        r = self.post(client, f"/api/datasets/{run_with_results['dataset']}/export", {"format": "ris"})
        assert len(parse_ris(r.data)) == 3

    def test_a_run_export_has_scores_for_the_scored_papers_only(self, client, run_with_results):
        r = self.post(client, f"/api/analysis-runs/{run_with_results['run']}/export", {"format": "csv"})
        got = rows(r.data)
        assert [row["score"] for row in got] == ["90", "70", "40"]

    def test_the_paper_ids_chosen_are_exported_in_the_order_sent(self, client, run_with_results):
        ids = run_with_results["ids"]
        r = self.post(
            client, f"/api/analysis-runs/{run_with_results['run']}/export", {"format": "csv", "paper_ids": [ids[1], ids[0]]}
        )
        assert [row["title"] for row in rows(r.data)] == ["Paper 1", "Paper 0"]

    def test_an_unknown_or_repeated_id_is_ignored(self, client, run_with_results):
        ids = run_with_results["ids"]
        r = self.post(
            client,
            f"/api/datasets/{run_with_results['dataset']}/export",
            {"format": "csv", "paper_ids": [ids[2], 99999, ids[2]]},
        )
        assert [row["title"] for row in rows(r.data)] == ["Paper 2"]

    def test_only_unknown_ids_leaves_nothing_to_export(self, client, run_with_results):
        r = self.post(client, f"/api/datasets/{run_with_results['dataset']}/export", {"format": "csv", "paper_ids": [99999]})
        assert r.status_code == 400 and "no papers" in r.get_json()["error"]

    def test_a_run_with_no_results_has_nothing_to_export(self, client, run_with_results):
        dataset_id = db.create_dataset("t", ["q"], name="Empty")
        run_id = db.create_analysis_run([dataset_id], "g", "anthropic", "claude-haiku-4-5")
        assert self.post(client, f"/api/analysis-runs/{run_id}/export", {"format": "bibtex"}).status_code == 400

    def test_unknown_run_and_dataset_are_404(self, client):
        assert self.post(client, "/api/analysis-runs/999/export", {"format": "csv"}).status_code == 404
        assert self.post(client, "/api/datasets/999/export", {"format": "csv"}).status_code == 404

    def test_a_foreign_origin_is_refused_before_anything_is_built(self, client, run_with_results):
        r = client.post(
            f"/api/datasets/{run_with_results['dataset']}/export",
            json={"format": "csv"},
            headers={"Origin": "https://evil.example"},
        )
        assert r.status_code == 403
