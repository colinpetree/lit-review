"""Release check: a database made by the previous release opens, migrates and still shows its
data in this build. Lit Review's version of personal-website's upgrade-migration test.

    python packaging/upgrade_test.py --previous-zip Lit-Review-0.1.3-Windows.zip --exe "dist/Lit Review/Lit Review.exe"

1. The previous release (unpacked from its zip, as the updater would) is started once on a
   throwaway data folder, which makes a database in its own schema, and stopped.
2. Sample rows are written into that database: a dataset with papers, a prompt and a scored
   evaluation, using only the columns that schema has (so this works for any older version).
3. This build is started on the same folder. It must migrate the database to this code's
   SCHEMA_VERSION, keep the one-time pre-upgrade copy when the version changed, and show the
   sample data through its API.
"""

import argparse
import datetime
import json
import re
import sqlite3
import sys
from pathlib import Path

from app_runner import RunningApp, fresh_work, unpack_release_zip

ROOT = Path(__file__).resolve().parent.parent
DB_NAME = "lit_review.db"


def this_schema_version():
    match = re.search(r"^SCHEMA_VERSION = (\d+)$", (ROOT / "backend" / "db.py").read_text(encoding="utf-8"), re.M)
    return int(match.group(1))


def _filler(declared_type):
    kind = (declared_type or "").upper()
    return 0 if ("INT" in kind or "REAL" in kind or "NUM" in kind) else ""


def insert(conn, table, values):
    """Insert `values`, keeping only the columns `table` has, and filling any other NOT NULL
    column without a default (one a newer version would set) with an empty value."""
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()  # cid, name, type, notnull, default, pk
    names = {c[1] for c in columns}
    row = {k: v for k, v in values.items() if k in names}
    for _cid, name, declared, notnull, default, pk in columns:
        if notnull and default is None and not pk and name not in row:
            row[name] = _filler(declared)
    keys = list(row)
    cur = conn.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})", [row[k] for k in keys])
    return cur.lastrowid


def seed(db_path):
    """The sample rows, as the newer build should show them."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        dataset = insert(conn, "dataset", {
            "name": "Upgrade sample dataset", "verbose_query": "Upgrade sample topic", "expanded_queries": json.dumps(["upgrade sample"]),
            "sources": json.dumps(["openalex"]), "from_year": 2020, "to_year": 2025, "from_date": "2020-01-01", "to_date": "2025-12-31",
            "created_at": now,
        })
        papers = []
        for n in range(1, 4):
            papers.append(insert(conn, "paper", {
                "source": "openalex", "source_id": f"W8800{n}", "doi": f"https://doi.org/10.5555/upgrade.{n}",
                "title": f"Upgrade sample paper {n}", "title_key": f"upgrade sample paper {n}",
                "abstract": f"Abstract of upgrade sample paper {n}, long enough to count as a real abstract for scoring.",
                "year": 2024, "citation_count": n, "authors": json.dumps(["U. Grader"]), "first_seen_at": now,
            }))
            insert(conn, "dataset_paper", {"dataset_id": dataset, "paper_id": papers[-1], "added_at": now})
        prompt = insert(conn, "prompt", {"name": "Upgrade sample prompt", "description": "Upgrade sample criteria.", "created_at": now, "updated_at": now})
        run = insert(conn, "analysis_run", {
            "grading_prompt": "Upgrade sample criteria.", "ai_api": "anthropic", "ai_model": "claude-sonnet-4-5", "status": "completed",
            "created_at": now, "completed_at": now, "prompt_id": prompt, "examples_snapshot": "[]", "name": "Upgrade sample run",
        })
        insert(conn, "analysis_run_dataset", {"run_id": run, "dataset_id": dataset})
        for i, paper in enumerate(papers):
            insert(conn, "analysis_result", {"run_id": run, "paper_id": paper, "score": 80 - i, "rationale": "Upgrade sample reasoning.", "created_at": now})
        conn.commit()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    return {"dataset": dataset, "papers": len(papers), "run": run, "prompt": prompt, "old_version": version}


def listed(body, key):
    """The items of a list answer, which is either a bare list or {key: [...]}."""
    if isinstance(body, dict):
        body = body.get(key, [])
    return body if isinstance(body, list) else []


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--previous-zip", required=True)
    parser.add_argument("--exe", required=True, help="this build's program")
    args = parser.parse_args(argv)

    work = fresh_work("lit-review-upgrade-")
    old_exe = unpack_release_zip(args.previous_zip, Path(work) / "previous")
    data = Path(work) / "app"

    with RunningApp(old_exe, data) as old:
        status, about = old.call("/api/about")
        print("previous release running, version", about.get("version") if isinstance(about, dict) else status)
    db_path = data / "data" / DB_NAME
    if not db_path.is_file():
        raise SystemExit(f"FAIL: the previous release made no database at {db_path}")
    sample = seed(db_path)
    new_version = this_schema_version()
    print(f"seeded the previous release's database (schema {sample['old_version']}); this build's schema is {new_version}")

    with RunningApp(args.exe, data) as new:
        status, body = new.call("/api/datasets")
        names = [d.get("name") for d in listed(body, "datasets")]
        if status != 200 or "Upgrade sample dataset" not in names:
            raise SystemExit(f"FAIL: the upgraded copy does not list the old dataset (got {status}: {names})")
        status, dataset = new.call(f"/api/datasets/{sample['dataset']}")
        if status != 200 or len(dataset.get("papers", [])) != sample["papers"]:
            raise SystemExit(f"FAIL: the old dataset's papers did not survive the upgrade ({status})")
        status, run = new.call(f"/api/analysis-runs/{sample['run']}")
        results = run.get("results", []) if isinstance(run, dict) else []
        if status != 200 or len([r for r in results if r.get("score") is not None]) != sample["papers"]:
            raise SystemExit(f"FAIL: the old evaluation's scores did not survive the upgrade ({status})")
        status, body = new.call("/api/prompts")
        if status != 200 or "Upgrade sample prompt" not in [p.get("name") for p in listed(body, "prompts")]:
            raise SystemExit(f"FAIL: the old prompt did not survive the upgrade ({status})")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        migrated = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    if migrated != new_version:
        raise SystemExit(f"FAIL: the database is at schema {migrated}, expected {new_version}")
    if sample["old_version"] != new_version:
        copy = db_path.with_name(f"{DB_NAME}.pre-upgrade-{sample['old_version']}-to-{new_version}")
        if not copy.is_file():
            raise SystemExit(f"FAIL: no pre-upgrade copy ({copy.name}) was kept")
        print("pre-upgrade copy kept:", copy.name)
    print(f"UPGRADE TEST PASSED (schema {sample['old_version']} -> {new_version})")


if __name__ == "__main__":
    sys.exit(main())
