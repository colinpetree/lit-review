"""Turn papers into a file the user can open elsewhere: CSV (spreadsheets), RIS (Zotero,
EndNote, Mendeley) and BibTeX (LaTeX, Zotero). Pure functions on the paper dicts that
db.get_run_results and db.get_dataset_papers return; nothing here touches the database.

Every field is text from an outside source (a paper's title can be anything), so each
format escapes what it needs to: CSV cells that a spreadsheet would run as a formula,
BibTeX's special characters, and line breaks in RIS."""

import csv
import io
import re
import unicodedata

FORMATS = {
    "csv": ("csv", "text/csv; charset=utf-8"),
    "ris": ("ris", "application/x-research-info-systems; charset=utf-8"),
    "bibtex": ("bib", "application/x-bibtex; charset=utf-8"),
}

# A spreadsheet runs a cell that starts with one of these as a formula.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def _squash(text):
    """One line of text: every run of whitespace (including line breaks) is one space."""
    return " ".join(str(text).split()) if text is not None else ""


def _authors(paper):
    return [a for a in (paper.get("authors") or []) if isinstance(a, str) and a.strip()]


def _doi(paper):
    """The bare DOI (10.xxxx/...), without the https://doi.org/ every source adds."""
    doi = (paper.get("doi") or "").strip()
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)


def _note(paper):
    """A free-text note for formats with no column of their own: a warning if the paper
    was retracted (so it is not cited unaware) and the AI's score and reasoning, as one
    line. '' for a paper with neither."""
    parts = []
    if paper.get("is_retracted"):
        parts.append("RETRACTED.")
    if paper.get("score") is not None:
        score = f"Relevance score: {paper['score']}"
        if paper.get("rationale"):
            score += f". {_squash(paper['rationale'])}"
        parts.append(score)
    return " ".join(parts)


# ---- CSV ----

def _cell(value):
    """A CSV cell. Text that would start a formula gets a leading apostrophe, which
    spreadsheets show as plain text; numbers are left as numbers."""
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(_FORMULA_STARTS):
        return "'" + value
    return value


def to_csv(papers, scored=False):
    """UTF-8 bytes with a byte order mark (so Excel reads accents) and CRLF line ends.
    `scored` adds the score, reasoning and relevance columns (a run's results)."""
    columns = ["title", "authors", "year", "publication_date", "venue", "doi", "url", "abstract"]
    if scored:
        columns += ["score", "rationale", "relevance"]
    columns += ["retracted", "read", "source"]

    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(columns)
    for paper in papers:
        row = {
            "title": paper.get("title"),
            "authors": "; ".join(_authors(paper)),
            "year": paper.get("year"),
            "publication_date": paper.get("publication_date"),
            "venue": paper.get("venue"),
            "doi": _doi(paper),
            "url": paper.get("url"),
            "abstract": paper.get("abstract"),
            "score": paper.get("score"),
            "rationale": paper.get("rationale"),
            "relevance": paper.get("relevance"),
            "retracted": "yes" if paper.get("is_retracted") else "no",
            "read": "yes" if paper.get("read") else "no",
            "source": paper.get("source"),
        }
        writer.writerow([_cell(row[c]) for c in columns])
    return ("﻿" + out.getvalue()).encode("utf-8")


# ---- RIS ----

def to_ris(papers):
    """RIS as UTF-8 bytes. One record per paper; each value is on one line, since a
    line break would start a new tag."""
    lines = []

    def tag(name, value):
        value = _squash(value)
        if value:
            lines.append(f"{name}  - {value}")

    for paper in papers:
        tag("TY", "JOUR")
        for author in _authors(paper):
            tag("AU", author)
        tag("TI", paper.get("title"))
        tag("JO", paper.get("venue"))
        if paper.get("year"):
            tag("PY", paper["year"])
        date = paper.get("publication_date") or ""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            tag("DA", date.replace("-", "/"))
        tag("DO", _doi(paper))
        tag("UR", paper.get("url"))
        tag("AB", paper.get("abstract"))
        tag("N1", _note(paper))
        lines.append("ER  - ")
        lines.append("")
    return "\r\n".join(lines).encode("utf-8")


# ---- BibTeX ----

_BIBTEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "^": r"\^{}",
    "~": r"\~{}",
}


def _bibtex_text(value):
    """Text safe inside a BibTeX field. One pass over the characters, so the backslash
    an escape adds is not itself escaped again."""
    return "".join(_BIBTEX_ESCAPES.get(ch, ch) for ch in _squash(value))


def _ascii(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _last_name(author):
    """'Ada Lovelace' and 'Lovelace, Ada' both give 'Lovelace'."""
    if "," in author:
        return author.split(",")[0].strip()
    parts = author.split()
    return parts[-1] if parts else ""


def _bibtex_key(paper):
    """Author last name, year and the paper's id (which keeps keys unique), ASCII only:
    'lovelace1843-12'."""
    authors = _authors(paper)
    name = re.sub(r"[^a-z0-9]", "", _ascii(_last_name(authors[0])).lower()) if authors else ""
    return f"{name or 'paper'}{paper.get('year') or ''}-{paper.get('id')}"


def to_bibtex(papers):
    """BibTeX as UTF-8 bytes, every paper an @article. The title is in double braces so
    BibTeX keeps its capitalization."""
    entries = []
    for paper in papers:
        fields = []

        def field(name, value, protected=False):
            text = _bibtex_text(value)
            if text:
                fields.append(f"  {name} = {{{{{text}}}}}" if protected else f"  {name} = {{{text}}}")

        field("title", paper.get("title"), protected=True)
        authors = _authors(paper)
        if authors:
            field("author", " and ".join(_squash(a) for a in authors))
        field("journal", paper.get("venue"))
        field("year", paper.get("year"))
        field("doi", _doi(paper))
        field("url", paper.get("url"))
        field("abstract", paper.get("abstract"))
        field("note", _note(paper))
        entries.append("@article{" + _bibtex_key(paper) + ",\n" + ",\n".join(fields) + "\n}\n")
    return "\n".join(entries).encode("utf-8")


def build(fmt, papers, scored=False):
    """(bytes, content_type, file extension) for a format name in FORMATS."""
    extension, content_type = FORMATS[fmt]
    if fmt == "csv":
        data = to_csv(papers, scored=scored)
    elif fmt == "ris":
        data = to_ris(papers)
    else:
        data = to_bibtex(papers)
    return data, content_type, extension


def safe_filename(name, extension, today):
    """A file name that is safe in a header and on any file system: the name as plain
    lower-case words, then the date ('coral-reef-bleaching-2026-10-03.csv')."""
    words = re.sub(r"[^a-z0-9]+", "-", _ascii(name or "").lower()).strip("-")[:60].strip("-")
    return f"{words or 'papers'}-{today}.{extension}"
