"""Models hosted by Groq, through its OpenAI-compatible API.

Strict JSON-schema output is only available on some Groq models (per Groq's
structured-outputs docs), so any other model uses plain JSON mode.
"""

from .openai_compat import OpenAICompatProvider

STRICT_SCHEMA_MODELS = frozenset({"openai/gpt-oss-20b", "openai/gpt-oss-120b"})

complete_json = OpenAICompatProvider(
    "Groq",
    "groq",
    base_url="https://api.groq.com/openai/v1",
    strict_schema_models=STRICT_SCHEMA_MODELS,
).complete_json
