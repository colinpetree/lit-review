# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Lit Review Assistant: a local-only tool for any STEM graduate student or researcher to
search scholarly databases (currently OpenAlex) and use an LLM to rank/filter results
against a research question. It serves both active literature review and periodically
checking a field for new publications. Test data/candidates deliberately span multiple
fields (engineering/physical sciences, biology, health/medicine) so the design
can't assume one discipline's databases or vocabulary. See [PLAN.md](PLAN.md) for the
full design: data sources, pipeline stages, architecture decisions, and phased build-out.

Current state: Phases 1-3 are built (OpenAlex retrieval, Claude-based query expansion and
relevance scoring, SQLite persistence, multi-page UI). Only the `anthropic` AI provider is
implemented. PubMed and Semantic Scholar are planned additional data sources, not deferred
(needed for authoritative biology/health-medicine coverage).

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

**Frontend** (from `frontend/`):
```
npm install
npm run dev       # Vite dev server with HMR, proxies /api to Flask on 5175
npm run build     # outputs to backend/static, which Flask serves
npm run lint      # oxlint
```

No test suite exists in either backend or frontend.

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
routes survive refresh. In dev, run Flask on 5175 (hardcoded) next to `npm run dev`.

### Backend modules

- `app.py` - all routes. `/api/search` (raw OpenAlex proxy), `/api/datasets/*`,
  `/api/papers/<id>`, `/api/analysis-runs/*`, `/api/settings/api-key`.
- `openalex.py` - Works API client with retry and cross-query `dedupe`. Reconstructs
  abstracts from OpenAlex's inverted-index format (`{word: [positions]}`).
- `search_sources.py` - the paper sources a dataset can be retrieved from: OpenAlex
  (`openalex.py`), Semantic Scholar and Elsevier (Scopus Search). Springer Nature is
  deliberately lookup-only (its search matched too strictly to be useful).
  `POST /api/datasets` searches every selected source with every
  expanded query, and any source failing fails the whole retrieval with nothing saved. A
  dataset records its `sources` (NULL = OpenAlex) and "reuse an identical search" also
  matches on sources. Every source reports DOIs as `https://doi.org/...` so cross-source
  duplicates merge. Scopus results have no abstracts (fill with "Find missing abstracts");
  Semantic Scholar without a key is often rate limited. `source_http.py` holds the shared
  HTTP helpers and `SourceError`.
- `abstracts.py` - looks up a missing abstract by DOI: Elsevier (Scopus `META_ABS`) and
  Springer Nature first, when the user has saved a key and the DOI prefix matches, then
  Europe PMC, then Semantic Scholar. Accepts only abstracts of `llm.MIN_ABSTRACT_CHARS`+.
  A source that fails (bad key, quota) raises `SourceError` and is skipped for the rest of
  the run. Driven by `POST /api/datasets/<id>/find-abstracts` (one chunk per call, stateless:
  the client sends back `skip_ids`/`skip_sources`; loop in `frontend/src/lib/findAbstracts.js`).
  Filled abstracts record `paper.abstract_source`. The dataset page starts this lookup
  automatically when it loads; `paper.abstract_checked_at` marks papers a lookup completed
  for without finding an abstract, so neither the automatic run nor the button asks again
  (saving a new Elsevier/Springer/Semantic Scholar key clears the marks, since a new source
  can be asked). A paper is not marked if every source errored. A looked-up abstract is
  dropped when the paper title the source returns clearly differs from the stored title
  (`title_match.py`; guards against a DOI pointing at a different paper). The DOI is
  deliberately read-only for users, since it is how the same paper is matched across searches. The lookup panel is a
  sticky side column on the dataset page, hidden once every included paper with a DOI has
  an abstract.
- `llm.py` - provider-agnostic interface (`expand_query`, `score_batch`) plus per-model
  `PRICING_PER_MTOK` used for cost tracking. Adding a model means adding a pricing entry
  here (`_validate_ai_model` in `app.py` rejects any model not in this table with a 400)
  and to the frontend's `lib/models.js`, which mirrors these keys by hand.
- `db.py` - stdlib `sqlite3` (no ORM), short-lived connection per call, a module `_LOCK`
  serializing writes. DB lives in the platformdirs user-data dir, not the repo. Schema
  changes to existing tables go through the idempotent ALTER-based `_migrate`, since
  `CREATE TABLE IF NOT EXISTS` won't alter an existing table and user data must never
  need deleting.
- `credentials.py` - API keys (Anthropic, OpenAlex) in a Fernet-encrypted file in the
  platformdirs config dir, guarded by thread and file locks. Deliberately not the OS
  keyring, so one mechanism works identically on every OS.

### Data model

Datasets and analysis runs are separate on purpose (PLAN.md, "Data model (Phase 3)"):

- `paper` is deduped globally (by DOI, else title+year). A `dataset` is a retrieved pool
  (verbose query + LLM-expanded queries + year range) linked via `dataset_paper`, where
  exclusion is a soft `excluded_at`. A dataset's short `name` (2-4 words) is written by the
  same LLM call that expands the query (`/api/datasets/expand` returns `title`, passed on
  to `POST /api/datasets` so a retried retrieval keeps it) and is editable via
  `PATCH /api/datasets/<id>`; the long topic stays in `verbose_query` (read-only).
- An `analysis_run` scores one or more datasets with a grading prompt and model, and
  writes one `analysis_result` (score + rationale) per paper. `llm_call` logs token usage
  and USD for every LLM call.
- Runs are resumable. The client repeatedly POSTs `/api/analysis-runs/<id>/process`, and
  each call scores one chunk (`SCORE_CHUNK_SIZE`=20) of still-unscored papers until the
  run's status is `completed`. `frontend/src/lib/driveAnalysisRun.js` is that loop.

- A `prompt` (name + description/research paper criteria) is reusable across datasets. Each
  run points at one via `prompt_id` but keeps its own snapshot: `grading_prompt` (the text)
  and `examples_snapshot` (the examples used), so editing a prompt never changes old runs.
  `prompt_example` rows are added only from a run's results ("Mark as example", which
  copies that paper's score and reasoning); only the newest `db.EXAMPLE_LIMIT` are sent to
  the judge. A prompt created from Analyze gets an AI title (requested in the run's first
  scoring call via `title_pending`; never for existing prompts, and any user edit clears
  the flag). Prompts, runs and datasets are soft-deleted (`deleted_at`).

Keep retrieval and LLM judgment strictly separate: the LLM only scores real
API-returned abstracts and must never invent citations.

### Frontend

React 19 + Vite + Tailwind v4 (`@tailwindcss/vite`) + react-router. Routes are in
`src/main.jsx` under a shared `AppLayout`: discover, datasets (+ `:id`), analyze,
prompts (+ `:id`), results (+ `:id`), settings. Shared UI: `MoreMenu` (more-horizontal
popover), `Modal`/`ConfirmModal`, `DeleteMenu`, `PromptCombobox`. Backend calls go through `src/lib/api.js`.

Fonts match the earlier project: Source Sans 3 and Source Code Pro, self-hosted
via `@fontsource` (latin subset, imported at the top of `src/index.css`) and mapped to
`--font-sans`/`--font-mono` in the `@theme` block. No serif is installed because nothing
uses one. `index.css` also nudges any lucide icon that is a direct child of a `.flex` or
`.inline-flex` by `-0.5px`, because Source Sans 3's line box makes text sit slightly above
a centered icon. That rule is unlayered, so it overrides `translate-*` utilities on such
icons; put those icons in a non-flex wrapper (as the absolute-positioned search icons are).
