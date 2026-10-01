"""Claude via the `anthropic` SDK."""

import json

import anthropic

import credentials

from . import LLMError


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


def complete_json(model, system, user, schema, max_tokens):
    client = _client()
    response = _call(
        client,
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    parsed = _parsed_json(response)
    return parsed, response.usage.input_tokens, response.usage.output_tokens
