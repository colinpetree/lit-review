"""Provider-agnostic LLM interface for query expansion and relevance scoring.

Only the Claude ("anthropic") provider is implemented so far. PLAN.md calls
for OpenAI/Gemini/Groq too - add them as sibling provider modules behind the
same two functions (expand_query, score_batch) when it's time; callers in
app.py should not need to change.
"""

import json

import anthropic

import credentials

MODEL = "claude-haiku-4-5"
PRICING_PER_MTOK = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}


class LLMError(Exception):
    """Missing credentials or an unrecoverable provider error."""


class Usage:
    def __init__(self, input_tokens=0, output_tokens=0, model=MODEL):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.model = model

    def add(self, other):
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens

    @property
    def usd(self):
        rates = PRICING_PER_MTOK[self.model]
        return (
            self.input_tokens * rates["input"] + self.output_tokens * rates["output"]
        ) / 1_000_000

    def to_dict(self):
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": round(self.usd, 6),
        }


def _client():
    key = credentials.get_key("anthropic")
    if not key:
        raise LLMError(
            "No Anthropic API key configured. Add one in Settings before running "
            "an AI-assisted review."
        )
    return anthropic.Anthropic(api_key=key)


def _call(client, **kwargs):
    try:
        return client.messages.create(**kwargs)
    except anthropic.AuthenticationError as exc:
        raise LLMError("Anthropic rejected the API key - check it in Settings.") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError("Anthropic rate limit reached. Please wait and try again.") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"Anthropic API error: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError("Failed to reach Anthropic. Check your network connection.") from exc


def _parsed_json(response):
    """Pull the structured-output JSON out of a response, raising LLMError
    (instead of an unhandled StopIteration/JSONDecodeError) for every way a
    response can fail to be the clean text block output_config.format
    promises - a refusal, a mid-response cutoff at max_tokens, or otherwise
    malformed JSON."""
    if response.stop_reason == "refusal":
        raise LLMError("Anthropic declined to process this request.")
    if response.stop_reason == "max_tokens":
        raise LLMError(
            "Anthropic's response was cut off before finishing - try a smaller batch."
        )

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise LLMError("Anthropic returned no text content to parse.")

    try:
        return json.loads(text_block.text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Anthropic returned unparseable JSON: {exc}") from exc


def expand_query(research_question, n=4):
    """Turn a free-text research question into a handful of literal keyword
    queries suitable for OpenAlex's search param (which is literal, not
    semantic)."""
    client = _client()
    response = _call(
        client,
        model=MODEL,
        max_tokens=1024,
        system=(
            f"You expand a researcher's free-text research question into at most {n} "
            "literal keyword search queries for a scholarly database (OpenAlex). "
            "Each query should be a short phrase using terminology a paper's title or "
            "abstract would actually contain - not a rephrasing of the question itself. "
            "Vary vocabulary/synonyms across queries to broaden recall."
        ),
        messages=[{"role": "user", "content": research_question}],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "queries": {
                            "type": "array",
                            "items": {"type": "string"},
                        }
                    },
                    "required": ["queries"],
                    "additionalProperties": False,
                },
            }
        },
    )
    queries = _parsed_json(response)["queries"]
    return queries, Usage(response.usage.input_tokens, response.usage.output_tokens)


def score_batch(research_question, candidates):
    """Score a batch of candidate papers (each needs at least id/title/abstract)
    against the research question, in one LLM call. Returns
    ({id: {"score": 0-100, "rationale": str}}, Usage)."""
    client = _client()

    papers_block = "\n\n".join(
        f"[{c['id']}] {c.get('title') or '(no title)'}\n"
        f"{c.get('abstract') or '(no abstract available)'}"
        for c in candidates
    )

    response = _call(
        client,
        model=MODEL,
        max_tokens=16000,
        system=(
            "You judge relevance of scholarly papers against a researcher's research "
            "question. For each paper, given only its title and abstract, score how "
            "relevant/novel it is to the research question from 0 (irrelevant) to 100 "
            "(highly relevant, directly on-topic), with a one-to-two sentence rationale. "
            "Base every judgment only on the given title/abstract - never invent details "
            "about a paper you don't have information on."
        ),
        messages=[
            {
                "role": "user",
                "content": f"Research question: {research_question}\n\nPapers:\n\n{papers_block}",
            }
        ],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "scores": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "score": {"type": "integer"},
                                    "rationale": {"type": "string"},
                                },
                                "required": ["id", "score", "rationale"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["scores"],
                    "additionalProperties": False,
                },
            }
        },
    )
    scores = {}
    for row in _parsed_json(response)["scores"]:
        row["score"] = max(0, min(100, row["score"]))  # schema can't enforce the range; clamp defensively
        scores[row["id"]] = row
    return scores, Usage(response.usage.input_tokens, response.usage.output_tokens)
