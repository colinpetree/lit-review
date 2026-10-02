"""Provider-agnostic LLM interface for query expansion and relevance scoring.

Prompts, JSON schemas and score handling live here and are shared by every
provider. Each provider's SDK specifics (client, structured-output request,
error mapping) live in its own module under providers/, behind one function,
complete_json. To add a provider: write that module, register it in
PROVIDERS, list its models in MODELS, and mirror the models in the frontend's
lib/models.js. Callers in app.py pass `ai_api` and `model` explicitly.
"""

import importlib

from providers import LLMError

# provider id -> module exposing complete_json(). The ids are also the
# credential names in credentials.py and what analysis_run.ai_api stores.
# Modules are imported on first use (_provider_module), so a provider whose SDK
# isn't installed only breaks that provider, and startup doesn't load all four SDKs.
PROVIDERS = {
    "anthropic": "providers.anthropic",
    "openai": "providers.openai",
    "gemini": "providers.gemini",
}

# provider id -> {model id: {input/output USD per million tokens (approximate,
# for the cost estimate only), max_output_tokens}}. The first model listed for
# a provider is its default. A model not listed here is rejected by app.py.
MODELS = {
    "anthropic": {
        "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "max_output_tokens": 16000},
        "claude-sonnet-5": {"input": 2.00, "output": 10.00, "max_output_tokens": 16000},
        "claude-opus-5": {"input": 5.00, "output": 25.00, "max_output_tokens": 16000},
    },
    "openai": {
        "gpt-6-luna": {"input": 0.10, "output": 0.50, "max_output_tokens": 16000},
        "gpt-6.1-sol": {"input": 2.00, "output": 10.00, "max_output_tokens": 16000},
        "gpt-6-astra": {"input": 10.00, "output": 50.00, "max_output_tokens": 16000},
    },
    "gemini": {
        "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50, "max_output_tokens": 16000},
        "gemini-3.5-flash": {"input": 1.50, "output": 9.00, "max_output_tokens": 16000},
        # Priced at the rate for prompts up to 200k tokens; a scoring chunk is far below that.
        "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00, "max_output_tokens": 16000},
    },
}

DEFAULT_PROVIDER = "anthropic"


def default_model(ai_api):
    """The model used when a caller names a provider but no model."""
    return next(iter(MODELS[ai_api]))


class Usage:
    def __init__(self, input_tokens=0, output_tokens=0, model=None, provider=DEFAULT_PROVIDER):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.provider = provider
        self.model = model or default_model(provider)

    def add(self, other):
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens

    @property
    def usd(self):
        rates = MODELS[self.provider][self.model]
        return (
            self.input_tokens * rates["input"] + self.output_tokens * rates["output"]
        ) / 1_000_000

    def to_dict(self):
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": round(self.usd, 6),
        }


MAX_TITLE_CHARS = 60


def _clean_title(raw):
    """A model-written title, whitespace-collapsed and length-capped, or None
    if it came back empty."""
    return " ".join(str(raw or "").split())[:MAX_TITLE_CHARS] or None


def _provider_module(ai_api):
    try:
        return importlib.import_module(PROVIDERS[ai_api])
    except ModuleNotFoundError as exc:
        raise LLMError(
            f"The Python package for '{ai_api}' is not installed ({exc.name or ai_api}). "
            "Run `pip install -r requirements.txt` in the backend folder and restart the app."
        ) from exc
    except ImportError as exc:
        # Installed but unusable (e.g. a version mismatch), so "not installed"
        # would be wrong; show the real reason.
        raise LLMError(
            f"The Python package for '{ai_api}' failed to load: {exc}. Try "
            "`pip install -r requirements.txt` in the backend folder and restart the app."
        ) from exc


def _whole_number(value):
    """value as an int if it is a whole number (85, 85.0 or "85"), else None.
    Strict schemas guarantee an integer, but other forms are tolerated."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _complete_json(ai_api, model, system, user, schema, max_tokens):
    """One provider call: (parsed_json, Usage)."""
    parsed, input_tokens, output_tokens = _provider_module(ai_api).complete_json(
        model, system, user, schema, max_tokens
    )
    return parsed, Usage(input_tokens, output_tokens, model=model, provider=ai_api)


def expand_query(research_question, ai_api, model, n=4):
    """Turn a free-text research question into a handful of literal keyword
    queries suitable for OpenAlex's search param (which is literal, not
    semantic), plus a 2-4 word title naming the topic (used as the dataset's
    name). Returns (queries, Usage, title); title is None if unusable."""
    parsed, usage = _complete_json(
        ai_api,
        model,
        system=(
            f"You expand a researcher's free-text research question into at most {n} "
            "literal keyword search queries for a scholarly database (OpenAlex). "
            "Each query should be a short phrase using terminology a paper's title or "
            "abstract would actually contain - not a rephrasing of the question itself. "
            "Vary vocabulary/synonyms across queries to broaden recall. Also return a "
            "`title`: a 2-4 word title that names the topic."
        ),
        user=research_question,
        schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["title", "queries"],
            "additionalProperties": False,
        },
        max_tokens=1024,
    )
    queries = parsed.get("queries") if isinstance(parsed, dict) else None
    if not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):
        raise LLMError("The AI returned search queries in an unexpected format.")
    return queries, usage, _clean_title(parsed.get("title"))


# (name, low, high) - ordered best to worst. The prompt text below and the
# post-response enforcement in score_batch are both built from this one table
# so the two can't drift apart.
SCORE_BRACKETS = [
    ("direct", 85, 100, "the title and abstract directly address the grading prompt"),
    ("strong", 65, 84, "same topic and closely related subject or methods, but a different angle"),
    ("partial", 40, 64, "related background, or covers only part of what the prompt asks"),
    ("tangential", 15, 39, "shares vocabulary or field but does not address the prompt"),
    ("unrelated", 0, 14, "off-topic"),
]
_BRACKET_RANGES = {name: (low, high) for name, low, high, _ in SCORE_BRACKETS}
# A paper with no abstract can't be verified against the prompt from its
# title alone, so it can never score above the top of this bracket.
NO_ABSTRACT_MAX_SCORE = _BRACKET_RANGES["tangential"][1]
# Stubs like "N/A" or a one-line teaser are no more checkable than a blank
# abstract, so anything shorter than this counts as missing.
MIN_ABSTRACT_CHARS = 100
NO_JUDGMENT_RATIONALE = "The AI did not return a judgment for this paper."


def _usable_abstract(candidate):
    """The candidate's abstract if it's long enough to judge from, else ''."""
    abstract = (candidate.get("abstract") or "").strip()
    return abstract if len(abstract) >= MIN_ABSTRACT_CHARS else ""

_JUDGE_SYSTEM_PROMPT = (
    "You are a strict relevance judge for scholarly papers. The user gives a grading "
    "prompt describing what they are looking for. For each paper, compare its title and "
    "abstract against that prompt and decide how well the paper satisfies it.\n\n"
    "For each paper, write the `comparison` first: 2-4 sentences stating what the paper "
    "studies, what the grading prompt asks for, and where they overlap or fail to. Only "
    "after writing the comparison, choose a `bracket` and then a `score` that falls "
    "inside that bracket's range:\n"
    + "\n".join(f"- {name} ({low}-{high}): {desc}" for name, low, high, desc in SCORE_BRACKETS)
    + "\n\nRules:\n"
    "- Default to a low score. Most papers returned by a search are not relevant, so most "
    "should land in tangential or unrelated. Move up a bracket only when the abstract "
    "gives clear evidence, not because the topic merely sounds similar.\n"
    "- Shared keywords are not relevance. A paper on a neighboring problem scores "
    "tangential at best.\n"
    "- Base every judgment only on the given title and abstract. Never invent or assume "
    "details the text does not state.\n"
    f"- If a paper has no abstract, it can score at most {NO_ABSTRACT_MAX_SCORE} "
    "(tangential), and the comparison must say the abstract was unavailable."
)


def _enforce_bracket(score, bracket, has_abstract):
    """The schema can't constrain a score to a bracket's range, and the prompt
    alone isn't a guarantee, so clamp the score into its stated bracket, and
    cap it for a paper with no abstract. Returns the final integer score."""
    if bracket in _BRACKET_RANGES:
        low, high = _BRACKET_RANGES[bracket]
        score = max(low, min(high, score))
    score = max(0, min(100, score))
    if not has_abstract:
        score = min(score, NO_ABSTRACT_MAX_SCORE)
    return score


MAX_EXAMPLE_ABSTRACT_CHARS = 1200


def _examples_block(examples):
    """Calibration text for the user message. Each example is a paper whose
    score and reasoning the user confirmed as a good judgment."""
    if not examples:
        return ""
    parts = []
    for i, ex in enumerate(examples, 1):
        abstract = (ex.get("abstract") or "").strip()[:MAX_EXAMPLE_ABSTRACT_CHARS]
        parts.append(
            f"[Example {i}] {ex.get('title') or '(no title)'}\n"
            f"{abstract or '(no abstract available)'}\n"
            f"Score: {ex['score']}\n"
            f"Reasoning: {ex['rationale']}"
        )
    return (
        "Calibration examples: papers the user confirmed were scored well for this "
        "grading prompt. Use them only to calibrate how strictly to score. Do not score "
        "a paper higher because its topic resembles an example.\n\n"
        + "\n\n".join(parts)
        + "\n\n"
    )


def score_batch(grading_prompt, candidates, ai_api, model, examples=None, want_title=False):
    """Score a batch of candidate papers (each needs at least id/title/abstract)
    against the user's grading prompt. Returns
    ({id: {"score": 0-100 or None, "rationale": str}}, Usage, title), with one
    entry for every candidate id. The model's `comparison` text is the
    rationale. `title` is a 2-4 word title for the grading prompt when
    want_title is set and the model returned a usable one, else None.

    `examples` ({title, abstract, score, rationale} dicts) are calibration
    only and never scored themselves.

    A paper the model skips is retried once on its own. If it is skipped
    again it gets score None with an explanatory rationale, so the run can
    finish instead of re-selecting the same unscored paper forever."""
    if ai_api not in MODELS or model not in MODELS[ai_api]:
        raise LLMError(f"The model '{model}' ({ai_api}) is no longer supported.")
    scores, usage, title = _score_call(
        grading_prompt, candidates, ai_api, model, examples, want_title
    )

    missing = [c for c in candidates if str(c["id"]) not in scores]
    if missing:
        retry_scores, retry_usage, _ = _score_call(
            grading_prompt, missing, ai_api, model, examples, False
        )
        scores.update(retry_scores)
        usage.add(retry_usage)

    for c in candidates:
        scores.setdefault(
            str(c["id"]), {"score": None, "rationale": NO_JUDGMENT_RATIONALE}
        )
    return scores, usage, title


def _score_call(grading_prompt, candidates, ai_api, model, examples=None, want_title=False):
    """One LLM call. Only ids that belong to `candidates` are returned, so a
    made-up or non-numeric id from the model is dropped here."""
    has_abstract = {str(c["id"]): bool(_usable_abstract(c)) for c in candidates}
    papers_block = "\n\n".join(
        f"[{c['id']}] {c.get('title') or '(no title)'}\n"
        f"{_usable_abstract(c) or '(no abstract available)'}"
        for c in candidates
    )
    title_instruction = (
        "Also return `title`: a 2-4 word title that names what the grading prompt "
        "is looking for.\n\n"
        if want_title
        else ""
    )
    properties = {}
    if want_title:
        properties["title"] = {"type": "string"}
    required = ["title", "scores"] if want_title else ["scores"]

    parsed, usage = _complete_json(
        ai_api,
        model,
        system=_JUDGE_SYSTEM_PROMPT,
        user=(
            f"{title_instruction}{_examples_block(examples)}"
            f"Grading prompt: {grading_prompt}\n\nPapers:\n\n{papers_block}"
        ),
        schema={
            "type": "object",
            "properties": {
                **properties,
                "scores": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        # Property order matters: comparison comes before
                        # bracket/score so the model reasons first.
                        "properties": {
                            "id": {"type": "string"},
                            "comparison": {"type": "string"},
                            "bracket": {
                                "type": "string",
                                "enum": list(_BRACKET_RANGES),
                            },
                            "score": {"type": "integer"},
                        },
                        "required": ["id", "comparison", "bracket", "score"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": required,
            "additionalProperties": False,
        },
        max_tokens=MODELS[ai_api][model]["max_output_tokens"],
    )
    title = None
    if want_title:
        title = _clean_title(parsed.get("title"))
    rows = parsed.get("scores") if isinstance(parsed, dict) else None
    if not isinstance(rows, list):
        raise LLMError("The AI returned scores in an unexpected format.")
    scores = {}
    for row in rows:
        # A malformed row is skipped and the paper is retried by score_batch
        # instead of crashing the chunk.
        if not isinstance(row, dict):
            continue
        score = _whole_number(row.get("score"))
        paper_id = str(row.get("id", "")).strip()
        if score is None or paper_id not in has_abstract or not row.get("comparison"):
            continue
        scores[paper_id] = {
            "score": _enforce_bracket(score, row.get("bracket"), has_abstract[paper_id]),
            "rationale": row["comparison"],
        }
    return scores, usage, title
