"""Start Lit Review from source for the job-flow browser test (frontend/scripts/verify-jobs.mjs),
with the AI provider and the paper sources replaced by fakes. Test-only: nothing here is in the
packaged app. Run by `python packaging/browser_test.py --jobs` (CI's e2e job), which gives it
throwaway data folders, a spare port and no browser.

  - Every network connection that is not to this computer is refused, as in tests/conftest.py,
    so a fake that was missed fails loudly instead of reaching a real service or spending money.
  - The AI: query expansion answers two queries and a title; grading scores every paper it is
    sent (SCORE_SECONDS a batch). Until the browser has stopped a run once, every batch after the
    first waits for that stop, so "stop halfway" never depends on how fast the machine is.
  - OpenAlex (the default source) returns PAPERS papers; the abstract lookup finds nothing.
  - Everything else (job threads, database, routes, the page) is the real app.
"""

import ipaddress
import os
import re
import socket
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

PAPERS = 50  # three grading batches of 20
SCORE_SECONDS = float(os.environ.get("LIT_REVIEW_E2E_SCORE_SECONDS", "1"))
HOLD_SECONDS = 180  # how long a held batch waits for the Stop before carrying on regardless
ABSTRACT = "This study measures the effect of coral growth on reef output under field conditions over two seasons. "


def _is_local(host):
    if host in (None, ""):
        return True
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def block_network():
    real_connect, real_connect_ex, real_getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def refuse(what, target):
        raise RuntimeError(f"e2e: the app tried to reach the network ({what}: {target!r}); a fake is missing")

    def connect(self, address):
        if not _is_local(address[0] if isinstance(address, tuple) else address):
            refuse("connect", address)
        return real_connect(self, address)

    def connect_ex(self, address):
        if not _is_local(address[0] if isinstance(address, tuple) else address):
            refuse("connect_ex", address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if not _is_local(host):
            refuse("DNS lookup", host)
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo


def install_fakes():
    import abstracts
    import llm
    import openalex

    import db

    batches = {"scored": 0, "stopped_once": False}

    def hold_until_stopped():
        """Until the browser has stopped a run once, hold every grading batch after the first, so
        the Stop always lands while papers are left (no race against a fixed delay, however slow
        the machine). After that first stop, nothing is held, so the resumed run finishes."""
        deadline = time.monotonic() + HOLD_SECONDS
        while not batches["stopped_once"] and time.monotonic() < deadline:
            if any(job.get("stop_requested") for job in db.list_jobs()):
                batches["stopped_once"] = True
                return
            time.sleep(0.2)

    def complete(ai_api, model, system, user, schema, max_tokens):
        properties = (schema or {}).get("properties", {})
        if "queries" in properties:
            parsed = {"queries": ["coral reef growth rates", "reef fish recruitment"], "title": "Coral reef growth"}
        else:
            if batches["scored"] >= 1:
                hold_until_stopped()
            time.sleep(SCORE_SECONDS)
            batches["scored"] += 1
            ids = re.findall(r'<paper id="(\d+)">', user)
            parsed = {"scores": [{"id": i, "comparison": "Compared.", "bracket": "strong", "score": 60 + int(i) % 40} for i in ids]}
            if "title" in properties:
                parsed["title"] = "Coral growth criteria"
        return parsed, llm.Usage(1000, 200, model=model, provider=ai_api)

    llm._complete_json = complete

    def search_all(query, from_date=None, to_date=None, max_results=None):
        papers = [
            {
                "id": f"W77{i:03d}", "source": "openalex", "title": f"Coral reef study {i}: growth and recruitment",
                "year": 2024, "publication_date": "2024-05-01", "abstract": ABSTRACT, "authors": ["R. Diver"],
                "citation_count": i, "doi": f"https://doi.org/10.5555/reef.{i}",
            }
            for i in range(PAPERS)
        ]
        return papers[: max_results or PAPERS], PAPERS

    openalex.search_all = search_all

    def lookup_batch(papers, skip_sources=frozenset(), answers=None):
        return {key: abstracts.Lookup(None, None, {}, frozenset(), True) for key, _, _ in papers}

    abstracts.lookup_batch = lookup_batch


def main():
    block_network()
    install_fakes()
    import app

    return app.main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
