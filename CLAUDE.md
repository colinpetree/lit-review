# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Lit Review: a local-only tool for any STEM graduate student or researcher to
search scholarly databases (currently OpenAlex) and use an LLM to rank/filter results
against a research question. It serves both active literature review and periodically
checking a field for new publications. Test data/candidates deliberately span multiple
fields (engineering/physical sciences, biology, health/medicine) so the design
can't assume one discipline's databases or vocabulary. See [PLAN.md](PLAN.md) for the
full design: data sources, pipeline stages, architecture decisions, and phased build-out.

Current state: Phases 1-3 are built (retrieval, AI query expansion and relevance scoring, SQLite
persistence, multi-page UI), and so is most of what came after: four search sources (OpenAlex,
Semantic Scholar, Elsevier/Scopus, PubMed), three AI providers (Anthropic, OpenAI, Google Gemini;
the user picks one per run), checking a dataset for new papers, retraction handling, export
(CSV, RIS, BibTeX), a cost estimate with a spending threshold and per-run limit, backup and
restore, and Deleted Items (datasets, prompts and runs are soft-deleted; Deleted Items is the
only place anything is removed for good). The big missing piece is packaging (see PLAN.md,
Distribution / packaging), which the primary user needs.

Two audiences matter for UX/packaging decisions: the primary user has never used a
command line, so end-user distribution must be a double-click executable (no
`git clone`, no `pip install`). See the Distribution section of PLAN.md before touching
packaging. The maintainer (secondary user) works from source as described below.

## Commands

**Backend** (from `backend/`, using the existing `.venv`):
```
pip install -r requirements.txt
python app.py                     # http://127.0.0.1:5175, opens browser
```
Every line in `requirements.txt` is pinned to the version that was tested (the provider SDKs
use newer parameters, such as `output_config` in `providers/anthropic.py`, that an older
release would reject). When bumping one, run the whole test suite, since the tests fake the
provider call and will not notice an SDK change by themselves. Check one real scoring call
with your own key before shipping an SDK bump, and keep PLAN.md's packaging hidden-imports
list in sync with the provider modules.

**Frontend** (from `frontend/`):
```
npm install
npm run dev       # Vite dev server with HMR, proxies /api to Flask on 5175
npm run build     # outputs to backend/static, which Flask serves
npm run lint      # oxlint
```

**Tests** (pytest for the backend, Vitest for the frontend `src/lib` modules; components are checked by hand):
```
cd backend; .venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q                          # all backend tests
.venv\Scripts\python -m pytest tests/test_dates.py -k month  # one file / one test
cd frontend; npm test                                      # all frontend tests (fnm preamble below)
npx vitest run src/lib/paperFilter.test.js                 # one frontend file
```
`backend/tests/conftest.py` has two autouse fixtures that every test gets: the database and
credential store are redirected to a temp dir, and any attempt to reach a non-loopback host
(connect, UDP send or DNS lookup, so it covers the AI provider SDKs and `requests`) raises
`RuntimeError`, so a test cannot touch real data or spend money. Use the `client`
fixture (it sends the app's real Host) and `fake_llm` (replaces the provider call) rather than
patching around them. Tests marked `xfail(strict=True)` document a known bug; remove the marker when
the bug is fixed. `LIT_REVIEW_DATA_DIR` and `LIT_REVIEW_CONFIG_DIR` env vars move the database and
the saved keys elsewhere; they are for development and tests only, so use them (never the real
profile) when trying risky changes by hand.

### Node/npm in Claude tool shells

Node is managed by fnm (Node 24, same as the earlier project), not installed
system-wide. The user's PowerShell `$PROFILE` activates it, but the Bash/PowerShell tool
shells do not load the profile, so `npm` is "not recognized" there. In each PowerShell
tool call that needs node/npm, activate fnm first:

```powershell
$fnm="$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Schniz.fnm_Microsoft.Winget.Source_8wekyb3d8bbwe\fnm.exe"
& $fnm env --shell powershell | Out-String | Invoke-Expression
& $fnm use 24.19.0 2>&1 | Out-Null
cd "$(git rev-parse --show-toplevel)\frontend"
npm run build
```

Shell state does not persist between tool calls, so repeat this preamble each time. Use
PowerShell for this, not Bash (fnm is set up for PowerShell). If 24.19.0 is gone, list
installed versions in `%APPDATA%\fnm\node-versions` and use one of those.

## Architecture

Single Flask process serves both the API and the built frontend; there is no separate
frontend server at runtime. `vite build` writes straight into `backend/static`, so a
rebuild is required for Flask to pick up frontend changes. The catch-all route in
`backend/app.py` is `safe_join`-guarded and falls back to `index.html` so client-side
routes survive refresh. An unknown `/api/...` path is a JSON 404, not the app page. In dev, run
Flask on 5175 (hardcoded) next to `npm run dev`.

**Request guard (do not weaken).** The app listens on 127.0.0.1 only, but a website open in the
user's own browser can still reach it. `reject_foreign_requests` in `app.py` therefore refuses
any request whose `Host` is not `127.0.0.1:5175` or `localhost:5175` (DNS rebinding) and any
POST/PATCH/DELETE whose `Origin` is present and is not one of those (a plain cross-site POST
needs no preflight, and routes like `/process` and `/find-abstracts` take no body, so the
JSON-only body parsing does not protect them). A request with no `Origin` is allowed (curl,
tests). Consequences: a new route never needs CORS and must not add it; every mutating route is
covered automatically; tests must use the `client` fixture, which sends the right Host. The Vite
dev proxy (`vite.config.js`) rewrites Host, and rewrites Origin only when it came from a localhost
page, so a website posting to the dev server is still refused. Every response also carries
`X-Frame-Options: DENY`, a `frame-ancestors 'none'` CSP, `nosniff` and `no-referrer`; `/api/*`
responses are `no-store`. Anything that logs an exception from an outside API must pass it through
`source_http.redact` (OpenAlex and Springer take the key as a query parameter, and `requests`
puts the whole URL in its error text). Links to papers must pass `source_http.safe_url` on the
way in (only http/https) and `isHttpUrl` (`lib/format.js`) on the way out.

**Request validation.** A route reads its body with `_json_body()` (must be a JSON object) and
takes fields through the helpers in `app.py` (`_str`, `_int_id`, `_token_count`,
`_clean_queries`), which raise `InvalidRequest`; one error handler turns that into a 400 with
the message, so a route does not need its own try/except for them. Never call
`request.get_json` directly or `int()`/`.strip()` on a body value: a list, bool or huge number in
the wrong place was a 500. Limits are constants beside the helpers (queries: `llm.MAX_QUERIES` of
`llm.MAX_QUERY_CHARS`, since each runs against every source; paper fields; token counts; ids must
fit SQLite) and `MAX_REQUEST_BYTES` (1 MB, a 413) covers the whole body. `llm.expand_query` cleans
what the model returns to the same limits, and when the model was billed for an unusable answer
the `LLMError` carries `usage` so the route still logs the cost. Any other exception is a JSON
500 with the traceback in the log (through `redact`); an `HTTPException` (404, 405, 413) keeps
its status and is JSON for `/api/*`. The two long text boxes (research question, new prompt) have
a matching `maxLength` in the page. `tests/test_validation.py` has the table of bad bodies; add a
row there for any new route field.

**One slow job per run or dataset.** `POST /api/analysis-runs/<id>/process` and
`POST /api/datasets/<id>/find-abstracts` hold an `_exclusive(kind, id)` lock (non-blocking) for
the whole call; a second request for the same run or dataset gets **409** at once. Stopping a
request in the browser does not stop the server's call to the AI model, so without this a quick
Stop then Resume, or a second tab, scores the same papers twice and pays twice. Any new route
that does slow billable work should use it. Clients treat 409 as "busy, not failed":
`driveAnalysisRun` waits 2 s and retries (up to 30 times, honoring Abort) and `startLookup` ends
quietly; `lib/api.js` puts the HTTP status on thrown errors as `error.status` for this.

**One app per user, and only that user.** Loopback is shared by every account on the computer,
so the port alone is not private: another signed-in user could open your copy (your datasets, AI
jobs on your API keys). So each copy requires a secret, and each user gets their own copy.

*Access (`access.py`, `require_session` in `app.py`, `lib/session.js` + `lib/api.js`).* A random
secret is created once and kept in `access.token` in the user-data dir (written atomically). The
boundary is the user's own profile folder: that file and the browser's own copy of the secret are as
private as the account's files are, and keeping a profile private is the machine owner's job, so
the app does **not** touch file permissions (it once did, with `icacls` and `whoami` on Windows;
that was removed because it only mattered on a profile open to other accounts, where the browser's
own storage is open too, and it was the source of a startup crash on account names with accented
letters). On macOS and Linux the files come out owner-only anyway, since `mkstemp` makes them that
way. The thing the OS does *not* separate is the network port: the operating system keeps accounts'
files apart but not their ports, so another signed-in user could otherwise open this app on
127.0.0.1, which is what the secret is for. The app opens the browser on
`http://127.0.0.1:PORT/#token=...`. The part after the `#` is never sent to any server, so it is in
no request, log, or Referer. `main.jsx` calls `captureTokenFromLocation()` first: it keeps the secret
in that page's `localStorage` (and in memory, if storage is blocked) and strips it from the address
bar. Every API call goes through `apiFetch` in `lib/api.js`, which sends `Authorization: Bearer
<secret>`; never call `fetch` directly for the API. `require_session` refuses (401) any `/api/*`
request without it except `/api/health` (compared in constant time); the page itself (HTML, scripts)
holds nothing private and is open. It fails closed: with no secret configured
(`app.config["ACCESS_TOKEN"]`, set only by `main()`) every API call except health is 503. A 401
anywhere sets a global "not connected" flag (`lib/session.js`), and `AppLayout` shows one banner
for it, with the same words as the server's error (a test compares them).

**It is a header, not a cookie, on purpose.** Browsers match cookies by host name only, never by
port, so a cookie for this app would be sent to every other web server the user's browser visits on
127.0.0.1, which could then use it (verified, and the reason for the redesign); and a cookie is
attached by the browser to requests other sites make. `localStorage` is kept apart per address *and
port*, and a header is only ever set by the page's own script, so neither leaks and nothing rides on
another site's request. Nothing ever sets a cookie (a test asserts it) and a cookie never
authenticates (a test asserts that too). Verified in real headless Chrome: the link signs in, a
reload stays signed in, another port in the same browser does not get the secret, and an unrelated
local web server sees no secret, cookie or authorization header. Tests use the `client` fixture,
which sends the header; `anonymous` (in `test_auth.py`) is a stranger. Dev server: the Flask
console prints the private link; open it with `127.0.0.1:5175` replaced by `localhost:5173` (the Vite
dev origin) once, and the dev server's page keeps the secret for its own origin; the proxy forwards
the header.

*One copy per user (`main()`).* In layers, because each alone has a hole:
1. **A lock file** (`single_instance.py`, `filelock`, `instance.lock`), taken first. The OS gives it
   to exactly one process and drops it when that process ends for any reason, so a crash or kill
   leaves nothing stale. It closes the race between two launches at the same moment, which both
   see a free port before either has bound one. A copy that loses it calls
   `hand_over_to_running_copy`: it reads `instance.json` (the running copy's port and id, written
   after it binds), waits up to 15 s for that copy to answer as that id, opens the browser on it
   with the private link, and exits. It asks about that copy by id, not about the default port, so
   it can never open someone else's. A copy from before records existed holds the lock but writes no
   record and asks for no secret: if there is still no record after `LEGACY_GRACE_SECONDS` and the
   default port answers as Lit Review *without an instance id* (only such an older copy does), that
   is the copy and it is opened as it is, instead of waiting out the full time and failing.
2. **A port per copy** (`start_server`): from 5175 up to 20 ports. A port with anything listening
   is skipped, including another user's copy of this app (it needs its owner's secret, so it is no
   use here); a port that cannot be bound is skipped too, which handles two users launching at the
   same moment and both choosing the same one. So two people signed in at once each get their own
   copy. A copy from before the lock existed is just another copy to step over.
3. **`SingleOwnerServer`**: Werkzeug sets `SO_REUSEADDR`, and on Windows that lets a second server
   bind a port another is listening on with no error (a silent second copy). On Windows it binds
   with `SO_EXCLUSIVEADDRUSE` instead and reports `PortTaken`; elsewhere `SO_REUSEADDR` is kept
   (it does not allow a second listener, and lets the app restart at once). Never use `app.run`.

*Finding out whether a port is held (`check_port`).* By connecting with a 0.25 s timeout
(`PORT_CONNECT_SECONDS`), not by waiting for a refusal (on Windows a closed loopback port takes 1 to
2 s to refuse, which slowed every launch) and not by binding (a bind cannot see a program on all
interfaces or dual-stack IPv6, verified on Windows). A held port is probed with a raw socket on
purpose, not `urllib`: it must not follow redirects, ignore proxy settings, give up after 3 s in
total (a per-read timeout restarts with every byte, so a slow program would hold startup forever)
and read at most 64 KB. `GET /api/health` returns `{"app": "lit-review", "instance": <id>}`;
`probe_port` returns `(state, reply)` and `check_port(port, instance=...)` is "ours" only for that
copy.

*A data folder that cannot be used* (blocked, read-only, full disk, damaged database) is found at
launch by `db.ensure_ready()` and the lock/secret writes, and explained plainly
(`_data_folder_problem`, exit 1), not as a traceback or as errors on the first request.

Tests that start real copies (`tests/test_app_instances.py`, about 80 s) use the test-only switches
`LIT_REVIEW_PORT` (a spare port, never 5175), `LIT_REVIEW_NO_BROWSER=1` (print "Would open <url>"
instead of opening a browser) and the data/config dir overrides, via `tests/procutil.py` (`Copy`
kills the whole process tree, since the venv's `python.exe` on Windows is a launcher for the real
interpreter). Two data folders stand for two users. Never reload the `app` module in a test: it
swaps in new copies of its classes under every other test. For a real browser check, headless
Chrome (`--headless=new --dump-dom --virtual-time-budget=...`) with a throwaway `--user-data-dir`
against real copies on spare ports works well.

### Backend modules

- `app.py` - all routes. `/api/datasets/*`,
  `/api/papers/<id>`, `/api/analysis-runs/*`, `/api/settings/api-key`.
- `openalex.py` - Works API client with retry and cross-query `dedupe`. Reconstructs
  abstracts from OpenAlex's inverted-index format (`{word: [positions]}`).
- `search_sources.py` - the paper sources a dataset can be retrieved from: OpenAlex
  (`openalex.py`), Semantic Scholar, Elsevier (Scopus Search) and PubMed (NCBI E-utilities:
  esearch for ids, then efetch XML for abstracts; keyless, paced to 3 requests/s by
  `source_http.ncbi_get`; no citation counts). A per-browser Settings switch
  (`lib/pubmedSetting.js`, on by default) hides PubMed from Discover Papers; it is a UI
  preference only, the backend still accepts `pubmed`. Springer Nature is
  deliberately lookup-only (its search matched too strictly to be useful).
  The publication date range is `from_date`/`to_date` ("YYYY-MM-DD"; the Discover fields
  take a year, month or full date, a bare `from_year`/`to_year` is still accepted), stored on the
  dataset and matched when reusing a search. Each source narrows by its own means (some only by
  year), then `search_sources._filtered` keeps only papers whose shown date is in range (a PubMed
  paper with only a month or year is stored as the 1st but kept if any day of that month/year
  overlaps the range, via `date_precision`).
  `POST /api/datasets` searches every selected source with every
  expanded query, and any source failing fails the whole retrieval with nothing saved. A
  dataset records its `sources` (NULL = OpenAlex) and "reuse an identical search" also
  matches on sources. Every source reports DOIs as `https://doi.org/...` so cross-source
  duplicates merge. Scopus results have no abstracts (fill with "Find missing abstracts");
  Semantic Scholar without a key is often rate limited. `source_http.py` holds the shared
  HTTP helpers and `SourceError`.
  **A search keeps the most relevant papers, up to a limit the user chooses**: a dataset is a
  narrow dive on one topic, and datasets are pooled when evaluating, so covering more means
  several narrower datasets, not one that pulls in thousands of loosely related papers. The
  AI writes narrow queries (`llm.expand_query`: specific 3 to 7 word phrases that combine the
  key concepts, never a bare generic term, no boolean syntax since the sources differ), and each
  query keeps its top `search_limit` (50, 100 default, 200 or 500; `search_sources.
  SEARCH_LIMIT_CHOICES`, mirrored in `lib/searchLimit.js`) from each source, ranked by relevance.
  The limit is stored on the dataset (`dataset.search_limit`, NULL on older ones, treated as the
  default), is part of reusing an identical search and of the search lock and kept-searches key,
  and the "check for new papers" uses the dataset's own. **Never read a source to the end**:
  that once made every search return thousands of papers, because the top-N cut had been what
  kept datasets narrow. OpenAlex is read by cursor (`openalex.search_all`, pages no bigger than
  what is still wanted), Semantic Scholar and Scopus by offset, PubMed by one esearch for the
  ids and efetch batches. Each search returns a `SearchResult` (a list, so it still works as
  one) carrying `total` (what the source says matches), `fetched` (what it kept, before the
  exact date check) and `capped` (a sentence saying why any were left out, else None: how many
  matched and that the N most relevant were kept, or a limit of the source's, Semantic Scholar
  1,000, Scopus 5,000, PubMed 10,000). Both kinds of limit are reported, never hidden.
  `POST /api/datasets` keeps one entry per source and query in `dataset.retrieval`, shown on the
  dataset page as "Search completeness": a one-line summary on the details card and a "Show
  details" button that opens `SearchCompletenessModal` (papers kept per search, then the
  "100 of 368" numbers per source and query for the search and for the latest check).
  Each entry also has `capped_by` ("limit" for the user's own limit, "source" for a source's): the
  modal adds a note only for a source's own limit (each once), since the numbers already show the
  user's limit, and the `capped` sentences state only the fact. A page that fails for a passing reason
  (rate limit, 5xx, dropped connection: `source_http.SourceUnavailable`, or the same kinds of
  `requests` error in `openalex._fetch_page`) is asked again up to `PAGE_ATTEMPTS` times, so one
  hiccup does not discard the pages already read; a quota that ran out, a rejected key or a
  rejected query is not retried. Past that the retrieval is still one request that fails as a
  whole with nothing saved, but the searches that did finish are kept in memory for 10 minutes
  (`app._SEARCH_CACHE`, at most 20,000 papers held, dropped when the retrieval succeeds), so the
  retry button only re-runs what did not finish. The
  same search (question, dates, sources, queries) cannot run twice at once: the second gets a 409.
  A finished retrieval is saved by `db.save_retrieved_dataset` in one transaction (dataset, the
  expansion's cost, papers and membership), so a failed save leaves no empty dataset behind.
  **Check for new papers** (`POST /api/datasets/<id>/refresh`, the dataset page's button): runs the
  saved queries and sources again, with no AI call, and adds only papers not already in the dataset
  (`db.save_refresh`, one transaction; excluded and read states are untouched, and a seen paper's
  citation count is raised, never lowered). It searches a **narrowed window** (`_refresh_window`:
  from 45 days before the last check, or before the dataset was made, to the original end date),
  because the whole range again returns the same most-relevant papers and a new one rarely makes
  the cut; the overlap covers late indexing and PubMed's issue dates. A check reads up to
  `search_sources.REFRESH_SEARCH_LIMIT` (2,500) hits per search, not the dataset's own limit:
  sources cannot skip known papers, so a small limit would be spent on them and push new ones out. A search whose end date is
  past is refused with a message. The check is recorded in `dataset.last_refresh` (JSON: `at`, the
  dates, `new_count`, and the same per-search `retrieval` entries, so a check that hit the ceiling
  says so). New papers are stamped with that check's time in `dataset_paper.added_at`, and the API
  marks `is_new` on the papers whose stamp equals `last_refresh.at`, so only the latest check's
  batch shows the "New" badge and filter. It shares the search lock and kept-searches cache
  (`("refresh", id)` key; a second click gets a 409). Nothing runs on a schedule.
  **Retractions and non-research types.** Each source reports `is_retracted` (OpenAlex outright,
  PubMed from the "Retracted Publication" type, Scopus from its "Retracted" document type;
  Semantic Scholar says nothing, so NULL) and `work_type`, stored on `paper`. Kinds that are not
  papers (`search_sources.SKIP_WORK_TYPES`: paratext, erratum, retraction notice, comment) are
  dropped by `_filtered` so they are not scored and paid for, while a retracted paper itself is
  kept and badged. A retraction learned later sticks (`db._update_known_paper` never clears it),
  and rows from before are NULL (treated as not retracted) until a search finds them again.
  OpenAlex's "retraction" type and Scopus's "Erratum"/"Retracted" strings are unverified
  against the live APIs.
- `abstracts.py` - looks up a missing abstract by DOI: Elsevier (Scopus `META_ABS`) and
  Springer Nature first, when the user has saved a key and the DOI prefix matches, then
  Semantic Scholar, then Europe PMC last (it can be slow). Accepts only abstracts of `llm.MIN_ABSTRACT_CHARS`+.
  A source that fails (bad key, quota, or a 5xx/429 reply, via `source_http.raise_if_unavailable`)
  raises `SourceError` and is skipped for the rest of the run, but a passing problem (a timeout, a
  dropped connection, a rate limit: `SourceUnavailable`) is asked again up to `PAGE_ATTEMPTS` times
  per paper first (`retry_unavailable`), so one hiccup does not switch a source off for the rest.
  A source that is too slow to answer (`SourceTimeout`, a subclass) is not asked again by the
  lookup (it is skipped for the run and the next source takes over, since retrying a slow server
  cost a minute per paper); search pages still retry timeouts.
  `source_http.get` words the cause in the message ("Could not reach Europe PMC (it took too long
  to answer)") and logs the real exception, without any key; only a real answer (including 404
  "not found") counts as asked, so an outage never marks a paper checked. DOIs go into URL paths
  through `source_http.quote_doi` (some contain `?`, `#`, `<`). Driven by `POST /api/datasets/<id>/find-abstracts` (one chunk of `FIND_ABSTRACTS_CHUNK_SIZE`=10 papers per call, looked up **at the same time** by `app._look_up_batch`, so a slow source delays only its own paper; a lookup that crashes is logged and leaves its paper to be retried, and Semantic Scholar's requests still queue one interval apart under a lock in `source_http` however many are waiting; stateless:
  the client sends back `skip_ids`/`skip_sources`; loop in `frontend/src/lib/findAbstracts.js`).
  Filled abstracts record `paper.abstract_source`. The dataset page starts this lookup
  automatically when it loads; `paper.abstract_checked_at` marks papers a lookup completed
  for without finding an abstract, so neither the automatic run nor the button asks again
  (saving a new Elsevier/Springer/Semantic Scholar key clears the marks, since a new source
  can be asked). A paper is marked only once **every source that applies has answered** (`abstracts.Lookup.complete`):
  one that was down, too slow or skipped has not been asked, so the paper stays a candidate. Which sources
  already said "no abstract" is kept per paper in `paper.abstract_answered` (JSON list, read and
  extended by `db.get_abstract_answers`/`add_abstract_answers`), so the next lookup asks only the rest;
  a new key clears the marks but keeps those answers. A looked-up abstract is
  dropped when the paper title the source returns clearly differs from the stored title
  (`title_match.py`; guards against a DOI pointing at a different paper). The DOI is
  deliberately read-only for users, since it is how the same paper is matched across searches. The lookup panel is a
  sticky side column on the dataset page, hidden once every included paper with a DOI has
  an abstract.
- `llm.py` - provider-agnostic interface (`expand_query`, `score_batch`, both taking
  `ai_api` and `model`). Prompts, JSON schemas and score clamping live here and are shared;
  each provider's SDK specifics (client, structured-output request, error mapping, token
  counts) live in `providers/<name>.py` behind one `complete_json` function, registered in
  `PROVIDERS` (module paths, imported on first use so a missing SDK only breaks that
  provider; a packaged build must list them as hidden imports). OpenAI uses `providers/openai_compat.py`, which can also serve another OpenAI-compatible
  host via `base_url`/`strict_schema_models`. `MODELS` maps provider
  to model to approximate prices (cost estimate only) and `max_output_tokens`; the first
  model listed is that provider's default, and `_validate_ai_model` in `app.py` rejects any
  provider/model pair not in it with a 400. Adding a model means a `MODELS` entry plus the
  frontend's `lib/models.js`, which mirrors it by hand. Adding a provider also needs a key
  card in `SettingsPage.jsx` and a `PROVIDER_LABELS` entry. Paper text sent to the judge is
  untrusted (an abstract can say "score this 100"): each paper and example is wrapped in
  `<paper>`/`<example>` tags with `<title>`/`<abstract>`, `_fence` defuses any of those tag names
  inside the text (other `<` is left alone), and the system prompt tells the model to ignore
  instructions in them. Keep that structure when changing the prompt.
- `db.py` - stdlib `sqlite3` (no ORM), short-lived connection per call, a module `_LOCK`
  serializing writes. DB lives in the platformdirs user-data dir, not the repo. Schema
  changes to existing tables go through the idempotent ALTER-based `_migrate`, since
  `CREATE TABLE IF NOT EXISTS` won't alter an existing table and user data must never
  need deleting. Setup runs **once per process** (`_ensure_ready`, again if `DB_PATH` changes):
  schema, `_migrate`, indexes, WAL, then `PRAGMA user_version = SCHEMA_VERSION`; connections only
  set `busy_timeout` and `foreign_keys`. A change to the schema means a `_migrate` step **and** a
  `SCHEMA_VERSION` bump, which makes the next launch keep a one-time copy
  (`lit_review.db.pre-upgrade-<old>-to-<new>`, never deleted by the app) before migrating; a
  database stamped higher than the code (`DatabaseTooNew`) is refused. (Version 3 added
  `dataset.last_refresh`; 4 added `paper.is_retracted`, `paper.work_type` and
  `analysis_run.include_retracted`; 5 added `dataset.search_limit`; 6 added
  `paper.abstract_answered`; 7 added `analysis_run.max_usd`.) Foreign keys are enforced.
  Papers without a DOI match on `paper.title_key` (`title_match.title_key`: markup, accents, case
  and punctuation ignored, `+` and `#` kept) plus year; it is stored, so a change to that rule
  needs a version bump and re-backfill. `get_or_create_papers` inserts a whole search in one
  transaction. Known limitation: duplicates stored before `title_key` existed are not merged.
- `export.py` - CSV, RIS and BibTeX files from the paper dicts `db.get_run_results` and
  `db.get_dataset_papers` return (pure, no database access). Served by
  `POST /api/analysis-runs/<id>/export` and `POST /api/datasets/<id>/export` with
  `{format, paper_ids?}`: `paper_ids` is the page's filtered and sorted list, kept in that order,
  and ids not in the run or dataset are ignored (a dataset export holds included papers only).
  Every field is outside text, so CSV cells that start with `= + - @`, tab or CR get a leading
  `'` (formula injection), BibTeX characters are escaped in one pass, and RIS values are one line.
  The file name is a slug of the run or dataset name plus the date, so the header is safe. The
  client is `lib/exportFile.js` (a POST through `apiFetch`, since a plain link could not carry the
  secret) and the "Export" entry in `RunMenu`/`DatasetMenu` (`extraItems`).
- `request_gate.py`, and **backup, restore and the trash** (`db.py`, `app.py`, `TrashPage.jsx`, the
  "Backup and restore" card in Settings). `GET /api/data/backup` is `db.write_backup` (SQLite's own
  backup API into a folder in the user's data dir, streamed and removed; never the API keys).
  `POST /api/data/restore` takes the backup file **as the raw request body** and reads it straight
  from `wsgi.input` in 1 MB pieces (`MAX_RESTORE_BYTES` 500 MB): Flask 3.0.3's `MAX_CONTENT_LENGTH` is a
  read-only 1 MB for every request, so the route must not touch `request.stream` or `get_data`.
  The upload is checked read-only and immutable (`db.validate_backup_file`: SQLite header,
  `integrity_check`, the `paper`/`dataset`/`analysis_run`/`prompt` tables, and `user_version` not above
  `SCHEMA_VERSION`), then `RequestGate.close_when_quiet` turns new `/api/*` requests away (503) and
  waits up to `RESTORE_WAIT_SECONDS` for running ones (a scoring call can be slow: a restore that
  cannot wait changes nothing and answers 409). Every `/api/*` request except `/api/health` enters the
  gate in `before_request` and leaves in `teardown_request`; a new route needs nothing. Under the gate
  `db.replace_with_backup` copies the current database to `lit_review.db.before-restore-<time>` (never
  deleted), removes the old `-wal`/`-shm`, swaps the file (`os.replace`, retried on Windows
  `PermissionError`), resets `_ready_for` and migrates; if that fails the safety copy is put back.
  One restore at a time (`_exclusive("restore", 0)`). **Trash:** `GET /api/trash`,
  `POST /api/trash/<kind>/<id>/restore` (a run gets a free name through `_unique_run_name`),
  `DELETE /api/trash/<kind>/<id>` (purge; 409 while a result run still uses the dataset or prompt) and
  `DELETE /api/trash` (empty: runs, then datasets, then prompts, listing what stayed and why). The
  trash holds datasets, prompts and runs. A dataset or prompt is held back (409) while a **live** run
  uses it ("Delete that run first") and also while a run that is itself in the trash does ("Delete
  that run permanently first": the database keeps its link), which is why Empty trash goes runs first.
  A purge runs in one transaction, **detaches** `llm_call` rows (`dataset_id`/`run_id` NULL) instead of
  deleting them so total spend stays right, and removes only the purged item's own papers that nothing
  else refers to (not every unreferenced paper).
- `access.py`, `single_instance.py` - who may use a running copy and how a second launch finds it
  (see "One app per user" above); small and self-contained.
- `credentials.py` - API keys (the three AI providers plus openalex, elsevier, springernature,
  semanticscholar; allowed names are `CREDENTIAL_PROVIDERS` in `app.py`) in a Fernet-encrypted file in the
  platformdirs config dir, guarded by thread and file locks. Deliberately not the OS
  keyring, so one mechanism works identically on every OS. The Fernet key sits in the same
  folder, so this hides keys from backups and screenshots, not from other software running as the
  user; do not describe it as secure storage. Writes are atomic (temp file, then replace). A store
  that exists but can't be read (missing or damaged key file, or it won't decrypt) is never read
  as "no keys" by anything that writes: `set_key` renames both files to `*.corrupt-<time>` first,
  readers treat it as empty (the `<NAME>_API_KEY` env fallback still works) and
  `GET /api/settings/api-key` adds `"store_error": true`, which Settings shows as a notice. The
  status response now has that one non-provider key, so code reading it must index by provider id.

### Data model

Datasets and analysis runs are separate on purpose (PLAN.md, "Data model (Phase 3)"):

- `paper` is deduped globally (by DOI, else title+year). A `dataset` is a retrieved pool
  (verbose query + LLM-expanded queries + year range) linked via `dataset_paper`, where
  exclusion is a soft `excluded_at`. A dataset's short `name` (2-4 words) is written by the
  same LLM call that expands the query (`/api/datasets/expand` returns `title`, passed on
  to `POST /api/datasets` so a retried retrieval keeps it) and is editable via
  `PATCH /api/datasets/<id>`; the long topic stays in `verbose_query` (read-only). The
  AI model that expanded the query is not a `dataset` column: it is read from that
  dataset's `query_expansion` `llm_call` row (`db.get_dataset_expansion`, shown on the
  detail page with its cost, and as `ai_api`/`ai_model` on the list for the card preview).
- An `analysis_run` scores one or more datasets with a grading prompt and model, and
  writes one `analysis_result` (score + rationale) per paper. `llm_call` logs token usage
  and USD for every LLM call. A run's `status` is a convenience, not the truth: what is left to
  do is "included papers with no result" (`count_unscored_papers`, and `unscored_count` in
  `list_all_runs`, which is what the Results list's "Incomplete" label uses). `/process` on a
  `completed` run with unscored papers (an excluded paper restored, a dataset that gained papers)
  reopens it (`db.reopen_run`) and scores only those; on a `running` run with none left it just
  marks it completed. A run's cost includes the query expansion of each dataset it uses, so a
  shared dataset's expansion counts in every run that uses it (the UI says so).
- A run leaves **retracted papers out** unless created with `include_retracted` (stored on the
  run, so resuming applies the same rule; runs from before the option keep scoring everything).
  What a run scores is defined once, in `db._included_papers_sql`, which the Results counts, the
  papers scored and what is left to score all use: never copy that SQL. A scored paper that is
  later found to be retracted keeps its result. The run page says how many were left out
  (`retracted_left_out`), so they are never omitted silently.
- **Cost before and during a run.** `POST /api/analysis-runs/estimate` takes the same body as creating
  a run and returns `{papers, chunks, input_tokens, output_tokens, usd, basis, approximate}` without
  creating anything or calling the AI. The papers come from `db.get_estimate_candidates`, which uses
  `_included_papers_sql` (with its `datasets_sql` argument standing in for a run's datasets), so it
  prices exactly what a run would score. `llm.estimate_scoring_cost` counts the prompt text at 4
  characters a token, repeats the fixed text per chunk, adds 10% for retries, and guesses 150 output
  tokens a paper; once this provider and model have scored 20+ of the user's papers
  (`db.observed_output_tokens_per_paper`) it uses their real average (`basis: "history"`), which
  matters for thinking models that bill hidden reasoning as output. A run's optional `max_usd` (set on
  create or by `PATCH`, null removes it) is checked against `db.get_run_scoring_cost` (scoring only,
  not the datasets' expansion) **before** each chunk in `_process_run_chunk`, so a run can pass it by up
  to one chunk; past it `/process` answers 400 with `limit_reached: true` and writes nothing (the run
  is not reopened), and the run dict carries `scoring_cost` and `limit_reached`. Raising the limit
  and calling `/process` again carries on. On the client, `lib/spendSetting.js` holds the per-browser
  "ask before spending more than" amount (default $1.00, 0 = always ask, blank = never ask and no
  limit) and `limitFor` (a confirmed run is limited to its estimate plus 25%, an unconfirmed one to
  the threshold); Evaluate shows the estimate (`lib/useRunEstimate.js`), asks through `ConfirmModal`
  above the threshold, and a run stopped by its limit sends the user to the run page, which offers
  "Raise limit and continue".
- Runs are resumable. The client repeatedly POSTs `/api/analysis-runs/<id>/process`, and
  each call scores one chunk (`SCORE_CHUNK_SIZE`=20) of still-unscored papers until the
  run's status is `completed`. `frontend/src/lib/driveAnalysisRun.js` is that loop.

- A `prompt` (name + description/ideal research paper contents) is reusable across datasets. Each
  run points at one via `prompt_id` but keeps its own snapshot: `grading_prompt` (the text)
  and `examples_snapshot` (the examples used), so editing a prompt never changes old runs.
  `prompt_example` rows are added only from a run's results ("Mark as example", which
  copies that paper's score and reasoning); only the newest `db.EXAMPLE_LIMIT` are sent to
  the judge. A prompt created from Evaluate gets an AI title (requested in the run's first
  scoring call via `title_pending`; never for existing prompts, and any user edit clears
  the flag). Datasets, prompts and runs are all soft-deleted (`deleted_at`) and kept in Deleted
  Items (Settings), the only place anything is removed for good (`db.purge_from_trash`).
  `db.delete_analysis_run` only sets `deleted_at`: every reader of runs already filters it (lists,
  `get_analysis_run`, `_unique_run_name`), so a deleted run 404s everywhere and its scores, dataset
  links and spending stay in the database. Purging a run clears its `llm_call.run_id` and
  `prompt_example.source_run_id` instead of deleting those rows, so spend totals and examples
  survive; until then `list_prompt_examples` hides the example's run link (the run page is gone).
  Runs deleted by versions before the first soft delete (hard-deleted in between) are simply gone.

- A run has its own `analysis_run.name`, unique among live (not deleted) runs, case-insensitive
  (`db._unique_run_name` adds " (2)" etc.; renames that clash get a 409). It starts as the
  prompt's name; for a run that created its own prompt, `name_auto` lets the AI-generated
  prompt title replace the placeholder unless the user renamed first. Renamed via
  `PATCH /api/analysis-runs/<id>` (`RunMenu` + `RenameModal`, on the Results cards
  and the run page). Old runs are backfilled from their prompt name in `_migrate`.
- Sorting and the dataset date range prefer `paper.publication_date` over `year`, so
  `db.update_paper` clears that paper's full date when it contradicts the saved year (so
  re-saving an edited paper repairs it; nothing sweeps other papers).
- User-set paper states: `paper.read_at` (global, so Read follows the paper into every
  dataset and run; set via `PATCH /api/papers/<id>` with `{read}`, deliberately outside
  `EDITABLE_PAPER_FIELDS`) and `analysis_result.relevance` (per run; NULL = neutral, else
  `relevant`/`not_relevant`; only scored papers, set via
  `PATCH /api/analysis-runs/<id>/results/<paper_id>`). Re-scoring leaves relevance alone.
  Both filter client-side in `lib/paperFilter.js` (relevance only on the run page).

Keep retrieval and LLM judgment strictly separate: the LLM only scores real
API-returned abstracts and must never invent citations.

### Frontend

React 19 + Vite + Tailwind v3 (PostCSS, `tailwind.config.js`, same as an earlier project) + react-router. Routes are in
`src/main.jsx` under a shared `AppLayout`: discover, datasets (+ `:id`), evaluate,
prompts (+ `:id`), results (+ `:id`), settings. Shared UI: `MoreMenu` (more-horizontal
popover), `Modal`/`ConfirmModal`, `PromptCombobox`. Backend calls go through `src/lib/api.js`.

Theme (Light/Dark/System, set at the top of Settings) is stored per browser in localStorage
(`lib/theme.js`) and applied as a `dark` class on `<html>`; an inline script in `index.html`
applies it before first paint. Neutrals are CSS variables in `index.css` (`:root` and `.dark`)
wired into `tailwind.config.js` as `page`, `sidebar`, `surface` and the `gray`/`stone` scales, so
they flip automatically: use `bg-surface` for cards/popovers/modals, never `bg-white`. Chromatic
colors are NOT remapped (a shade is both text and solid fill), so colored text and tints need an
explicit `dark:` variant (for example `text-blue-600 dark:text-blue-400`); solid `bg-blue-600`
buttons stay the same in both themes.

Fonts match the earlier project: Source Sans 3 and Source Code Pro, self-hosted
via `@fontsource` (latin subset, imported at the top of `src/index.css`) and mapped to
`--font-sans`/`--font-mono` in the `@theme` block. No serif is installed because nothing
uses one. `index.css` also nudges any lucide icon, or provider logo from `ProviderIcons.jsx`
(class `provider-icon`), that is a direct child of a `.flex` or `.inline-flex` by `-0.5px`, because Source Sans 3's line box makes text sit slightly above
a centered icon. That rule is unlayered, so it overrides `translate-*` utilities on such
icons; put those icons in a non-flex wrapper (as the absolute-positioned search icons are).
