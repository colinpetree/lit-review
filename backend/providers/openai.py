"""GPT models via the `openai` SDK."""

from .openai_compat import OpenAICompatProvider

complete_json = OpenAICompatProvider("OpenAI", "openai").complete_json
