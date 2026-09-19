# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Lit Review Assistant: a local-only tool for any STEM graduate student or researcher to
search scholarly databases (starting with OpenAlex) and eventually use an LLM to
rank/filter results against a research question — useful both for active literature review
and for periodically checking a field for new publications. Test data/candidates
deliberately span multiple fields (engineering/physical sciences, biology,
health/medicine) so the design can't assume one discipline's databases or vocabulary. See
[PLAN.md](PLAN.md) for the full design — data sources, pipeline stages, architecture
decisions, and phased build-out. The project is currently at the start of **Phase 1**
(retrieval only, no AI yet): a search box that queries OpenAlex and shows a flat, unranked
list of results.

Two audiences matter for UX/packaging decisions: the primary user has never used a
command line, so end-user distribution must be a double-click executable (no
`git clone`, no `pip install`) — see the Distribution section of PLAN.md before touching
packaging. The maintainer (secondary user) works from source as described below.

## Architecture

Single Flask process serves both the API and the built frontend — there is no separate
frontend server at runtime.

- `backend/app.py` — Flask app. `/api/search` proxies to OpenAlex and returns JSON; a
  catch-all route (`safe_join`-guarded) serves `backend/static/` (the Vite build output)
  and falls back to `index.html` for any unknown path, so client-side routes survive a
  direct navigation/refresh.
- `backend/openalex.py` — thin OpenAlex Works API client. Notably reconstructs
  abstracts from OpenAlex's inverted-index format (`{word: [positions]}`) back into
  plain text.
- `frontend/` — React + Vite + Tailwind (v4, via `@tailwindcss/vite`). `vite build`
  outputs directly into `backend/static` (see `vite.config.js`), which is what
  `app.py` serves — so a full rebuild is required after frontend changes for the
  Flask server to pick them up (dev mode uses the Vite dev server with an API proxy
  instead; see below).
- In dev, `vite.config.js` proxies `/api` to `http://127.0.0.1:5175`, so run the
  Flask backend on port 5175 (its hardcoded default) alongside `npm run dev`.

Future phases (per PLAN.md, not yet built): LLM-based query expansion and relevance
scoring behind a provider-agnostic interface (Claude/OpenAI/Gemini/Groq), SQLite
persistence for runs/labels, and a feedback loop. When implementing these, keep
scholarly-API retrieval and LLM judgment strictly separate — the LLM must only score
real API-returned abstracts, never invent citations. PubMed (via NCBI E-utilities) and
Semantic Scholar are planned additional data sources alongside OpenAlex, not deferred —
needed for the biology/health-medicine test fields to get authoritative coverage.

## Commands

**Backend** (from `backend/`, using the existing `.venv`):
```
pip install -r requirements.txt   # flask, requests
python app.py                     # runs on http://127.0.0.1:5175, opens browser
```

**Frontend** (from `frontend/`):
```
npm install
npm run dev       # Vite dev server with HMR, proxies /api to the Flask backend
npm run build     # outputs to backend/static, for the Flask server to serve
npm run lint      # oxlint
npm run preview   # preview a production build
```

No test suite exists yet in either backend or frontend.
