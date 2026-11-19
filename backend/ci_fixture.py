"""Fill a throwaway data folder with sample datasets, papers, a prompt and evaluations, for
the release checks that drive the real app (packaging/browser_test.py and the browser walk
in frontend/scripts/verify-app.mjs). Modelled on personal-website's backend/ci_fixture.py.

    python backend/ci_fixture.py --data-dir <folder> --manifest <file.json>

Everything is written straight to the database through db.py, so no AI call, search or
abstract lookup happens (none is queued, either). The manifest names what was made, so
the browser walk can find it without guessing ids.

Never point --data-dir at a real data folder: the checks rename, exclude and delete things.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


def _paper(n, **extra):
    paper = {
        "id": f"W90000{n:02d}",
        "source": "openalex",
        "doi": f"https://doi.org/10.5555/ci.{n}",
        "title": f"CI sample paper {n} on graphene thermal transport",
        "abstract": (
            f"Sample abstract {n}. We measure thermal conductivity of suspended graphene "
            "ribbons and compare the results with phonon transport models across temperatures."
        ),
        "year": 2024,
        "publication_date": f"2024-0{1 + n % 9}-15",
        "citation_count": 10 * n,
        "venue": "Journal of Continuous Integration",
        "authors": ["A. Tester", "B. Checker"],
        "url": f"https://example.org/papers/{n}",
        "is_review": False,
        "is_retracted": False,
        "work_type": "article",
    }
    paper.update(extra)
    return paper


def build(data_dir):
    """Write the sample data into `data_dir` (which must be new or empty) and return the manifest."""
    os.environ["LIT_REVIEW_DATA_DIR"] = str(data_dir)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import db  # noqa: E402  (reads LIT_REVIEW_DATA_DIR when imported)

    if db.DB_PATH.exists():
        raise SystemExit(f"{db.DB_PATH} already exists: the fixture only fills a new, empty data folder")
    db.ensure_ready()

    papers_a = [_paper(n) for n in range(1, 7)]
    papers_a[2]["is_retracted"] = True  # a retracted paper is kept, badged and left out of runs
    papers_a[3]["abstract"] = None  # one without an abstract
    papers_b = [_paper(n, title=f"CI sample paper {n} on soil microbiome diversity") for n in range(11, 15)]

    first = db.create_dataset(
        "Thermal transport in suspended graphene ribbons", ["graphene thermal conductivity", "phonon transport ribbons"],
        from_date="2020-01-01", to_date="2025-12-31", name="Graphene thermal transport", search_limit=100,
    )
    db.add_papers_to_dataset(first, db.get_or_create_papers(papers_a))
    second = db.create_dataset(
        "Soil microbiome diversity under drought", ["soil microbiome drought diversity"],
        from_date="2021-01-01", to_date="2025-12-31", name="Soil microbiome drought", search_limit=100,
    )
    db.add_papers_to_dataset(second, db.get_or_create_papers(papers_b))
    trashed = db.create_dataset(
        "A dataset that starts in Deleted Items", ["deleted dataset query"], name="Deleted sample dataset",
    )
    db.add_papers_to_dataset(trashed, db.get_or_create_papers([_paper(21)]))
    db.delete_dataset(trashed)

    prompt = db.create_prompt(
        "Graphene heat transport", "Experimental measurements of thermal conductivity in graphene nanostructures."
    )

    usage = SimpleNamespace(input_tokens=1200, output_tokens=300, usd=0.0042, provider="anthropic", model="")
    completed = db.create_analysis_run([first], None, "anthropic", "claude-sonnet-4-5", prompt_id=prompt)
    scored = [p for p in db.get_run_candidate_papers(completed)]
    db.record_analysis_chunk(
        completed,
        {p["id"]: {"score": 90 - 10 * i, "rationale": f"Sample reasoning for paper {i + 1}."} for i, p in enumerate(scored)},
        usage,
    )
    db.mark_run_completed(completed)
    best = scored[0]["id"]
    db.add_prompt_example(prompt, best, completed, 90, "Sample reasoning for paper 1.")

    incomplete = db.create_analysis_run([second], None, "anthropic", "claude-sonnet-4-5", prompt_id=prompt)
    some = db.get_run_candidate_papers(incomplete)[:2]
    db.record_analysis_chunk(incomplete, {p["id"]: {"score": 40, "rationale": "Partly scored."} for p in some}, usage)

    return {
        "datasets": {
            "first": {"id": first, "name": "Graphene thermal transport", "papers": len(papers_a)},
            "second": {"id": second, "name": "Soil microbiome drought", "papers": len(papers_b)},
            "trashed": {"id": trashed, "name": "Deleted sample dataset"},
        },
        "prompt": {"id": prompt, "name": "Graphene heat transport"},
        "runs": {
            "completed": {"id": completed, "name": db.get_analysis_run(completed)["name"], "scored": len(scored)},
            "incomplete": {"id": incomplete, "name": db.get_analysis_run(incomplete)["name"]},
        },
        "paper": {"id": best, "title": next(p["title"] for p in scored if p["id"] == best)},
        "retracted_title": papers_a[2]["title"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    manifest = build(Path(args.data_dir))
    Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
