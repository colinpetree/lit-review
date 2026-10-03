"""Retracted papers and kinds of work that are not research papers."""

import xml.etree.ElementTree as ET
from contextlib import closing

import pytest

import db
import openalex
import search_sources as ss
from test_run_processing import ABSTRACT, process, scores_for


def paper(i, **extra):
    return {
        "id": f"W{i}",
        "source": "openalex",
        "title": f"Distinct paper title number {i}",
        "abstract": ABSTRACT,
        "year": 2022,
        "publication_date": "2022-05-01",
        "authors": [],
        **extra,
    }


def pubmed_article(pmid, types):
    kinds = "".join(f"<PublicationType>{t}</PublicationType>" for t in types)
    return ET.fromstring(
        f"<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article><ArticleTitle>Title {pmid}</ArticleTitle>"
        f"<Journal><JournalIssue><PubDate><Year>2022</Year></PubDate></JournalIssue></Journal>"
        f"<PublicationTypeList>{kinds}</PublicationTypeList></Article></MedlineCitation></PubmedArticle>"
    )


class TestSourcesReportIt:
    def test_openalex_says_whether_a_work_was_retracted_and_its_type(self):
        retracted = openalex._work_to_result({"id": "W1", "title": "t", "is_retracted": True, "type": "article"})
        plain = openalex._work_to_result({"id": "W2", "title": "t", "type": "review"})
        assert (retracted["is_retracted"], retracted["work_type"]) == (True, "article")
        assert (plain["is_retracted"], plain["work_type"], plain["is_review"]) == (False, "review", True)

    def test_pubmed_marks_the_retracted_paper_but_not_the_retraction_notice(self):
        retracted = ss._pubmed_result(pubmed_article("1", ["Journal Article", "Retracted Publication"]))
        assert retracted["is_retracted"] is True and retracted["work_type"] == "journal article"
        notice = ss._pubmed_result(pubmed_article("2", ["Journal Article", "Retraction of Publication"]))
        assert notice["is_retracted"] is False and notice["work_type"] == "retraction"

    @pytest.mark.parametrize(
        "kind, expected",
        [("Published Erratum", "erratum"), ("Comment", "comment"), ("Retraction of Publication", "retraction")],
    )
    def test_pubmed_non_research_types_get_the_common_names(self, kind, expected):
        assert ss._pubmed_result(pubmed_article("3", ["Letter", kind]))["work_type"] == expected

    def test_pubmed_with_no_types_has_none(self):
        assert ss._pubmed_result(pubmed_article("4", []))["work_type"] is None

    def test_scopus_erratum_and_retracted_documents(self):
        entry = {"dc:identifier": "SCOPUS_ID:1", "dc:title": "Erratum to something", "subtypeDescription": "Erratum"}
        assert ss._scopus_paper(entry)["work_type"] == "erratum"
        retracted = ss._scopus_paper({**entry, "subtypeDescription": "Retracted"})
        assert retracted["is_retracted"] is True
        assert ss._scopus_paper({**entry, "subtypeDescription": "Article"})["is_retracted"] is None


class TestNonResearchTypesAreSkippedAtIngest:
    def found(self, monkeypatch, *types):
        papers = [paper(i, work_type=t) for i, t in enumerate(types)]
        monkeypatch.setattr(openalex, "search_all", lambda *a, **k: (papers, len(papers)))
        return ss._search_openalex("coral", None, None)

    def test_front_matter_errata_retraction_notices_and_comments_are_dropped(self, monkeypatch):
        found = self.found(monkeypatch, "article", "paratext", "erratum", "retraction", "comment", "review", None)
        assert [r["work_type"] for r in found] == ["article", "review", None]

    def test_what_was_fetched_still_counts_the_skipped(self, monkeypatch):
        found = self.found(monkeypatch, "article", "erratum")
        assert (len(found), found.fetched, found.total, found.capped) == (1, 2, 2, None)

    def test_a_retracted_paper_itself_is_kept(self, monkeypatch):
        papers = [paper(1, work_type="article", is_retracted=True)]
        monkeypatch.setattr(openalex, "search_all", lambda *a, **k: (papers, 1))
        assert [r["is_retracted"] for r in ss._search_openalex("coral", None, None)] == [True]


class TestStored:
    def row(self, paper_id):
        with closing(db._connect()) as conn:
            return dict(conn.execute("SELECT is_retracted, work_type FROM paper WHERE id = ?", (paper_id,)).fetchone())

    def test_the_flags_are_saved_and_read_back(self):
        paper_id = db.get_or_create_paper(paper(1, is_retracted=True, work_type="article"))
        assert self.row(paper_id) == {"is_retracted": 1, "work_type": "article"}
        assert db.get_paper(paper_id)["is_retracted"] is True

    def test_a_source_that_does_not_say_stores_unknown(self):
        paper_id = db.get_or_create_paper(paper(2))
        assert self.row(paper_id) == {"is_retracted": None, "work_type": None}
        assert db.get_paper(paper_id)["is_retracted"] is False

    def test_a_retraction_learned_later_sticks_and_is_never_undone(self):
        paper_id = db.get_or_create_paper(paper(3, is_retracted=False))
        db.get_or_create_paper(paper(3, is_retracted=True))
        assert self.row(paper_id)["is_retracted"] == 1
        db.get_or_create_paper(paper(3, is_retracted=False))
        db.get_or_create_paper(paper(3))
        assert self.row(paper_id)["is_retracted"] == 1

    def test_an_unknown_becomes_known_and_the_type_is_only_filled_in(self):
        paper_id = db.get_or_create_paper(paper(4))
        db.get_or_create_paper(paper(4, is_retracted=False, work_type="article"))
        assert self.row(paper_id) == {"is_retracted": 0, "work_type": "article"}
        db.get_or_create_paper(paper(4, work_type="review"))
        assert self.row(paper_id)["work_type"] == "article"


def make_run(retracted=(2,), include_retracted=False, count=4):
    dataset_id = db.create_dataset("topic", ["q"], name="Dataset")
    ids = [db.get_or_create_paper(paper(i, is_retracted=i in retracted)) for i in range(count)]
    db.add_papers_to_dataset(dataset_id, ids)
    run_id = db.create_analysis_run(
        [dataset_id], "find coral papers", "anthropic", "claude-haiku-4-5", include_retracted=include_retracted
    )
    return dataset_id, ids, run_id


class TestRunsLeaveRetractedPapersOut:
    def test_by_default_a_retracted_paper_is_not_a_candidate_or_left_to_score(self):
        _, ids, run_id = make_run()
        candidates = {p["id"] for p in db.get_run_candidate_papers(run_id)}
        assert candidates == {ids[0], ids[1], ids[3]}
        assert {p["id"] for p in db.get_unscored_papers(run_id, 100)} == candidates
        assert db.count_unscored_papers(run_id) == 3

    def test_when_asked_for_it_is_scored_like_any_other(self):
        _, ids, run_id = make_run(include_retracted=True)
        assert {p["id"] for p in db.get_run_candidate_papers(run_id)} == set(ids)
        assert db.count_unscored_papers(run_id) == 4

    def test_the_results_list_counts_agree_with_what_is_scored(self):
        _, _, run_id = make_run()
        run = next(r for r in db.list_all_runs() if r["id"] == run_id)
        assert (run["paper_count"], run["unscored_count"]) == (3, 3)
        _, _, included = make_run(include_retracted=True)
        again = next(r for r in db.list_all_runs() if r["id"] == included)
        assert (again["paper_count"], again["unscored_count"]) == (4, 4)

    def test_how_many_were_left_out_is_reported(self):
        _, _, run_id = make_run(retracted=(1, 2))
        assert db.count_retracted_left_out(run_id) == 2
        _, _, included = make_run(retracted=(1, 2), include_retracted=True)
        assert db.count_retracted_left_out(included) == 0

    def test_an_excluded_retracted_paper_is_not_counted_as_left_out(self):
        dataset_id, ids, run_id = make_run()
        db.set_dataset_paper_excluded(dataset_id, ids[2], True)
        assert db.count_retracted_left_out(run_id) == 0

    def test_a_paper_in_two_datasets_is_judged_once(self):
        first, ids, run_id = make_run()
        second = db.create_dataset("other", ["q"], name="Other")
        db.add_papers_to_dataset(second, ids)
        with closing(db._connect()) as conn:
            conn.execute("INSERT INTO analysis_run_dataset (run_id, dataset_id) VALUES (?, ?)", (run_id, second))
            conn.commit()
        assert db.count_unscored_papers(run_id) == 3
        assert db.count_retracted_left_out(run_id) == 1

    def test_a_paper_scored_before_it_was_known_to_be_retracted_keeps_its_result(self):
        _, ids, run_id = make_run(retracted=())
        db.record_analysis_chunk(
            run_id, {ids[0]: {"score": 80, "rationale": "Good."}}, __import__("llm").Usage(1, 1, model="claude-haiku-4-5")
        )
        db.get_or_create_paper(paper(0, is_retracted=True))
        assert [p["id"] for p in db.get_run_results(run_id)] == [ids[0]]
        assert db.get_run_results(run_id)[0]["is_retracted"] is True

    def test_a_run_from_before_the_option_existed_keeps_scoring_everything(self):
        dataset_id, ids, run_id = make_run(include_retracted=False)
        conn = db.sqlite3.connect(str(db.DB_PATH))
        conn.execute("ALTER TABLE analysis_run DROP COLUMN include_retracted")
        conn.execute("PRAGMA user_version = 3")
        conn.commit()
        conn.close()
        db._ready_for = None
        db.ensure_ready()
        assert db.get_analysis_run(run_id)["include_retracted"] == 1
        assert db.count_unscored_papers(run_id) == 4


class TestRunsThroughTheApi:
    def create(self, client, dataset_id, **extra):
        return client.post(
            "/api/analysis-runs",
            json={"dataset_ids": [dataset_id], "grading_prompt": "find coral papers", "ai_api": "anthropic", **extra},
        )

    def test_the_default_leaves_retracted_papers_out_and_says_how_many(self, client):
        dataset_id, _, _ = make_run(retracted=(1, 2))
        run = self.create(client, dataset_id).get_json()
        assert run["include_retracted"] is False
        assert run["retracted_left_out"] == 2
        assert len(run["candidate_papers"]) == 2

    def test_include_retracted_scores_them(self, client):
        dataset_id, _, _ = make_run(retracted=(1, 2))
        run = self.create(client, dataset_id, include_retracted=True).get_json()
        assert (run["include_retracted"], run["retracted_left_out"], len(run["candidate_papers"])) == (True, 0, 4)

    @pytest.mark.parametrize("value", ["yes", 1, None, [True]])
    def test_a_value_that_is_not_true_or_false_is_refused(self, client, value):
        dataset_id, _, _ = make_run()
        response = self.create(client, dataset_id, include_retracted=value)
        assert response.status_code == 400
        assert "include_retracted" in response.get_json()["error"]

    def test_scoring_skips_retracted_papers_and_finishes(self, client, fake_llm):
        fake_llm.respond = lambda system, user, schema: scores_for(user)
        dataset_id, ids, _ = make_run(retracted=(1,))
        run = self.create(client, dataset_id).get_json()
        done = process(client, run["id"]).get_json()
        assert done["status"] == "completed"
        assert sorted(p["id"] for p in done["results"]) == sorted(set(ids) - {ids[1]})
        assert done["retracted_left_out"] == 1
