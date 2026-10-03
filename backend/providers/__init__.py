"""One module per AI provider SDK. Each exposes the same function:

    complete_json(model, system, user, schema, max_tokens)
        -> (parsed_dict, input_tokens, output_tokens)

and raises LLMError (with a message fit to show the user) for every way a call
can fail: missing or rejected key, rate limit, connection failure, refusal,
cut-off, or unparseable output. Prompts, schemas and score handling live in
llm.py and are shared by every provider.
"""


class LLMError(Exception):
    """Missing credentials or an unrecoverable provider error. `usage` is set when
    the model was called and billed before the failure (an answer that could not
    be used), so the caller can still record what it cost."""

    def __init__(self, message="", usage=None):
        super().__init__(message)
        self.usage = usage
