"""Providers that speak the OpenAI Chat Completions API: OpenAI itself and
Groq (same `openai` SDK pointed at Groq's base URL)."""

import json

import openai

import credentials

from . import LLMError


class OpenAICompatProvider:
    """`label` names the provider in messages shown to the user. `credential`
    is the name its API key is stored under. `strict_schema_models`, when not
    None, lists the models that accept a strict JSON-schema response format;
    any other model gets plain JSON mode, with the schema spelled out in the
    system prompt and the shape checked by the caller instead."""

    def __init__(self, label, credential, base_url=None, strict_schema_models=None):
        self.label = label
        self.credential = credential
        self.base_url = base_url
        self.strict_schema_models = strict_schema_models

    def _client(self):
        key = credentials.get_key(self.credential)
        if not key:
            raise LLMError(
                f"No {self.label} API key configured. Add one in Settings before "
                "running an AI-assisted review."
            )
        return openai.OpenAI(api_key=key, base_url=self.base_url)

    def _create(self, client, **kwargs):
        try:
            return client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise LLMError(f"{self.label} rejected the API key - check it in Settings.") from exc
        except openai.PermissionDeniedError as exc:
            # A valid key can still be refused (unsupported region, no access to
            # this model), so show the provider's reason, not "bad key".
            raise LLMError(f"{self.label} denied access: {exc.message}") from exc
        except openai.RateLimitError as exc:
            # A 429 is also how an account with no credit is reported, and
            # waiting won't fix that.
            if exc.code == "insufficient_quota" or "current quota" in exc.message.lower():
                raise LLMError(
                    f"Your {self.label} account is out of credit or over its quota. "
                    "Check your plan and billing with the provider."
                ) from exc
            raise LLMError(f"{self.label} rate limit reached. Please wait and try again.") from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"{self.label} API error: {exc.message}") from exc
        except openai.APIConnectionError as exc:
            raise LLMError(f"Failed to reach {self.label}. Check your network connection.") from exc

    def _parsed_json(self, response):
        """The JSON object in a response, raising LLMError for a refusal, a
        cut-off at the token limit, an empty reply or malformed JSON."""
        if not response.choices:
            raise LLMError(f"{self.label} returned no response to parse.")
        choice = response.choices[0]
        if choice.message.refusal or choice.finish_reason == "content_filter":
            raise LLMError(f"{self.label} declined to process this request.")
        if choice.finish_reason == "length":
            raise LLMError(
                f"{self.label}'s response was cut off before finishing - try a smaller batch."
            )
        if not choice.message.content:
            raise LLMError(f"{self.label} returned no text content to parse.")
        try:
            return json.loads(choice.message.content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"{self.label} returned unparseable JSON: {exc}") from exc

    def complete_json(self, model, system, user, schema, max_tokens):
        client = self._client()
        if self.strict_schema_models is None or model in self.strict_schema_models:
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": schema},
            }
        else:
            response_format = {"type": "json_object"}
            system = (
                f"{system}\n\nRespond with only a JSON object that matches this JSON "
                f"Schema:\n{json.dumps(schema)}"
            )
        response = self._create(
            client,
            model=model,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=response_format,
        )
        parsed = self._parsed_json(response)
        usage = response.usage
        if usage is None:
            return parsed, 0, 0
        return parsed, (usage.prompt_tokens or 0), (usage.completion_tokens or 0)
