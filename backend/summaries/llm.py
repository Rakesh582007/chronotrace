"""The hosted LLM that writes summaries: Gemini through the official google-genai SDK.

Settings (.env): LLM_PROVIDER=gemini, LLM_API_KEY, LLM_MODEL. Temperature 0.2, 30 s timeout, JSON output
constrained to the LLMSummary schema. Tests use a fake with the same generate() method.
"""

from __future__ import annotations

from typing import Protocol

from ..config import setting
from .guard import LLMSummary

TIMEOUT_SECONDS = 30
TEMPERATURE = 0.2


class LLMError(RuntimeError):
    """The model call failed (timeout, network, API error)."""


class LLMConfigError(RuntimeError):
    """The LLM settings are missing or name an unsupported provider."""


class LLM(Protocol):
    model: str

    def generate(self, system: str, prompt: str) -> str:
        """The model's answer (JSON text). Raises LLMError."""


class GeminiLLM:
    def __init__(self, api_key: str, model: str):
        from google import genai
        from google.genai import types

        self.model = model
        self._key = api_key
        self._types = types
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_SECONDS * 1000))

    def generate(self, system: str, prompt: str) -> str:
        t = self._types
        try:
            r = self._client.models.generate_content(
                model=self.model, contents=prompt,
                config=t.GenerateContentConfig(
                    system_instruction=system, temperature=TEMPERATURE, response_mime_type="application/json",
                    response_schema=LLMSummary,
                    automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True)))
        except Exception as e:                       # timeout, network or API error: never show the key
            raise LLMError(f"{type(e).__name__}: {str(e).replace(self._key, '***')[:300]}") from None
        return r.text or ""


def get_llm() -> LLM:
    provider, key, model = setting("LLM_PROVIDER").lower(), setting("LLM_API_KEY"), setting("LLM_MODEL")
    if provider != "gemini":
        raise LLMConfigError("summaries need LLM_PROVIDER=gemini in .env")
    missing = [k for k, v in (("LLM_API_KEY", key), ("LLM_MODEL", model)) if not v]
    if missing:
        raise LLMConfigError(f"summaries need {' and '.join(missing)} in .env")
    return GeminiLLM(key, model)
