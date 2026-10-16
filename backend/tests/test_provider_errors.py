"""Which AI failures are worth asking again about. A background job retries only these; a rejected key,
a refusal or an unreadable answer is not retried, since asking again would only be billed again."""

import anthropic
import httpx
import openai
import pytest
from google.genai import errors as genai_errors

from providers import LLMError, anthropic as anthropic_provider, gemini, openai_compat


def response(status):
    return httpx.Response(status, request=httpx.Request("POST", "http://localhost/test"))


def raising(exc):
    def call(**kwargs):
        raise exc

    return call


class Client:
    """Anthropic's client shape: client.messages.create(...)."""

    def __init__(self, exc):
        self.messages = type("M", (), {"create": staticmethod(raising(exc))})()


class OpenAIClient:
    def __init__(self, exc):
        self.chat = type("C", (), {"completions": type("D", (), {"create": staticmethod(raising(exc))})()})()


class GeminiClient:
    def __init__(self, exc):
        self.models = type("M", (), {"generate_content": staticmethod(raising(exc))})()


def failure_of(call):
    with pytest.raises(LLMError) as caught:
        call()
    return caught.value


class TestAnthropic:
    def error(self, exc):
        return failure_of(lambda: anthropic_provider._call(Client(exc), model="m"))

    def test_rate_limits_and_server_trouble_are_worth_retrying(self):
        assert self.error(anthropic.RateLimitError("slow down", response=response(429), body=None)).retryable
        assert self.error(anthropic.InternalServerError("overloaded", response=response(529), body=None)).retryable
        assert self.error(anthropic.APIConnectionError(request=httpx.Request("POST", "http://localhost/x"))).retryable

    def test_a_rejected_key_or_bad_request_is_not(self):
        assert not self.error(anthropic.AuthenticationError("no", response=response(401), body=None)).retryable
        assert not self.error(anthropic.BadRequestError("bad", response=response(400), body=None)).retryable


class TestOpenAI:
    def error(self, exc):
        return failure_of(lambda: openai_compat.OpenAICompatProvider("OpenAI", "openai")._create(OpenAIClient(exc), model="m"))

    def test_rate_limits_and_server_trouble_are_worth_retrying(self):
        assert self.error(openai.RateLimitError("slow down", response=response(429), body=None)).retryable
        assert self.error(openai.InternalServerError("oops", response=response(500), body=None)).retryable
        assert self.error(openai.APIConnectionError(request=httpx.Request("POST", "http://localhost/x"))).retryable

    def test_a_rejected_key_or_bad_request_is_not(self):
        assert not self.error(openai.AuthenticationError("no", response=response(401), body=None)).retryable
        assert not self.error(openai.BadRequestError("bad", response=response(400), body=None)).retryable


class TestGemini:
    def error(self, exc):
        return failure_of(lambda: gemini._generate(GeminiClient(exc), model="m"))

    def test_rate_limits_server_trouble_and_dropped_connections_are_worth_retrying(self):
        assert self.error(genai_errors.APIError(429, {"error": {"message": "slow"}})).retryable
        assert self.error(genai_errors.APIError(503, {"error": {"message": "busy"}})).retryable
        assert self.error(httpx.ConnectError("gone")).retryable

    def test_a_rejected_key_is_not(self):
        assert not self.error(genai_errors.APIError(401, {"error": {"message": "no"}})).retryable
        assert not self.error(genai_errors.APIError(403, {"error": {"message": "denied"}})).retryable


def test_an_unreadable_answer_is_not_retryable():
    assert LLMError("The AI returned grades in an unexpected format.").retryable is False
