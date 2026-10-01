"""Gemini via the `google-genai` SDK."""

import json

import httpx
from google import genai
from google.genai import errors, types

import credentials

from . import LLMError

_BLOCKED_FINISH_REASONS = {
    types.FinishReason.SAFETY,
    types.FinishReason.RECITATION,
    types.FinishReason.BLOCKLIST,
    types.FinishReason.PROHIBITED_CONTENT,
    types.FinishReason.SPII,
}


def _client():
    key = credentials.get_key("gemini")
    if not key:
        raise LLMError(
            "No Gemini API key configured. Add one in Settings before running "
            "an AI-assisted review."
        )
    return genai.Client(api_key=key)


def _generate(client, **kwargs):
    try:
        return client.models.generate_content(**kwargs)
    except errors.APIError as exc:
        message = exc.message or ""
        # Gemini reports a malformed key as a 400 INVALID_ARGUMENT, not a 401.
        if exc.code == 401 or (exc.code == 400 and "API key" in message):
            raise LLMError("Gemini rejected the API key - check it in Settings.") from exc
        if exc.code == 403:
            # A valid key can still be refused (unsupported region, no access to
            # this model), so show the provider's reason, not "bad key".
            raise LLMError(f"Gemini denied access: {message or 'permission denied'}") from exc
        if exc.code == 429:
            # Gemini reports both a per-minute rate limit and an exhausted quota
            # as 429, so don't promise that waiting helps.
            raise LLMError(
                "Gemini rate limit or quota reached. Wait a moment and try again; if it "
                "keeps happening, check your plan and billing with Google."
            ) from exc
        raise LLMError(f"Gemini API error: {message or exc.code}") from exc
    except httpx.TransportError as exc:
        raise LLMError("Failed to reach Gemini. Check your network connection.") from exc


def _parsed_json(response):
    """The JSON object in a response, raising LLMError for a blocked prompt, a
    refusal, a cut-off at the token limit, an empty reply or malformed JSON."""
    if not response.candidates:
        raise LLMError("Gemini declined to process this request.")
    candidate = response.candidates[0]
    if candidate.finish_reason in _BLOCKED_FINISH_REASONS:
        raise LLMError("Gemini declined to process this request.")
    if candidate.finish_reason == types.FinishReason.MAX_TOKENS:
        raise LLMError("Gemini's response was cut off before finishing - try a smaller batch.")
    text = response.text
    if not text:
        raise LLMError("Gemini returned no text content to parse.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Gemini returned unparseable JSON: {exc}") from exc


def complete_json(model, system, user, schema, max_tokens):
    client = _client()
    response = _generate(
        client,
        model=model,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_json_schema=schema,
        ),
    )
    parsed = _parsed_json(response)
    usage = response.usage_metadata
    if usage is None:
        return parsed, 0, 0
    # Thinking tokens are billed as output but reported separately.
    output_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
    return parsed, (usage.prompt_token_count or 0), output_tokens
