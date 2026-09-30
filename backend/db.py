"""SQLite persistence for datasets (retrieved paper pools) and analysis runs
(LLM relevance-scoring passes against a dataset) - see PLAN.md's Data model
(Phase 3) section for the full design rationale.

Stdlib sqlite3 only - deliberately no ORM until the schema grows enough to
want one (see PLAN.md's Dependencies section). Each call opens a short-lived
connection; _LOCK serializes write transactions since app.py runs Flask
threaded.
"""

import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import platformdirs

from credentials import APP_NAME

DB_PATH = Path(platformdirs.user_data_dir(APP_NAME)) / "lit_review.db"

_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    doi TEXT,
    title TEXT,
    abstract TEXT,
    year INTEGER,
    publication_date TEXT,
    citation_count INTEGER,
    venue TEXT,
    authors TEXT NOT NULL,
    url TEXT,
    is_review INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS dataset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    verbose_query TEXT NOT NULL,
    from_year INTEGER,
    to_year INTEGER,
    expanded_queries TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_paper (
    dataset_id INTEGER NOT NULL REFERENCES dataset(id),
    paper_id INTEGER NOT NULL REFERENCES paper(id),
    added_at TEXT NOT NULL,
    excluded_at TEXT,
    PRIMARY KEY (dataset_id, paper_id)
);

CREATE TABLE IF NOT EXISTS analysis_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grading_prompt TEXT NOT NULL,
    ai_api TEXT NOT NULL,
    ai_model TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS analysis_run_dataset (
    run_id INTEGER NOT NULL REFERENCES analysis_run(id),
    dataset_id INTEGER NOT NULL REFERENCES dataset(id),
    PRIMARY KEY (run_id, dataset_id)
);

CREATE TABLE IF NOT EXISTS analysis_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES analysis_run(id),
    paper_id INTEGER NOT NULL REFERENCES paper(id),
    rationale TEXT,
    score INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, paper_id)
);

CREATE TABLE IF NOT EXISTS llm_call (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purpose TEXT NOT NULL,
    dataset_id INTEGER REFERENCES dataset(id),
    run_id INTEGER REFERENCES analysis_run(id),
    ai_api TEXT NOT NULL,
    ai_model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    usd REAL NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _migrate(conn):
    """Idempotent ALTER-based migrations for columns added after a table's
    initial CREATE TABLE IF NOT EXISTS - CREATE TABLE IF NOT EXISTS only
    handles a table that doesn't exist yet at all, not one that exists with
    an older shape, and unlike earlier schema changes in this project's
    history, this one must never require deleting the user's existing data
    to pick up."""
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(paper)")}
    if "publication_date" not in existing_columns:
        conn.execute("ALTER TABLE paper ADD COLUMN publication_date TEXT")
        conn.commit()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def _dedupe_key(result):
    if result.get("doi"):
        return ("doi", result["doi"].lower())
    return ("title", (result.get("title") or "").strip().lower(), result.get("year"))


def _backfill_abstract_if_blank(conn, paper_id, existing_abstract, new_abstract):
    """Shared by both of get_or_create_paper()'s "found an existing row"
    branches (the initial dedupe-key lookup, and the lost-an-insert-race
    fallback) - never overwrites an existing non-blank abstract, only fills
    a gap. Caller commits; this only executes the UPDATE when needed."""
    if not (existing_abstract or "").strip() and new_abstract and new_abstract.strip():
        conn.execute("UPDATE paper SET abstract = ? WHERE id = ?", (new_abstract, paper_id))
        conn.commit()


def get_or_create_paper(result):
    """Insert a paper (in the shape openalex._work_to_result() returns) if no
    matching row exists yet, else return the existing row's id. Matching
    follows the same rule openalex.dedupe() applies in-memory: DOI first,
    else normalized (title, year) - not expressible as a single UNIQUE
    constraint, so it's a lookup-then-insert done under _LOCK.

    If a matching row already exists but has no abstract, and this occurrence
    of the paper does, backfill it - the same paper can turn up more than
    once (different expanded queries in one search, or eventually different
    source databases) and whichever occurrence is seen first otherwise wins
    forever, even if a later one is more complete. Abstracts are stored as
    '' (not NULL) when OpenAlex has none (openalex.reconstruct_abstract()
    returns '' for a missing/empty abstract_inverted_index) - a blank check
    has to treat both as "missing", not just NULL, or this would never
    trigger. Never overwrites an existing non-blank abstract with a
    different one - this only fills a gap, it doesn't reconcile conflicts."""
    with _LOCK, closing(_connect()) as conn:
        key = _dedupe_key(result)
        if key[0] == "doi":
            row = conn.execute(
                "SELECT id, abstract FROM paper WHERE lower(doi) = ?", (key[1],)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, abstract FROM paper WHERE doi IS NULL AND lower(trim(title)) = ? "
                "AND (year IS ? OR year = ?)",
                (key[1], key[2], key[2]),
            ).fetchone()
        if row:
            _backfill_abstract_if_blank(conn, row["id"], row["abstract"], result.get("abstract"))
            return row["id"]

        cur = conn.execute(
            """
            INSERT INTO paper
                (source, source_id, doi, title, abstract, year, publication_date,
                 citation_count, venue, authors, url, is_review, first_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source, source_id) DO NOTHING
            """,
            (
                result.get("source", "openalex"),
                result["id"],
                result.get("doi"),
                result.get("title"),
                result.get("abstract"),
                result.get("year"),
                result.get("publication_date"),
                result.get("citation_count", 0),
                result.get("venue"),
                json.dumps(result.get("authors") or []),
                result.get("url"),
                int(bool(result.get("is_review"))),
                _now(),
            ),
        )
        conn.commit()
        if cur.lastrowid and cur.rowcount:
            return cur.lastrowid
        # Lost a race with another insert of the same source/source_id, or the
        # in-memory result carries an OpenAlex id already seen under a
        # different dedupe key - either way, look the row up by source_id.
        # Same abstract-backfill applies here as the initial-lookup branch
        # above - a race is exactly the case where "whichever copy inserted
        # first wins forever" would otherwise silently drop a more complete
        # abstract from the copy that lost the race.
        row = conn.execute(
            "SELECT id, abstract FROM paper WHERE source = ? AND source_id = ?",
            (result.get("source", "openalex"), result["id"]),
        ).fetchone()
        _backfill_abstract_if_blank(conn, row["id"], row["abstract"], result.get("abstract"))
        return row["id"]


def _paper_row_to_dict(row):
    return {
        "id": row["paper_id"] if "paper_id" in row.keys() else row["id"],
        "title": row["title"],
        "abstract": row["abstract"],
        "year": row["year"],
        "publication_date": row["publication_date"] if "publication_date" in row.keys() else None,
        "citation_count": row["citation_count"],
        "doi": row["doi"],
        "url": row["url"],
        "venue": row["venue"],
        "authors": json.loads(row["authors"]),
        "is_review": bool(row["is_review"]),
    }


def get_paper(paper_id):
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM paper WHERE id = ?", (paper_id,)).fetchone()
        return _paper_row_to_dict(row) if row else None


# Fields the user is allowed to hand-edit - the paper table's identity
# columns (source, source_id, first_seen_at) are deliberately excluded.
EDITABLE_PAPER_FIELDS = {"title", "abstract", "doi", "year", "citation_count", "venue", "url", "authors"}


def update_paper(paper_id, fields):
    """Partial update of an existing paper row - lets the user correct or
    fill in data OpenAlex didn't have, most commonly a missing abstract
    (papers are shared globally across every dataset that pulled them in,
    so an edit here is visible everywhere that paper appears, which is the
    point - one corrected copy, not one per dataset). Unknown keys are
    silently ignored; only EDITABLE_PAPER_FIELDS may be touched."""
    updates = {k: v for k, v in fields.items() if k in EDITABLE_PAPER_FIELDS}
    if not updates:
        return
    if "authors" in updates:
        updates["authors"] = json.dumps(updates["authors"] or [])
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with _LOCK, closing(_connect()) as conn:
        conn.execute(f"UPDATE paper SET {set_clause} WHERE id = ?", (*updates.values(), paper_id))
        conn.commit()


def create_dataset(verbose_query, expanded_queries, from_year=None, to_year=None, name=None):
    with _LOCK, closing(_connect()) as conn:
        cur = conn.execute(
            """
            INSERT INTO dataset (name, verbose_query, from_year, to_year, expanded_queries, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, verbose_query, from_year, to_year, json.dumps(expanded_queries), _now()),
        )
        conn.commit()
        return cur.lastrowid


def add_papers_to_dataset(dataset_id, paper_ids):
    with _LOCK, closing(_connect()) as conn:
        now = _now()
        conn.executemany(
            "INSERT OR IGNORE INTO dataset_paper (dataset_id, paper_id, added_at) VALUES (?, ?, ?)",
            [(dataset_id, paper_id, now) for paper_id in paper_ids],
        )
        conn.commit()


def find_dataset(verbose_query, from_year=None, to_year=None):
    """Look up an existing dataset with the same question + year filters, so
    resubmitting an identical search reuses it instead of re-running
    expansion/retrieval (see PLAN.md's reuse-first rule for POST /api/datasets)."""
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT id FROM dataset
            WHERE verbose_query = ?
              AND (from_year IS ? OR from_year = ?)
              AND (to_year IS ? OR to_year = ?)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (verbose_query, from_year, from_year, to_year, to_year),
        ).fetchone()
        return row["id"] if row else None


def list_datasets():
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT d.id, d.name, d.verbose_query, d.from_year, d.to_year, d.created_at,
                   COUNT(dp.paper_id) AS paper_count,
                   MIN(p.year) AS oldest_year,
                   MAX(p.year) AS newest_year,
                   MAX(p.publication_date) AS newest_publication_date
            FROM dataset d
            LEFT JOIN dataset_paper dp ON dp.dataset_id = d.id AND dp.excluded_at IS NULL
            LEFT JOIN paper p ON p.id = dp.paper_id
            GROUP BY d.id
            ORDER BY d.created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_dataset(dataset_id):
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM dataset WHERE id = ?", (dataset_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["expanded_queries"] = json.loads(d["expanded_queries"])
        return d


def get_dataset_papers(dataset_id, include_excluded=False):
    query = """
        SELECT p.*, dp.paper_id, dp.excluded_at
        FROM dataset_paper dp
        JOIN paper p ON p.id = dp.paper_id
        WHERE dp.dataset_id = ?
    """
    if not include_excluded:
        query += " AND dp.excluded_at IS NULL"
    with closing(_connect()) as conn:
        rows = conn.execute(query, (dataset_id,)).fetchall()
        return [_paper_row_to_dict(row) for row in rows]


def exclude_dataset_paper(dataset_id, paper_id):
    with _LOCK, closing(_connect()) as conn:
        conn.execute(
            "UPDATE dataset_paper SET excluded_at = ? WHERE dataset_id = ? AND paper_id = ?",
            (_now(), dataset_id, paper_id),
        )
        conn.commit()


def create_analysis_run(dataset_ids, grading_prompt, ai_api, ai_model):
    """A run can span several datasets - scores the union of their papers in
    one pass. dataset_ids must be non-empty (validated by the caller)."""
    with _LOCK, closing(_connect()) as conn:
        cur = conn.execute(
            """
            INSERT INTO analysis_run (grading_prompt, ai_api, ai_model, status, created_at)
            VALUES (?, ?, ?, 'running', ?)
            """,
            (grading_prompt, ai_api, ai_model, _now()),
        )
        run_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO analysis_run_dataset (run_id, dataset_id) VALUES (?, ?)",
            [(run_id, dataset_id) for dataset_id in dataset_ids],
        )
        conn.commit()
        return run_id


def get_run_datasets(run_id):
    """The datasets feeding a run, for display (e.g. "built from: X, Y")."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT d.id, d.verbose_query, d.created_at
            FROM analysis_run_dataset ard
            JOIN dataset d ON d.id = ard.dataset_id
            WHERE ard.run_id = ?
            ORDER BY d.created_at
            """,
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]




def list_all_runs():
    """All runs with their linked dataset names, status, and cost, for the
    Past Results list page."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT run.id, run.grading_prompt, run.ai_api, run.ai_model, run.status,
                   run.created_at, run.completed_at,
                   GROUP_CONCAT(DISTINCT d.verbose_query) AS dataset_names,
                   (SELECT COALESCE(SUM(usd), 0) FROM llm_call WHERE run_id = run.id)
                   + (SELECT COALESCE(SUM(usd), 0) FROM llm_call
                        WHERE run_id IS NULL
                          AND dataset_id IN (
                              SELECT dataset_id FROM analysis_run_dataset WHERE run_id = run.id
                          )) AS cost
            FROM analysis_run run
            JOIN analysis_run_dataset ard ON ard.run_id = run.id
            JOIN dataset d ON d.id = ard.dataset_id
            GROUP BY run.id
            ORDER BY run.created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_analysis_run(run_id):
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM analysis_run WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


def get_run_results(run_id):
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT p.*, ar.paper_id, ar.rationale, ar.score
            FROM analysis_result ar
            JOIN paper p ON p.id = ar.paper_id
            WHERE ar.run_id = ?
            ORDER BY ar.score DESC
            """,
            (run_id,),
        ).fetchall()
        results = []
        for row in rows:
            paper = _paper_row_to_dict(row)
            paper["score"] = row["score"]
            paper["rationale"] = row["rationale"]
            results.append(paper)
        return results


def _run_papers_subquery(run_id):
    """A run's candidate paper ids: the union of every linked dataset's
    non-excluded papers, deduped (a paper can appear in more than one
    selected dataset) - included if at least one of its dataset_paper rows
    among the run's datasets isn't excluded (excluded via dataset A but
    present via dataset B still counts as included)."""
    return (
        """
        SELECT dp.paper_id
        FROM dataset_paper dp
        JOIN analysis_run_dataset ard ON ard.dataset_id = dp.dataset_id
        WHERE ard.run_id = ?
        GROUP BY dp.paper_id
        HAVING SUM(CASE WHEN dp.excluded_at IS NULL THEN 1 ELSE 0 END) > 0
        """,
        (run_id,),
    )


def get_run_candidate_papers(run_id):
    """Every candidate paper for a run (scored or not) - the full list a
    run's results get merged onto for progressive/resumed display."""
    subquery, params = _run_papers_subquery(run_id)
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"""
            SELECT p.*, included.paper_id AS paper_id
            FROM ({subquery}) included
            JOIN paper p ON p.id = included.paper_id
            """,
            params,
        ).fetchall()
        return [_paper_row_to_dict(row) for row in rows]


def get_unscored_papers(run_id, limit):
    """This run's candidate papers that have no analysis_result yet - the
    resumable-chunk query PLAN.md describes: calling /process again after an
    interruption just re-selects this same set."""
    subquery, params = _run_papers_subquery(run_id)
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"""
            SELECT p.*, included.paper_id AS paper_id
            FROM ({subquery}) included
            JOIN paper p ON p.id = included.paper_id
            LEFT JOIN analysis_result ar ON ar.run_id = ? AND ar.paper_id = included.paper_id
            WHERE ar.id IS NULL
            LIMIT ?
            """,
            (*params, run_id, limit),
        ).fetchall()
        return [_paper_row_to_dict(row) for row in rows]


def count_unscored_papers(run_id):
    subquery, params = _run_papers_subquery(run_id)
    with closing(_connect()) as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM ({subquery}) included
            LEFT JOIN analysis_result ar ON ar.run_id = ? AND ar.paper_id = included.paper_id
            WHERE ar.id IS NULL
            """,
            (*params, run_id),
        ).fetchone()
        return row["total"]


def record_analysis_chunk(run_id, scores, usage):
    """Write a scored chunk's analysis_result rows + its llm_call row in one
    transaction, only ever called after the LLM call already succeeded - so
    an interrupted run never leaves a half-written chunk behind. Scoring
    llm_call rows get dataset_id = NULL - a run can span several datasets,
    so there's no single one to attribute the call to; get_run_cost() sums
    scoring cost by run_id alone."""
    with _LOCK, closing(_connect()) as conn:
        now = _now()
        conn.executemany(
            """
            INSERT INTO analysis_result (run_id, paper_id, rationale, score, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (run_id, paper_id) DO UPDATE SET
                rationale = excluded.rationale, score = excluded.score
            """,
            [
                (run_id, paper_id, scored["rationale"], scored["score"], now)
                for paper_id, scored in scores.items()
            ],
        )
        run = conn.execute("SELECT ai_api, ai_model FROM analysis_run WHERE id = ?", (run_id,)).fetchone()
        conn.execute(
            """
            INSERT INTO llm_call
                (purpose, dataset_id, run_id, ai_api, ai_model, input_tokens, output_tokens, usd, created_at)
            VALUES ('scoring', NULL, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, run["ai_api"], run["ai_model"], usage.input_tokens, usage.output_tokens, usage.usd, now),
        )
        conn.commit()


def record_llm_call(purpose, ai_api, ai_model, usage, dataset_id=None, run_id=None):
    with _LOCK, closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO llm_call
                (purpose, dataset_id, run_id, ai_api, ai_model, input_tokens, output_tokens, usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (purpose, dataset_id, run_id, ai_api, ai_model, usage.input_tokens, usage.output_tokens, usage.usd, _now()),
        )
        conn.commit()


def mark_run_completed(run_id):
    with _LOCK, closing(_connect()) as conn:
        conn.execute(
            "UPDATE analysis_run SET status = 'completed', completed_at = ? WHERE id = ?",
            (_now(), run_id),
        )
        conn.commit()


def get_cost(dataset_id=None, run_id=None):
    """Sum of llm_call.usd matching whichever filter(s) are given. Callers
    that want a run's *total* cost (scoring + the dataset's one expansion
    call) must add two separate get_cost() calls together - see
    get_run_cost() below - since expansion/scoring calls sit on different
    columns and OR-ing them here would double count when both ids are given."""
    with closing(_connect()) as conn:
        if run_id is not None:
            row = conn.execute("SELECT SUM(usd) AS total FROM llm_call WHERE run_id = ?", (run_id,)).fetchone()
        elif dataset_id is not None:
            row = conn.execute(
                "SELECT SUM(usd) AS total FROM llm_call WHERE dataset_id = ? AND run_id IS NULL",
                (dataset_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT SUM(usd) AS total FROM llm_call").fetchone()
        return row["total"] or 0.0


def get_run_cost(run_id):
    """This run's own scoring cost plus the expansion cost of every dataset
    linked to it - the two halves of what the UI calls "cost of this run"."""
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT COALESCE(SUM(usd), 0) FROM llm_call WHERE run_id = ?)
                + (SELECT COALESCE(SUM(usd), 0) FROM llm_call
                     WHERE run_id IS NULL
                       AND dataset_id IN (
                           SELECT dataset_id FROM analysis_run_dataset WHERE run_id = ?
                       )) AS total
            """,
            (run_id, run_id),
        ).fetchone()
        return row["total"] or 0.0
