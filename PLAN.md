# Lit Review Assistant — Project Plan

## Problem

Literature review for a STEM PhD is slow: broad keyword searches return hundreds of
loosely-relevant papers, and manually reading abstracts to find the handful that are
actually novel/relevant is tedious. Goal: an app that takes a research question or topic,
pulls a wide candidate set from real scholarly databases, and uses an LLM to filter/rank
that set down to a small, high-yield shortlist — with reasoning attached, not a black-box
score. Also useful beyond active lit review: any researcher wanting to stay current on new
publications in their field can run the same search periodically to surface recent
additions.

Non-goal: this is not a tool that lets an LLM "discover" papers from its own knowledge.
Discovery must come from real API results; the LLM's job is judging relevance/novelty against
those real abstracts, to avoid hallucinated citations.

**Primary user**: any STEM graduate student or researcher doing literature review or
tracking new publications in their field — the UX, setup, and packaging decisions throughout
this plan are optimized for someone who has never used a command line or downloaded code
from GitHub before. Test data/candidates span multiple fields on purpose, so the design
can't assume one discipline's databases or vocabulary: engineering (physical sciences), biology, and health/medicine. Secondary user: the maintainer, who
will also use it occasionally and is comfortable with more technical setups, but isn't the
one the zero-setup/no-terminal requirements are protecting. (Repo is planned for public
release, so this plan uses gender-neutral language throughout regardless of the actual
user's gender.)

## Data sources

- **OpenAlex** (primary) — free, no key required, broad multidisciplinary coverage including
  engineering. Structured metadata: abstract (inverted index format, needs reconstruction),
  citation counts, concepts/topics, referenced_works, related_works. Good for keyword + topic
  search and citation-graph traversal.
- **Semantic Scholar API** (secondary) — free, works without a key at low volume, but a free
  API key raises rate limits meaningfully — supported in-app (see Architecture) since the
  pipeline batch-queries it every run. Strong in STEM, has a built-in "recommendations"
  endpoint and citation-graph lookups (citations/references of a given paper) that OpenAlex
  also supports but S2's are convenient. Good cross-check / dedupe source.
- **PubMed** — needed given health/medicine and biology are target test fields, not just
  an edge case; add via NCBI E-utilities. Free, no key required for low-volume use (an
  NCBI API key raises rate limits, same pattern as Semantic Scholar's). Authoritative for
  biomedical literature (MeSH terms, clinical studies) in a way OpenAlex/Semantic Scholar's
  broader coverage doesn't guarantee.
- **Web of Science / Scopus** — optional future addition, gated behind whether the primary
  user's institution has an API license (not just a browser subscription — those are separate
  entitlements). Worth one email to the library; don't block the build on this.

## Core pipeline

1. **Input**: research question or topic description (free text), plus optional filters
   (date range, exclude reviews, require full text available, etc).
2. **Query expansion**: LLM turns the free-text question into a handful of structured
   search queries / keyword sets (since API keyword search is literal, not semantic).
3. **Retrieval**: run expanded queries against OpenAlex (+ Semantic Scholar), pull top N
   results per query (e.g. 50-100), merge.
4. **Dedupe**: match across sources by DOI, fall back to title+year fuzzy match.
5. **Relevance/novelty scoring**: LLM scores each candidate abstract against the original
   research question. Score should include a short rationale, not just a number, so the user
   can sanity-check the ranking. Batch this — don't do one LLM call per paper if avoidable, to
   control cost. Record token usage (input/output) and computed $ cost for every LLM call
   made during the run (query expansion + scoring), even though this won't be surfaced in
   the main UI — see Cost tracking below.
6. **Shortlist**: sort by score, surface top K (e.g. 15-25) with rationale, citation count,
   year, source link. Everything else stays available but collapsed, not discarded.
7. **Iteration**: allow the user to mark papers as "yes/no/maybe", and feed that signal back
   into re-ranking remaining candidates (basic relevance feedback) or into the next search
   round's query expansion.

## Architecture

Local-only, OS-agnostic (Windows/Mac/Linux), launched on demand by the machine owner —
no networking beyond outbound calls to the scholarly APIs and whichever AI provider is
selected. No auth/multi-tenancy needed since it's single-user and never exposed off
localhost.

- **Backend**: Python + Flask (existing, working stack — reused as-is from the other
  project). Runs a local dev/WSGI server bound to `127.0.0.1` on a fixed or
  auto-selected port; app entry point opens the user's default browser to that URL via
  `webbrowser.open()`, so there's no separate "installer" UX — just run the script.
- **Frontend**: React 18 + Vite + Tailwind — a search input, a results list with
  expandable rationale per paper, label buttons (yes/no/maybe) that persist, and a
  "past runs" view. `vite build` output is served as static files by Flask, so the
  shipped app is a single Flask process (no separate frontend dev server needed at
  runtime).
- **DB**: SQLite (stdlib `sqlite3`, or `SQLAlchemy`/`sqlmodel` if an ORM layer is
  wanted) — local file, zero config, matches local-only/no-networking requirement.
  Persists retrieved papers, datasets, analysis runs, scores/rationale, and (future)
  yes/no/maybe labels so past results are always browsable. See Data model (Phase 3)
  below for the actual table design.
- **Cost tracking**: every LLM call (query expansion + scoring) logs provider, model,
  input/output token counts, and computed $ cost against whichever dataset or analysis
  run it belongs to (see `LlmCall` in Data model below). Not necessarily shown anywhere
  in the main results UI — the user doesn't need to think about it per search — but kept
  in the DB so a separate view (e.g. a simple "usage" page, or just a direct query against
  the SQLite file) can show total spend over time. This is what makes the still-open
  per-search cost cap/estimate question (see Open questions) answerable from real data
  instead of guessing.
- **API keys, general**: any credential the app needs — AI provider keys and the optional
  Semantic Scholar key — is entered once via the UI and persisted to a single encrypted
  local file (via `cryptography`'s Fernet, key file at 0600 perms), located with
  `platformdirs`'s per-user config dir. Deliberately *not* the OS-native credential
  manager (Windows Credential Manager/macOS Keychain/Secret Service): those differ enough
  across platforms — Linux Secret Service in particular is often unavailable on headless/
  minimal installs — that "same code, same behavior on every OS" wins over integrating
  with each OS's native store. Never written to SQLite or in plaintext. Semantic Scholar's
  key is optional (the API works unauthenticated at low volume); if omitted, the app just
  runs retrieval against it at the lower unauthenticated rate limit instead of blocking
  the feature.
- **LLM**: user supplies their own API key at runtime (never bundled/hardcoded) and
  picks their provider from four supported options — Claude (`anthropic` SDK), OpenAI
  (`openai` SDK), Google Gemini (`google-genai` SDK), and Groq (OpenAI-compatible API,
  reuses the `openai` SDK pointed at Groq's base URL) — via a small provider-agnostic
  interface (e.g. `expand_query()`, `score_batch()`) with one implementation per
  provider. Gemini's free tier and Groq's low cost/high speed give cost-conscious
  users (e.g. a grad student paying out of pocket) real options beyond Claude/OpenAI's
  pay-as-you-go-only pricing. Use prompt caching (Claude) / equivalent batching (other
  providers) for the scoring system prompt since it's a repeated, structured task per batch.
- **Considered, deferred**: Cohere's Rerank API as a cheap first-pass filter (rerank
  all candidates, then only send the top-K to the chosen LLM for rationale) could cut
  per-search LLM cost/latency, but adds a second API/key to manage and a coordination
  question (Cohere's ranking vs. the LLM's own judgment could disagree on what's
  "relevant"). Not worth designing in before real usage data shows per-search LLM
  cost is actually a problem — revisit in Phase 4 if so.

## Data model (Phase 3)

Retrieval and LLM judgment are modeled as two separate, independently reusable things -
not one row per "search" - so the same pulled-in pool of papers can be graded by several
different prompts/models without re-querying the scholarly APIs, and so a paper's data is
never duplicated just because it showed up in more than one dataset.

- **`Paper`** (global, source-agnostic, one row per real paper): `id`, `source` (e.g.
  `"openalex"` - `"pubmed"`/`"semantic_scholar"` later), `source_id`, `doi`, `title`,
  `abstract`, `year`, `citation_count`, `venue`, `authors`, `url`, `is_review`,
  `first_seen_at`. Dedup key is `doi` if present, else normalized `(title, year)` - the
  same rule `openalex.dedupe()` already applies in-memory per-request, just enforced once
  at insert time instead of every run. Once a paper is in this table it's "already loaded
  and ready to go" for any future dataset that pulls it in again - no re-fetch, no re-dedupe.
- **`Dataset`**: `id`, `name`, `verbose_query` (the free-text research question the user
  typed), `expanded_queries` (the LLM's keyword breakdown that produced it, kept for
  auditability), `created_at` (so the user can tell when a dataset might be stale - see
  Open questions for what "stale" should actually do).
- **`DatasetPaper`** (join table, dataset membership + soft delete): `dataset_id`,
  `paper_id`, `added_at`, `excluded_at` (nullable - set when the user manually removes a
  paper from the dataset; `NULL` means still in the dataset). Excluded papers are kept,
  not hard-deleted, so removal is reversible and never breaks a past analysis run that
  already scored them.
- **`AnalysisRun`**: `id`, `dataset_id`, `grading_prompt` (the exact prompt text used to
  judge relevance for this run - saved in full so the user can reuse or refine it later
  and compare results), `ai_api`, `ai_model`, `status` (`running` / `completed`),
  `created_at`, `completed_at`. Because `ai_api`/`ai_model` are stored per run, the same
  dataset + grading prompt can be run against different providers/models and compared
  side by side.
- **`AnalysisResult`**: `id`, `run_id`, `paper_id`, `rationale`, `score`, `created_at`.
  Rationale is generated *before* score (both in the LLM's structured-output schema field
  order and in the prompt) so the model reasons before committing to a number, rather than
  justifying a number it already picked. **Unique constraint on `(run_id, paper_id)`** -
  this single constraint is what makes an interrupted run resumable (see below), and is
  also what the final results view sorts by score (desc) and joins back to `Paper` to
  display.
- **`LlmCall`** (cost log - the concrete mechanism behind the Cost tracking bullet above):
  `id`, `purpose` (`query_expansion` or `scoring`), `dataset_id` (set for expansion
  calls), `run_id` (set for scoring calls), `ai_api`, `ai_model`, `input_tokens`,
  `output_tokens`, `usd`, `created_at`. Total spend for a dataset or a run is just
  `SUM(usd)` filtered by the right id.

**Scoring in resumable chunks**: candidates are scored in batches (the same
`SCORE_CHUNK_SIZE`-style chunking already used in Phase 2, sized to control cost/latency
without hitting output-token limits), and each chunk's `AnalysisResult` rows + its
`LlmCall` row are written in one DB transaction immediately after that chunk's LLM call
succeeds - not batched up and written all at once at the end. This means:

1. If the run is interrupted (crash, app closed, network drop) partway through, only
   fully-completed chunks exist in the DB - there's no half-written chunk to clean up,
   because the insert only happens after the LLM call already returned successfully.
2. "Resuming" a run isn't a special code path - it's re-running the same processing step.
   Re-select dataset papers (`excluded_at IS NULL`) that have no `AnalysisResult` yet
   under this `run_id` (a `LEFT JOIN ... WHERE AnalysisResult.id IS NULL`), chunk only the
   remainder, and continue. When nothing's left unscored, mark the run `completed`.
3. At the API level this is one endpoint (e.g. `POST /api/analysis-runs/<id>/process`)
   that processes remaining chunks - calling it once does a full run, calling it again
   after an interruption just picks up where it stopped.

This setup is also what enables comparing different AI providers/models against each
other: run the same dataset through multiple `AnalysisRun`s with different `ai_api`/
`ai_model` (and optionally different grading prompts) and compare their `AnalysisResult`
rankings side by side.

## Dependencies

**Backend (Python)**
- `flask` — web server + API layer (existing stack, already installed/working)
- `requests` or `httpx` — OpenAlex / Semantic Scholar HTTP clients
- `anthropic` — Claude API SDK
- `openai` — OpenAI API SDK (also reused for Groq, which is OpenAI-API-compatible)
- `google-genai` — Google Gemini API SDK
- `sqlite3` (stdlib) — DB; add `sqlalchemy` only if the schema grows enough to want an ORM
- `cryptography` + `platformdirs` — cross-platform encrypted local-file storage for the
  user's AI provider API key (deliberately not `keyring`/OS credential managers — see
  Architecture)

**Frontend (JS)**
- `react` 18, `vite` — existing, familiar
- `tailwindcss` — existing, reused from prior project's working styles

All of the above are open-source/free to use; only the AI provider API calls
themselves are metered, and that cost is the user's own (their key, their bill).

## Phased build-out

**Phase 1 — retrieval only, no AI**
Search box → OpenAlex query → flat list of results (title, abstract, year, citations, link).
Validates the data source is good enough before spending effort on ranking.

**Phase 2 — AI scoring**
Add LLM-based query expansion and relevance scoring on top of Phase 1's results. Ship the
shortlist view with rationale.

**Phase 3 — persistence + feedback loop**
Persist retrieval (datasets of papers) and LLM judgment (analysis runs that grade a
dataset against a prompt) as two separate, independently reusable models - see Data
model (Phase 3) above for the full table design and the resumable-chunk-processing
approach. Once that's in place, use yes/no/maybe labels to bias re-ranking and future
query expansion. (Under review: per-paper yes/no/maybe labels may be replaced by the
saved-prompt-with-examples design in "Saved prompts with examples" below, which is
easier for users to understand.)

**Phase 4 (optional, later)**
Semantic Scholar citation-graph exploration ("show me what cites/references this shortlisted
paper"), export shortlist to BibTeX/RIS for the user's reference manager, WoS/Scopus
integration if the primary user's institution has API access.

Also under consideration: an AI-assisted "find missing abstracts" action on the Paper Data
Sets page, on top of the manual paper-editing capability already built (`PATCH
/api/papers/<id>` - lets the user hand-correct/fill in any paper's title, abstract, DOI,
year, venue, URL; since `paper` is a single shared row, an edit is visible everywhere that
paper appears). The risk with an automated version is specifically *how* it fills the gap:
asking an LLM to recall the abstract from its own training data risks a fabricated abstract
silently sitting in a real paper's record, which violates this project's core "never invent
citations" principle worse than a blank abstract does - a hallucinated one looks legitimate.
If built, it should fetch the paper's DOI landing page and extract the real abstract text
from what's actually returned, never ask the model to recall it from memory - and even then,
flag the result as "auto-filled, unverified" (a paywall/JS-rendered page/redirect can still
yield wrong or truncated text) rather than making it indistinguishable from a real
OpenAlex-sourced abstract.

## Saved prompts with examples (decided, being built)

Status: design settled, see "Decided design" at the end of this section. The original
proposal is kept below for context.

**Problem.** The judge's strictness is now fixed by a system prompt with score brackets
(see `backend/llm.py`), but a user has no way to teach it what "relevant" means for their
specific question. Per-paper yes/no/maybe labels (Core pipeline step 7) would add a new
concept to an already slightly confusing flow (discover, dataset, analyze, results).

**Idea.** Introduce a `prompt` entity that bundles what the user is looking for with
worked examples, and apply it to datasets:
- **Prompt:** name, description (the text currently typed as `grading_prompt`), and a
  list of examples.
- **Example:** a reference to a real `paper` row, the score bracket the user says it
  belongs in, and an optional one-line note on why. The judge receives the title,
  abstract, bracket, and note as calibration.
- **Run:** a prompt applied to one or more datasets, as today, except the prompt comes
  from the saved object.

**User flow.** Write a prompt on Analyze and run it. On the results page, a wrongly scored
paper gets a "Fix this score" action (pick the correct bracket, add a note). That paper is
saved as an example on the prompt and used in the next run. A "this one is right" action
saves confirmed good calls as well.

**Design decisions to settle.**
- **Snapshot per run.** Store a copy of the prompt text and examples on each run, not just
  a link, so editing a prompt never changes what old results mean.
- **Cap examples.** Each example adds input tokens to every scoring chunk (20 papers).
  Likely 3-6 active examples; decide whether the UI uses the most recent N or lets the
  user pick which are active.
- **Balance.** Correction-only examples skew toward "too high" cases and can push scores
  too low, so allow confirming good calls too.
- **Per-prompt, not global.** Relevance depends on the question, so examples belong to a
  prompt, not to a paper.
- **Real papers only.** Examples reference actual API-returned `paper` rows, preserving
  the "never invent citations" rule.

**Suggested phasing.**
1. Saved prompts only (no examples): new `prompt` table, Analyze picks or creates one,
   prompt snapshot stored on the run. Small, and clarifies what the prompt box is.
2. Examples on prompts: results-page correction action, examples injected into
   `score_batch`. Needs a UX mockup of the results page first.
3. Later: use examples to inform query expansion.

**Open questions (resolved below).**
- How should examples be edited or removed once saved?
- Do corrections re-score the current run, or only apply to later runs?
- Does a prompt belong to one dataset, or is it reusable across datasets?

**Decided design.**
- **Scoring Prompts page** (sidebar link). Lists prompts; each card has a more-horizontal
  menu with Edit (name and description) and Delete (soft delete, like runs and datasets).
  A detail page lists the prompt's examples; removing an example is the only change
  allowed there. Examples are never added from the prompt itself.
- **Prompts are reusable across datasets** and not tied to one. A run picks a prompt.
- **Creating prompts.** (1) "New prompt" on the Scoring Prompts page: a modal with a title
  and the research question. (2) Running an analysis on Analyze with the "New prompt"
  option and a research question. In case 2 the first scoring call of the run also
  returns a 2-4 word title, and the server names the prompt with it (a placeholder of
  the question's first four words is used until then, or if no title comes back). A title
  is only ever requested for a prompt created this way, never for an existing prompt, and
  it never replaces a title the user set: saving any edit clears the pending flag.
- **Analyze picker.** The research question field becomes a type-to-filter dropdown of
  saved prompts with "New prompt" first, which reveals the research question text box.
  Choosing an existing prompt shows its description and example count.
- **Examples** are added only from a run's results, through a more-horizontal menu on a
  scored paper ("Mark as example", with a confirmation modal explaining the paper's score
  and reasoning will be used as a good example for future runs of that prompt). An
  example stores its own copy of the score and reasoning. Marking a paper already marked
  for that prompt replaces the old example. Removing an example is a hard delete.
- **Snapshot per run.** A run stores the prompt text and the examples it was scored with,
  so editing a prompt never changes old results and a resumed run scores consistently.
- **Cap.** Only the 6 most recent examples are sent to the judge.
- **Existing runs** are backfilled into prompts named after their first four words.
- **Soft deletes.** Deleting a run or prompt only hides it, so a deleted run's scored
  papers can still be used as examples. Corrections apply to later runs only, they do not
  re-score the current run.
- **Paper menu parity.** Paper cards use the same more-horizontal menu everywhere: Edit on
  dataset lists, Edit plus Mark as example on run results.

## Distribution / packaging

Target user has never used a command line or downloaded code from GitHub before, so
"clone the repo and run pip install" is not acceptable UX. Plan:

- **Packaging**: PyInstaller `--onedir` bundles the Flask backend + all Python deps +
  the built React/Vite/Tailwind static assets into a folder containing the executable
  plus its supporting files per OS (`.exe` on Windows, binary on macOS/Linux) — no
  Python install required on the user's machine. Double-click the executable to
  launch; app opens the default browser to `127.0.0.1:<port>` itself. `--onedir`
  chosen over `--onefile` because `--onefile` silently re-extracts itself to a temp
  dir on *every* launch, which is slower and worse for an app the user double-clicks
  repeatedly — a zipped folder is still a normal GitHub Releases download/unzip flow.
- **Cross-platform builds**: PyInstaller can't cross-compile, so each OS's executable
  must be built on that OS. Solved with a GitHub Actions workflow matrixed across
  `windows-latest`, `macos-latest` (Apple Silicon), and optionally an Intel Mac
  runner/`macos-13` — GitHub-hosted runners are free for this use case, so no need to
  own all target machines. Workflow builds on tag push, attaches each
  OS's zipped `--onedir` output as an asset on a GitHub Release.
- **Distribution**: users download the release asset for their OS directly from the
  GitHub Releases page — no `git clone`, no terminal.
- **Update checks**: on launch, the app calls the GitHub Releases API
  (`GET /repos/<owner>/<repo>/releases/latest`, unauthenticated — fine at this
  request volume) and compares the returned tag to the running app's embedded
  version string. If newer, show a banner/notice in the UI with a link to the new
  release download (and changelog/release notes). Full silent self-download-and-
  replace is deliberately out of scope for v1 — a running executable can't safely
  overwrite itself (especially on Windows), so keep the update flow to "notify + one
  link to click," which matches the target user's comfort level anyway. If this
  becomes annoying later, revisit with a proper updater (e.g. PyUpdater) once the
  app is stable enough to be worth the added complexity.
- **Lessons carried over from a prior project** (Flask +
  React/Tailwind, already has a working PyInstaller setup at
  `backend/pyinstaller.spec`) — real gotchas worth not rediscovering the hard way:
  - *Hidden imports via `collect_all()`*: PyInstaller's static import analysis misses
    packages that load bindings dynamically at runtime. That repo runs `collect_all()`
    for `cryptography`, `anthropic`, `pydantic`, `pydantic_core`, `anyio`, and others,
    merging the returned `datas`/`binaries`/`hiddenimports` into the `Analysis` call.
    Expect the same treatment for `anthropic`, `openai`, and `google-genai` (and
    possibly `pydantic`/`anyio` as transitive deps) — verify by actually running the
    frozen executable, not just a successful build, since these failures are runtime
    `ImportError`s a clean build won't catch.
  - *`certifi` cert bundle must be bundled as data, not just code*: `requests`/
    `anthropic`-style HTTPS calls fail cert verification once frozen unless `certifi`'s
    `cacert.pem` is included via `collect_data_files('certifi')`. This will bite every
    one of our 4 AI providers plus OpenAlex/Semantic Scholar calls if skipped — easy to
    miss because dev mode works fine (uses the system Python's certifi) and it only
    breaks in the packaged build.
  - *Dynamic class-path loading*: not directly applicable (no gunicorn for a local
    desktop app), but the general lesson carries: anything selected by a string/
    class-path at runtime (rather than a static `import`) needs an explicit
    `collect_submodules()`/hiddenimports entry, or it silently works in dev and breaks
    frozen.
  - *Not reused from that repo*: its frontend is React Router v7 in full SSR
    "framework mode" (streamed HTML, bot detection, CSP hash injection) built for a
    deployed public site — overkill for this app's local single-page UI. Reuse its
    Tailwind/PostCSS config only, not its build pipeline. Likewise its backend deps
    (`flask-sqlalchemy`, `flask-login`, `psycopg2`, `gunicorn`, `stripe`, `authlib`)
    are for a multi-user deployed site with auth/payments and mostly don't apply here.

## Resolved decisions

- **Hosting**: local-only, launched on demand by the machine owner — not deployed/hosted
  anywhere (no EC2, no server). Single-user, no auth/multi-tenancy needed.
- **Distribution**: packaged as a standalone executable per OS via PyInstaller + GitHub
  Actions, downloaded from GitHub Releases — no command line or `git clone` required of
  the end user (see Distribution / packaging above).
- **AI provider**: user's choice of Claude, OpenAI, Gemini, or Groq, using their own API
  key, persisted to a single cross-platform encrypted local file (see Architecture — not
  the OS-native keyring/credential manager). Cohere Rerank considered and deferred (see
  architecture section above).
- **Semantic Scholar key**: supported (optional) so users can get higher rate limits;
  stored the same way as the AI provider keys, but the app still works without it at
  the unauthenticated rate limit.

## Open questions to resolve before/while building

- Whether/how to surface a per-search cost estimate or cap in the main UI (the underlying
  data will exist either way — see Cost tracking above — so this is a UI/UX decision to
  make once real per-run cost numbers are in hand, not a data-modeling one).
- What a "stale" `Dataset` should actually let the user do: just start a fresh dataset
  (simplest, fine for Phase 3), or later support re-expanding/appending newly-published
  results since `created_at` into the existing dataset instead of starting over (more
  useful for the "periodically check a field for new publications" use case in Problem,
  but adds real complexity - e.g. does an appended paper get retroactively scored by past
  analysis runs?). Deliberately deferred until the app has been used enough to see what
  "stale" actually feels like in practice, rather than guessing now.
