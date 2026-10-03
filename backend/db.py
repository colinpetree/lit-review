"""SQLite persistence for datasets (retrieved paper pools) and analysis runs
(LLM relevance-scoring passes against a dataset) - see PLAN.md's Data model
(Phase 3) section for the full design rationale.

Stdlib sqlite3 only - deliberately no ORM until the schema grows enough to
want one (see PLAN.md's Dependencies section). Each call opens a short-lived
connection; _LOCK serializes write transactions since app.py runs Flask
threaded.
"""

import json
import logging
import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import platformdirs

from credentials import APP_NAME
from openalex import dedupe_key
from source_http import safe_url
from title_match import title_key

# LIT_REVIEW_DATA_DIR is for development and tests only, so they never touch the
# real database.
DB_PATH = Path(os.environ.get("LIT_REVIEW_DATA_DIR") or platformdirs.user_data_dir(APP_NAME)) / "lit_review.db"

_LOCK = threading.Lock()

# Bumped when the schema changes in a way an older copy of the app could not read.
# 1 = everything up to the title_key column and the indexes. A database stamped
# higher than this was made by a newer version and is not opened.
SCHEMA_VERSION = 1

_INIT_LOCK = threading.Lock()
_ready_for = None  # the DB_PATH that has been created, migrated and tuned


class DatabaseTooNew(sqlite3.DatabaseError):
    pass

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

CREATE TABLE IF NOT EXISTS prompt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    title_pending INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS prompt_example (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES prompt(id),
    paper_id INTEGER NOT NULL REFERENCES paper(id),
    source_run_id INTEGER REFERENCES analysis_run(id),
    score INTEGER NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (prompt_id, paper_id)
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


def _placeholder_title(text):
    """Stand-in title (first few words of the text) for a prompt or dataset."""
    return " ".join(text.split()[:4])[:60] or "Untitled"


MAX_RUN_NAME_CHARS = 120


def _unique_run_name(conn, base, exclude_run_id=None):
    """`base`, or `base (2)`, `base (3)`... when another live (not deleted) run
    already has the name. Case-insensitive. Callers hold _LOCK, so two writers
    can't pick the same name."""
    base = " ".join((base or "").split())[:MAX_RUN_NAME_CHARS] or "Untitled"
    taken = {
        row["name"].lower()
        for row in conn.execute(
            "SELECT name FROM analysis_run WHERE deleted_at IS NULL AND name IS NOT NULL AND id != ?",
            (exclude_run_id or -1,),
        )
    }
    if base.lower() not in taken:
        return base
    n = 2
    while True:
        suffix = f" ({n})"
        candidate = base[: MAX_RUN_NAME_CHARS - len(suffix)] + suffix
        if candidate.lower() not in taken:
            return candidate
        n += 1


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
    # Which source an abstract was looked up from after the fact (NULL for
    # abstracts that came with the paper or were typed in by hand).
    if "abstract_source" not in existing_columns:
        conn.execute("ALTER TABLE paper ADD COLUMN abstract_source TEXT")
        conn.commit()
    # When an abstract lookup last completed for a paper without finding one,
    # so the automatic lookup on opening a dataset doesn't retry it every time.
    if "abstract_checked_at" not in existing_columns:
        conn.execute("ALTER TABLE paper ADD COLUMN abstract_checked_at TEXT")
        conn.commit()
    # When the user marked a paper read (NULL = unread). On the paper itself,
    # not a dataset or run, so it follows the paper everywhere it shows up.
    if "read_at" not in existing_columns:
        conn.execute("ALTER TABLE paper ADD COLUMN read_at TEXT")
        conn.commit()
    # The title reduced to what identifies the paper across sources
    # (title_match.title_key), the dedupe key for papers without a DOI.
    if "title_key" not in existing_columns:
        conn.execute("ALTER TABLE paper ADD COLUMN title_key TEXT")
        conn.commit()
    _backfill_title_keys(conn)

    # The user's relevance call on one run's result: 'relevant', 'not_relevant',
    # or NULL for neutral. Per result because relevance depends on the run's
    # research criteria.
    result_columns = {row["name"] for row in conn.execute("PRAGMA table_info(analysis_result)")}
    if "relevance" not in result_columns:
        conn.execute("ALTER TABLE analysis_result ADD COLUMN relevance TEXT")
        conn.commit()

    # Soft delete: hidden from the UI but kept, since scored runs are meant to
    # stay available as examples for reusable prompts.
    for table in ("dataset", "analysis_run"):
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "deleted_at" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN deleted_at TEXT")
            conn.commit()

    # Which paper sources a dataset was retrieved from (JSON list of ids).
    # NULL on datasets from before sources could be chosen: all OpenAlex.
    dataset_columns = {row["name"] for row in conn.execute("PRAGMA table_info(dataset)")}
    if "sources" not in dataset_columns:
        conn.execute("ALTER TABLE dataset ADD COLUMN sources TEXT")
        conn.commit()

    # The search's publication date bounds ("YYYY-MM-DD"), replacing the bare
    # years in from_year/to_year (still filled in, as the year of each bound).
    # Datasets from before get a bound from their year: Jan 1 / Dec 31.
    for column in ("from_date", "to_date"):
        if column not in dataset_columns:
            conn.execute(f"ALTER TABLE dataset ADD COLUMN {column} TEXT")
    conn.execute("UPDATE dataset SET from_date = printf('%04d-01-01', from_year) WHERE from_date IS NULL AND from_year IS NOT NULL")
    conn.execute("UPDATE dataset SET to_date = printf('%04d-12-31', to_year) WHERE to_date IS NULL AND to_year IS NOT NULL")
    conn.commit()

    # Datasets from before titles existed get the first few words of their
    # topic as a title (editable later). New datasets always set a name.
    if "name" not in dataset_columns:
        conn.execute("ALTER TABLE dataset ADD COLUMN name TEXT")
        conn.commit()
    for row in conn.execute("SELECT id, verbose_query FROM dataset WHERE name IS NULL").fetchall():
        conn.execute(
            "UPDATE dataset SET name = ? WHERE id = ?",
            (_placeholder_title(row["verbose_query"]), row["id"]),
        )
    conn.commit()

    # A run keeps its own copy of the prompt text (grading_prompt) and of the
    # examples it was scored with (examples_snapshot), so editing a prompt
    # later never changes what an old run's results mean.
    run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(analysis_run)")}
    # name: the run's own, unique (among live runs) and renamable title.
    # name_auto: still the placeholder from a run that created its own prompt,
    # so the AI-generated prompt title replaces it unless the user renamed first.
    for column, ddl in (
        ("prompt_id", "INTEGER"),
        ("examples_snapshot", "TEXT"),
        ("name", "TEXT"),
        ("name_auto", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if column not in run_columns:
            conn.execute(f"ALTER TABLE analysis_run ADD COLUMN {column} {ddl}")
            conn.commit()

    # Runs from before saved prompts existed get a prompt made from their
    # grading text. New runs always set prompt_id, so a NULL one is legacy.
    # If every run that used the text is already deleted, the prompt is made
    # hidden too, so a deleted run doesn't resurface as a listed prompt.
    legacy = conn.execute(
        """
        SELECT grading_prompt, MIN(created_at) AS created_at,
               SUM(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) AS live_runs
        FROM analysis_run WHERE prompt_id IS NULL GROUP BY grading_prompt
        """
    ).fetchall()
    for row in legacy:
        cur = conn.execute(
            """
            INSERT INTO prompt (name, description, title_pending, created_at, updated_at, deleted_at)
            VALUES (?, ?, 0, ?, ?, ?)
            """,
            (
                _placeholder_title(row["grading_prompt"]),
                row["grading_prompt"],
                row["created_at"],
                row["created_at"],
                None if row["live_runs"] else _now(),
            ),
        )
        conn.execute(
            "UPDATE analysis_run SET prompt_id = ? WHERE prompt_id IS NULL AND grading_prompt = ?",
            (cur.lastrowid, row["grading_prompt"]),
        )
    if legacy:
        conn.commit()

    # Runs from before they had their own name start from their prompt's name,
    # made unique in the order the runs were created. Deleted runs are kept
    # out of the uniqueness check, so they just take the plain name.
    unnamed = conn.execute(
        """
        SELECT run.id, run.grading_prompt, run.deleted_at, pr.name AS prompt_name
        FROM analysis_run run LEFT JOIN prompt pr ON pr.id = run.prompt_id
        WHERE run.name IS NULL
        ORDER BY run.created_at, run.id
        """
    ).fetchall()
    for row in unnamed:
        base = row["prompt_name"] or _placeholder_title(row["grading_prompt"])
        name = (
            _unique_run_name(conn, base, row["id"])
            if row["deleted_at"] is None
            else " ".join(base.split())[:MAX_RUN_NAME_CHARS] or "Untitled"
        )
        conn.execute("UPDATE analysis_run SET name = ? WHERE id = ?", (name, row["id"]))
    if unnamed:
        conn.commit()


def _backfill_title_keys(conn):
    """Give every paper from before title_key existed its key, in batches. A
    paper with no usable title gets '' (not NULL), so it is not revisited."""
    while True:
        rows = conn.execute("SELECT id, title FROM paper WHERE title_key IS NULL LIMIT 1000").fetchall()
        if not rows:
            return
        conn.executemany(
            "UPDATE paper SET title_key = ? WHERE id = ?",
            [(title_key(row["title"]), row["id"]) for row in rows],
        )
        conn.commit()


def _create_indexes(conn):
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_paper_doi ON paper(lower(doi))",
        "CREATE INDEX IF NOT EXISTS idx_paper_title_key ON paper(title_key)",
        "CREATE INDEX IF NOT EXISTS idx_dataset_paper_paper ON dataset_paper(paper_id)",
        "CREATE INDEX IF NOT EXISTS idx_llm_call_run ON llm_call(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_llm_call_dataset ON llm_call(dataset_id)",
        "CREATE INDEX IF NOT EXISTS idx_prompt_example_paper ON prompt_example(paper_id)",
    ):
        conn.execute(statement)
    conn.commit()


def _keep_copy_before_upgrade(conn, old_version):
    """Copy the database (as it is, before any migration touches it) next to the
    original, once, so the first launch after an upgrade can never cost the user
    their data. Never overwritten or deleted by the app."""
    copy = DB_PATH.with_name(f"{DB_PATH.name}.pre-upgrade-{old_version}-to-{SCHEMA_VERSION}")
    if copy.exists():
        return
    temp = copy.with_name(copy.name + ".partial")
    temp.unlink(missing_ok=True)
    target = sqlite3.connect(str(temp))
    try:
        conn.backup(target)
    finally:
        target.close()
    os.replace(temp, copy)


def _ensure_ready():
    """Create, upgrade and tune the database once per process (and again if
    DB_PATH changes, which tests do). Routes never run migrations themselves."""
    global _ready_for
    if _ready_for == DB_PATH and DB_PATH.exists():
        return
    with _INIT_LOCK:
        if _ready_for == DB_PATH and DB_PATH.exists():
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        had_data = DB_PATH.exists() and DB_PATH.stat().st_size > 0
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise DatabaseTooNew(
                    "This data was made by a newer version of Lit Review. Please update Lit Review to open it."
                )
            if had_data and version < SCHEMA_VERSION:
                _keep_copy_before_upgrade(conn, version)
            conn.executescript(_SCHEMA)
            _migrate(conn)
            _create_indexes(conn)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
            # Foreign keys are enforced from here on. Rows an older version left
            # dangling are reported, never repaired behind the user's back.
            orphans = conn.execute("PRAGMA foreign_key_check").fetchall()
            if orphans:
                logging.getLogger(__name__).warning(
                    "The database has %d rows that point at missing rows (left as they are).", len(orphans)
                )
        finally:
            conn.close()
        _ready_for = DB_PATH


def _connect():
    _ensure_ready()
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_ready():
    """Create the data folder and database now (and bring an older database up to
    date), so a folder that cannot be used fails here, at launch, where it can be
    explained, instead of as an error on the first request. Raises OSError or
    sqlite3.Error."""
    _ensure_ready()


def _backfill_abstract_if_blank(conn, paper_id, existing_abstract, new_abstract):
    """Shared by both of _get_or_create_paper()'s "found an existing row"
    branches (the initial dedupe-key lookup, and the lost-an-insert-race
    fallback) - never overwrites an existing non-blank abstract, only fills
    a gap. Caller commits; this only executes the UPDATE when needed."""
    if not (existing_abstract or "").strip() and new_abstract and new_abstract.strip():
        conn.execute("UPDATE paper SET abstract = ? WHERE id = ?", (new_abstract, paper_id))


def _get_or_create_paper(conn, result):
    """One paper's lookup-then-insert on an open connection, without committing
    (see get_or_create_papers, which holds _LOCK and commits once)."""
    key = dedupe_key(result)
    row = None
    if key[0] == "doi":
        row = conn.execute("SELECT id, abstract FROM paper WHERE lower(doi) = ?", (key[1],)).fetchone()
    elif key[0] == "title":
        row = conn.execute(
            "SELECT id, abstract FROM paper WHERE doi IS NULL AND title_key = ? "
            "AND (year IS ? OR year = ?) ORDER BY id LIMIT 1",
            (key[1], key[2], key[2]),
        ).fetchone()
    if row:
        _backfill_abstract_if_blank(conn, row["id"], row["abstract"], result.get("abstract"))
        return row["id"]

    cur = conn.execute(
        """
        INSERT INTO paper
            (source, source_id, doi, title, title_key, abstract, year, publication_date,
             citation_count, venue, authors, url, is_review, first_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source, source_id) DO NOTHING
        """,
        (
            result.get("source", "openalex"),
            result["id"],
            result.get("doi"),
            result.get("title"),
            title_key(result.get("title")),
            result.get("abstract"),
            result.get("year"),
            result.get("publication_date"),
            result.get("citation_count", 0),
            result.get("venue"),
            json.dumps(result.get("authors") or []),
            safe_url(result.get("url")),
            int(bool(result.get("is_review"))),
            _now(),
        ),
    )
    if cur.rowcount:
        return cur.lastrowid
    # The same source id is already stored under a different dedupe key (its
    # title or DOI changed since): use that row. The abstract backfill applies
    # here too, so a more complete copy is not dropped just because it came second.
    row = conn.execute(
        "SELECT id, abstract FROM paper WHERE source = ? AND source_id = ?",
        (result.get("source", "openalex"), result["id"]),
    ).fetchone()
    _backfill_abstract_if_blank(conn, row["id"], row["abstract"], result.get("abstract"))
    return row["id"]


def get_or_create_papers(results):
    """Insert each paper (in the shape openalex._work_to_result() returns) that has
    no matching row yet, and return every paper's row id, in input order. All in
    one transaction, so a search of thousands of papers is one commit, and one
    that fails part way leaves nothing behind.

    Matching follows the same rule openalex.dedupe() applies in-memory: DOI first,
    else normalized (title, year) - not expressible as a single UNIQUE
    constraint, so it's a lookup-then-insert done under _LOCK. A paper repeated
    within `results` matches the row its first occurrence inserted.

    If a matching row already exists but has no abstract, and this occurrence
    of the paper does, backfill it - the same paper can turn up more than
    once (different expanded queries in one search, or different source
    databases) and whichever occurrence is seen first otherwise wins
    forever, even if a later one is more complete. Abstracts are stored as
    '' (not NULL) when OpenAlex has none (openalex.reconstruct_abstract()
    returns '' for a missing/empty abstract_inverted_index) - a blank check
    has to treat both as "missing", not just NULL, or this would never
    trigger. Never overwrites an existing non-blank abstract with a
    different one - this only fills a gap, it doesn't reconcile conflicts."""
    with _LOCK, closing(_connect()) as conn:
        ids = [_get_or_create_paper(conn, result) for result in results]
        conn.commit()
        return ids


def get_or_create_paper(result):
    """get_or_create_papers() for one paper."""
    return get_or_create_papers([result])[0]


def _paper_row_to_dict(row):
    paper = {
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
    # A per-dataset flag, so only set for rows read through dataset_paper. Left
    # out otherwise (not False), so a paper edit's response can't overwrite the
    # page's existing excluded state when merged into it.
    if "excluded_at" in row.keys():
        paper["excluded"] = bool(row["excluded_at"])
    # Whether an abstract lookup has already completed for this paper. Left out
    # (not False) when the row doesn't carry the column, for the same reason.
    if "abstract_checked_at" in row.keys():
        paper["abstract_checked"] = row["abstract_checked_at"] is not None
    # Global to the paper. Left out (not False) when the row lacks the column,
    # for the same reason.
    if "read_at" in row.keys():
        paper["read"] = row["read_at"] is not None
    return paper


def get_paper(paper_id):
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM paper WHERE id = ?", (paper_id,)).fetchone()
        return _paper_row_to_dict(row) if row else None


# Fields the user is allowed to hand-edit - the paper table's identity
# columns (source, source_id, first_seen_at) and the DOI (the key papers are
# matched on across searches) are deliberately excluded.
EDITABLE_PAPER_FIELDS = {"title", "abstract", "year", "citation_count", "venue", "url", "authors"}


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
    if "title" in updates:
        set_clause += ", title_key = ?"
        updates["title_key"] = title_key(updates["title"])
    with _LOCK, closing(_connect()) as conn:
        conn.execute(f"UPDATE paper SET {set_clause} WHERE id = ?", (*updates.values(), paper_id))
        if "year" in updates:
            # Sorting and the dataset's date range prefer the full publication
            # date, so one that contradicts the corrected year is cleared and the
            # year is used instead. Only this paper, only when the user saves it.
            conn.execute(
                "UPDATE paper SET publication_date = NULL WHERE id = ? AND publication_date IS NOT NULL "
                "AND year IS NOT NULL AND substr(publication_date, 1, 4) != CAST(year AS TEXT)",
                (paper_id,),
            )
        conn.commit()


def set_paper_read(paper_id, read):
    """Mark a paper read or unread. Global to the paper, so it shows in every
    dataset and run containing it. Returns False if the paper doesn't exist."""
    with _LOCK, closing(_connect()) as conn:
        cur = conn.execute(
            "UPDATE paper SET read_at = ? WHERE id = ?",
            (_now() if read else None, paper_id),
        )
        conn.commit()
        return cur.rowcount > 0


def get_dataset_papers_missing_abstract(dataset_id):
    """(id, doi, checked, title) of each non-excluded paper in the dataset with
    a blank abstract; doi may be None, and checked is whether a lookup already
    completed for it without finding one. Excluded papers are left alone,
    since they won't be scored and a lookup would only spend API quota."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.doi, p.abstract_checked_at IS NOT NULL AS checked, p.title
            FROM dataset_paper dp
            JOIN paper p ON p.id = dp.paper_id
            WHERE dp.dataset_id = ? AND dp.excluded_at IS NULL
              AND (p.abstract IS NULL OR TRIM(p.abstract) = '')
            ORDER BY p.id
            """,
            (dataset_id,),
        ).fetchall()
        return [(row["id"], row["doi"], bool(row["checked"]), row["title"]) for row in rows]


def mark_abstract_checked(paper_id):
    with _LOCK, closing(_connect()) as conn:
        conn.execute("UPDATE paper SET abstract_checked_at = ? WHERE id = ?", (_now(), paper_id))
        conn.commit()


def clear_abstract_checked():
    """Forget which papers an abstract lookup already gave up on, so the next
    lookup tries them all again. Called when a new lookup API key is saved,
    since a source that couldn't be asked before now can be."""
    with _LOCK, closing(_connect()) as conn:
        conn.execute("UPDATE paper SET abstract_checked_at = NULL WHERE abstract_checked_at IS NOT NULL")
        conn.commit()


def set_paper_abstract_if_blank(paper_id, abstract, source):
    """Fill a blank abstract and record where it came from. Never overwrites
    one that's there (the user may have typed one in since the lookup
    started). Returns whether it was written."""
    with _LOCK, closing(_connect()) as conn:
        cur = conn.execute(
            "UPDATE paper SET abstract = ?, abstract_source = ? "
            "WHERE id = ? AND (abstract IS NULL OR TRIM(abstract) = '')",
            (abstract, source, paper_id),
        )
        conn.commit()
        return cur.rowcount > 0


def _dataset_sources(raw):
    """A dataset's source ids from its stored JSON; OpenAlex for datasets that
    predate the column."""
    try:
        sources = json.loads(raw) if raw else None
    except ValueError:
        sources = None
    return sources or ["openalex"]


def create_dataset(verbose_query, expanded_queries, from_date=None, to_date=None, name=None, sources=None):
    """from_date and to_date are the search's "YYYY-MM-DD" publication date bounds. name is the short title (AI-written at expansion time); without one, the
    first few words of the topic stand in. sources are the paper source ids it
    was retrieved from (default OpenAlex)."""
    name = (name or "").strip() or _placeholder_title(verbose_query)
    with _LOCK, closing(_connect()) as conn:
        cur = conn.execute(
            """
            INSERT INTO dataset
                (name, verbose_query, from_year, to_year, from_date, to_date, expanded_queries, sources, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                verbose_query,
                int(from_date[:4]) if from_date else None,
                int(to_date[:4]) if to_date else None,
                from_date,
                to_date,
                json.dumps(expanded_queries),
                json.dumps(sources or ["openalex"]),
                _now(),
            ),
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


def find_dataset(verbose_query, from_date=None, to_date=None, sources=None):
    """Look up an existing dataset with the same question + date filters +
    paper sources, so resubmitting an identical search reuses it instead of
    re-running expansion/retrieval (see PLAN.md's reuse-first rule for
    POST /api/datasets). The same topic searched in different sources is a
    different paper pool, so it isn't reused."""
    wanted = sorted(sources or ["openalex"])
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT id, sources FROM dataset
            WHERE verbose_query = ?
              AND deleted_at IS NULL
              AND (from_date IS ? OR from_date = ?)
              AND (to_date IS ? OR to_date = ?)
            ORDER BY created_at DESC
            """,
            (verbose_query, from_date, from_date, to_date, to_date),
        ).fetchall()
        for row in rows:
            if sorted(_dataset_sources(row["sources"])) == wanted:
                return row["id"]
        return None


def list_datasets():
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT d.id, d.name, d.verbose_query, d.from_year, d.to_year, d.created_at,
                   COUNT(dp.paper_id) AS paper_count,
                   MIN(p.year) AS oldest_year,
                   MAX(p.year) AS newest_year,
                   MAX(p.publication_date) AS newest_publication_date,
                   (SELECT ai_api FROM llm_call
                     WHERE dataset_id = d.id AND run_id IS NULL AND purpose = 'query_expansion'
                     ORDER BY id DESC LIMIT 1) AS ai_api,
                   (SELECT ai_model FROM llm_call
                     WHERE dataset_id = d.id AND run_id IS NULL AND purpose = 'query_expansion'
                     ORDER BY id DESC LIMIT 1) AS ai_model
            FROM dataset d
            LEFT JOIN dataset_paper dp ON dp.dataset_id = d.id AND dp.excluded_at IS NULL
            LEFT JOIN paper p ON p.id = dp.paper_id
            WHERE d.deleted_at IS NULL
            GROUP BY d.id
            ORDER BY d.created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_dataset(dataset_id, include_deleted=False):
    query = "SELECT * FROM dataset WHERE id = ?"
    if not include_deleted:
        query += " AND deleted_at IS NULL"
    with closing(_connect()) as conn:
        row = conn.execute(query, (dataset_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["expanded_queries"] = json.loads(d["expanded_queries"])
        d["sources"] = _dataset_sources(d.get("sources"))
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


def set_dataset_paper_excluded(dataset_id, paper_id, excluded):
    """Soft-exclude (or restore) a paper within one dataset. Returns False if
    the paper isn't in the dataset."""
    with _LOCK, closing(_connect()) as conn:
        cur = conn.execute(
            "UPDATE dataset_paper SET excluded_at = ? WHERE dataset_id = ? AND paper_id = ?",
            (_now() if excluded else None, dataset_id, paper_id),
        )
        conn.commit()
        return cur.rowcount > 0


def rename_dataset(dataset_id, name):
    with _LOCK, closing(_connect()) as conn:
        conn.execute(
            "UPDATE dataset SET name = ? WHERE id = ? AND deleted_at IS NULL", (name, dataset_id)
        )
        conn.commit()


def delete_dataset(dataset_id):
    """Soft-deletes only the dataset grouping. Runs that scored it are kept
    (they still list it by name), as are papers and LLM call logs."""
    with _LOCK, closing(_connect()) as conn:
        conn.execute(
            "UPDATE dataset SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (_now(), dataset_id),
        )
        conn.commit()


def rename_analysis_run(run_id, name):
    """Give a run a new name. Returns the saved (whitespace-normalized) name, or
    None if another live run already has it (case-insensitive). A rename also
    stops the AI prompt title from replacing the name later."""
    name = " ".join(name.split())
    with _LOCK, closing(_connect()) as conn:
        if _unique_run_name(conn, name, run_id) != name:
            return None
        conn.execute(
            "UPDATE analysis_run SET name = ?, name_auto = 0 WHERE id = ? AND deleted_at IS NULL",
            (name, run_id),
        )
        conn.commit()
        return name


def delete_analysis_run(run_id):
    """Soft delete: the run and its scores are hidden, not removed."""
    with _LOCK, closing(_connect()) as conn:
        conn.execute(
            "UPDATE analysis_run SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (_now(), run_id),
        )
        conn.commit()


# Each example adds input tokens to every scoring chunk, so only the most
# recently added ones are sent to the judge.
EXAMPLE_LIMIT = 6


def _scoring_examples(conn, prompt_id):
    rows = conn.execute(
        """
        SELECT p.title, p.abstract, pe.score, pe.rationale
        FROM prompt_example pe
        JOIN paper p ON p.id = pe.paper_id
        WHERE pe.prompt_id = ?
        ORDER BY pe.created_at DESC, pe.id DESC
        LIMIT ?
        """,
        (prompt_id, EXAMPLE_LIMIT),
    ).fetchall()
    return [dict(row) for row in rows]


def create_analysis_run(dataset_ids, grading_prompt, ai_api, ai_model, prompt_id=None):
    """A run can span several datasets - scores the union of their papers in
    one pass. dataset_ids must be non-empty (validated by the caller).

    With prompt_id, the run uses that saved prompt: its description becomes the
    run's grading_prompt (a snapshot) and its current examples are snapshotted
    too. Without one, a new prompt is created from grading_prompt in the same
    transaction, with a placeholder name and title_pending set so the first
    scoring call supplies a real title."""
    with _LOCK, closing(_connect()) as conn:
        now = _now()
        # The run's name starts as its prompt's. For a new prompt that is only a
        # placeholder until the AI title arrives, so name_auto lets that title
        # replace it (see set_generated_prompt_title).
        if prompt_id is None:
            prompt_name = _placeholder_title(grading_prompt)
            cur = conn.execute(
                """
                INSERT INTO prompt (name, description, title_pending, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?)
                """,
                (prompt_name, grading_prompt, now, now),
            )
            prompt_id = cur.lastrowid
            examples = []
            name_auto = 1
        else:
            prompt = conn.execute(
                "SELECT name, description FROM prompt WHERE id = ?", (prompt_id,)
            ).fetchone()
            grading_prompt = prompt["description"]
            prompt_name = prompt["name"]
            examples = _scoring_examples(conn, prompt_id)
            name_auto = 0
        cur = conn.execute(
            """
            INSERT INTO analysis_run
                (grading_prompt, ai_api, ai_model, status, created_at, prompt_id, examples_snapshot,
                 name, name_auto)
            VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?)
            """,
            (
                grading_prompt, ai_api, ai_model, now, prompt_id, json.dumps(examples),
                _unique_run_name(conn, prompt_name), name_auto,
            ),
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
            SELECT d.id, d.name, d.verbose_query, d.created_at,
                   (d.deleted_at IS NOT NULL) AS deleted
            FROM analysis_run_dataset ard
            JOIN dataset d ON d.id = ard.dataset_id
            WHERE ard.run_id = ?
            ORDER BY d.created_at
            """,
            (run_id,),
        ).fetchall()
        return [{**row, "deleted": bool(row["deleted"])} for row in map(dict, rows)]




def list_all_runs():
    """All runs with their linked dataset names, status, and cost, for the
    Results list page."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT run.id, run.name, run.grading_prompt, run.ai_api, run.ai_model, run.status,
                   run.created_at, run.completed_at, pr.name AS prompt_name,
                   json_group_array(json_object('name', d.name, 'created_at', d.created_at)) AS datasets,
                   (SELECT COUNT(*) FROM (
                        SELECT dp.paper_id
                        FROM dataset_paper dp
                        JOIN analysis_run_dataset rd ON rd.dataset_id = dp.dataset_id
                        WHERE rd.run_id = run.id
                        GROUP BY dp.paper_id
                        HAVING SUM(CASE WHEN dp.excluded_at IS NULL THEN 1 ELSE 0 END) > 0
                   )) AS paper_count,
                   -- Included papers with no result yet: what "Incomplete" means. Not the
                   -- run's status, which can lag (still "running" after the last unscored
                   -- papers were excluded) or be stale (a "completed" run whose papers came back).
                   (SELECT COUNT(*) FROM (
                        SELECT dp.paper_id
                        FROM dataset_paper dp
                        JOIN analysis_run_dataset rd ON rd.dataset_id = dp.dataset_id
                        WHERE rd.run_id = run.id
                        GROUP BY dp.paper_id
                        HAVING SUM(CASE WHEN dp.excluded_at IS NULL THEN 1 ELSE 0 END) > 0
                   ) included
                   LEFT JOIN analysis_result ar ON ar.run_id = run.id AND ar.paper_id = included.paper_id
                   WHERE ar.id IS NULL) AS unscored_count,
                   (SELECT COALESCE(SUM(usd), 0) FROM llm_call WHERE run_id = run.id)
                   + (SELECT COALESCE(SUM(usd), 0) FROM llm_call
                        WHERE run_id IS NULL
                          AND dataset_id IN (
                              SELECT dataset_id FROM analysis_run_dataset WHERE run_id = run.id
                          )) AS cost
            FROM analysis_run run
            JOIN analysis_run_dataset ard ON ard.run_id = run.id
            JOIN dataset d ON d.id = ard.dataset_id
            LEFT JOIN prompt pr ON pr.id = run.prompt_id
            WHERE run.deleted_at IS NULL
            GROUP BY run.id
            ORDER BY run.created_at DESC
            """
        ).fetchall()
        runs = []
        for row in rows:
            run = dict(row)
            run["datasets"] = json.loads(run["datasets"])
            runs.append(run)
        return runs


def get_analysis_run(run_id, include_deleted=False):
    query = "SELECT * FROM analysis_run WHERE id = ?"
    if not include_deleted:
        query += " AND deleted_at IS NULL"
    with closing(_connect()) as conn:
        row = conn.execute(query, (run_id,)).fetchone()
        if not row:
            return None
        run = dict(row)
        run["examples_snapshot"] = json.loads(run["examples_snapshot"] or "[]")
        return run


def get_run_result(run_id, paper_id):
    """One scored paper's score and reasoning in a run, or None if unscored."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT score, rationale FROM analysis_result WHERE run_id = ? AND paper_id = ?",
            (run_id, paper_id),
        ).fetchone()
        return dict(row) if row else None


# Prompts

def create_prompt(name, description):
    with _LOCK, closing(_connect()) as conn:
        now = _now()
        cur = conn.execute(
            "INSERT INTO prompt (name, description, title_pending, created_at, updated_at) VALUES (?, ?, 0, ?, ?)",
            (name, description, now, now),
        )
        conn.commit()
        return cur.lastrowid


def list_prompts():
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT pr.id, pr.name, pr.description, pr.created_at, pr.updated_at,
                   (SELECT COUNT(*) FROM prompt_example pe WHERE pe.prompt_id = pr.id) AS example_count
            FROM prompt pr
            WHERE pr.deleted_at IS NULL
            ORDER BY pr.updated_at DESC, pr.id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_prompt(prompt_id, include_deleted=False):
    query = "SELECT * FROM prompt WHERE id = ?"
    if not include_deleted:
        query += " AND deleted_at IS NULL"
    with closing(_connect()) as conn:
        row = conn.execute(query, (prompt_id,)).fetchone()
        return dict(row) if row else None


def update_prompt(prompt_id, name, description):
    """Saving any edit also clears title_pending, so a title the user just set
    can never be overwritten by the AI-generated one."""
    with _LOCK, closing(_connect()) as conn:
        conn.execute(
            """
            UPDATE prompt SET name = ?, description = ?, title_pending = 0, updated_at = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (name, description, _now(), prompt_id),
        )
        conn.commit()


def set_generated_prompt_title(prompt_id, title):
    """Applies the AI's title only while the prompt is still awaiting one
    (title_pending), and clears the flag either way."""
    with _LOCK, closing(_connect()) as conn:
        if title:
            cur = conn.execute(
                "UPDATE prompt SET name = ? WHERE id = ? AND title_pending = 1",
                (title, prompt_id),
            )
            if cur.rowcount:
                # The run that made this prompt is still on its placeholder
                # name unless the user already renamed it.
                for run in conn.execute(
                    "SELECT id FROM analysis_run WHERE prompt_id = ? AND name_auto = 1", (prompt_id,)
                ).fetchall():
                    conn.execute(
                        "UPDATE analysis_run SET name = ? WHERE id = ?",
                        (_unique_run_name(conn, title, run["id"]), run["id"]),
                    )
        conn.execute("UPDATE analysis_run SET name_auto = 0 WHERE prompt_id = ?", (prompt_id,))
        conn.execute("UPDATE prompt SET title_pending = 0 WHERE id = ?", (prompt_id,))
        conn.commit()


def delete_prompt(prompt_id):
    """Soft delete. Runs keep their own snapshot of the prompt and examples."""
    with _LOCK, closing(_connect()) as conn:
        conn.execute(
            "UPDATE prompt SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (_now(), prompt_id),
        )
        conn.commit()


def list_prompt_examples(prompt_id):
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT pe.id, pe.paper_id, pe.source_run_id, pe.score, pe.rationale, pe.created_at,
                   p.title, p.year
            FROM prompt_example pe
            JOIN paper p ON p.id = pe.paper_id
            WHERE pe.prompt_id = ?
            ORDER BY pe.created_at DESC, pe.id DESC
            """,
            (prompt_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def add_prompt_example(prompt_id, paper_id, run_id, score, rationale):
    """Marking a paper that is already an example replaces the old one (newest
    score and reasoning win)."""
    with _LOCK, closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO prompt_example (prompt_id, paper_id, source_run_id, score, rationale, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (prompt_id, paper_id) DO UPDATE SET
                source_run_id = excluded.source_run_id,
                score = excluded.score,
                rationale = excluded.rationale,
                created_at = excluded.created_at
            """,
            (prompt_id, paper_id, run_id, score, rationale, _now()),
        )
        conn.commit()


def remove_prompt_example(prompt_id, example_id):
    with _LOCK, closing(_connect()) as conn:
        cur = conn.execute(
            "DELETE FROM prompt_example WHERE id = ? AND prompt_id = ?", (example_id, prompt_id)
        )
        conn.commit()
        return cur.rowcount > 0


RELEVANCE_VALUES = {"relevant", "neutral", "not_relevant"}


def set_result_relevance(run_id, paper_id, relevance):
    """Set the user's relevance call on a paper's result in one run
    ('neutral' is stored as NULL). Returns False if the run has no result for
    the paper."""
    with _LOCK, closing(_connect()) as conn:
        cur = conn.execute(
            "UPDATE analysis_result SET relevance = ? WHERE run_id = ? AND paper_id = ?",
            (None if relevance == "neutral" else relevance, run_id, paper_id),
        )
        conn.commit()
        return cur.rowcount > 0


def get_run_results(run_id):
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT p.*, ar.paper_id, ar.rationale, ar.score, ar.relevance,
                   (pe.id IS NOT NULL) AS is_example
            FROM analysis_result ar
            JOIN paper p ON p.id = ar.paper_id
            JOIN analysis_run run ON run.id = ar.run_id
            LEFT JOIN prompt_example pe ON pe.prompt_id = run.prompt_id AND pe.paper_id = ar.paper_id
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
            paper["relevance"] = row["relevance"] or "neutral"
            paper["is_example"] = bool(row["is_example"])
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


def reopen_run(run_id):
    """Put a finished run back to "running" because it has unscored papers again.
    Does nothing for a run that is not completed."""
    with _LOCK, closing(_connect()) as conn:
        conn.execute(
            "UPDATE analysis_run SET status = 'running', completed_at = NULL WHERE id = ? AND status = 'completed'",
            (run_id,),
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


def get_dataset_expansion(dataset_id):
    """The AI model that expanded this dataset's query and what that cost, as
    {"ai_api", "ai_model", "cost"}, or None if no expansion call was logged. The
    model is the latest logged call's; the cost sums every expansion call."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT ai_api, ai_model, usd FROM llm_call
            WHERE dataset_id = ? AND run_id IS NULL AND purpose = 'query_expansion'
            ORDER BY id DESC
            """,
            (dataset_id,),
        ).fetchall()
    if not rows:
        return None
    return {
        "ai_api": rows[0]["ai_api"],
        "ai_model": rows[0]["ai_model"],
        "cost": sum(row["usd"] for row in rows),
    }


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
