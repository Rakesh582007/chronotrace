"""The hosted LLM that writes summaries: Gemini through the official google-genai SDK.

Settings (.env): LLM_PROVIDER=gemini, LLM_API_KEY, LLM_MODEL, and optionally LLM_MODEL_FALLBACKS (comma-
separated). Temperature 0.2, JSON output constrained to the LLMSummary schema. Tests use a fake with the
same generate() method, or GeminiLLM with a fake client.

Availability (separate from the guard retry in backend/summaries/__init__.py): a 429 or 503 is retried
after 2 s, then 5 s; if the model still answers 429/503, the fallback models are tried in order, each the
same way. One call, retries and fallbacks included, stops after about 60 s; each request has at most 30 s.
Any other error is not retried here.
"""

from __future__ import annotations

import time
from typing import Protocol

from ..config import setting
from .guard import LLMSummary

TIMEOUT_SECONDS = 30               # one request
TOTAL_SECONDS = 60                 # one call: every retry and fallback model together
BACKOFF_SECONDS = (2, 5)           # waits before a model's 2nd and 3rd try
RETRY_STATUS = {429, 503}          # rate limited, overloaded: worth waiting for
MIN_REQUEST_SECONDS = 5            # do not start a request with less time than this left
TEMPERATURE = 0.2


class LLMError(RuntimeError):
    """The model call failed (timeout, network, API error, or every model unavailable)."""


class LLMConfigError(RuntimeError):
    """The LLM settings are missing or name an unsupported provider."""


class LLM(Protocol):
    model: str                     # the model that wrote the last answer

    def generate(self, system: str, prompt: str) -> str:
        """The model's answer (JSON text). Raises LLMError."""


class GeminiLLM:
    def __init__(self, api_key: str, model: str, fallbacks: tuple[str, ...] = (), client=None,
                 sleep=time.sleep, clock=time.monotonic):
        from google.genai import types

        self.models = [model] + [m for m in fallbacks if m and m != model]
        self.model = model
        self._key = api_key
        self._types = types
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_SECONDS * 1000))
        self._client, self._sleep, self._clock = client, sleep, clock

    def _clean(self, e: Exception) -> str:
        return f"{type(e).__name__}: {str(e).replace(self._key, '***')[:300]}" if self._key else str(e)[:300]

    def _request(self, model: str, system: str, prompt: str, seconds: float) -> str:
        t = self._types
        r = self._client.models.generate_content(
            model=model, contents=prompt,
            config=t.GenerateContentConfig(
                system_instruction=system, temperature=TEMPERATURE, response_mime_type="application/json",
                response_schema=LLMSummary, http_options=t.HttpOptions(timeout=int(seconds * 1000)),
                automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True)))
        return r.text or ""

    def generate(self, system: str, prompt: str) -> str:
        deadline = self._clock() + TOTAL_SECONDS
        unavailable: list[str] = []
        for model in self.models:
            for wait in (0, *BACKOFF_SECONDS):
                if wait:
                    if self._clock() + wait + MIN_REQUEST_SECONDS > deadline:
                        break
                    self._sleep(wait)
                left = deadline - self._clock()
                if left < MIN_REQUEST_SECONDS:
                    raise LLMError(f"no answer within {TOTAL_SECONDS} s: " + "; ".join(unavailable))
                try:
                    text = self._request(model, system, prompt, min(TIMEOUT_SECONDS, left))
                except Exception as e:             # timeout, network or API error: never show the key
                    status = getattr(e, "code", None)
                    if status not in RETRY_STATUS:
                        raise LLMError(f"{model}: {self._clean(e)}") from None
                    unavailable.append(f"{model} {status}")
                    continue
                self.model = model
                return text
        raise LLMError("every model was unavailable (429/503): " + "; ".join(unavailable))


def get_llm() -> LLM:
    provider, key, model = setting("LLM_PROVIDER").lower(), setting("LLM_API_KEY"), setting("LLM_MODEL")
    if provider != "gemini":
        raise LLMConfigError("summaries need LLM_PROVIDER=gemini in .env")
    missing = [k for k, v in (("LLM_API_KEY", key), ("LLM_MODEL", model)) if not v]
    if missing:
        raise LLMConfigError(f"summaries need {' and '.join(missing)} in .env")
    fallbacks = tuple(m.strip() for m in setting("LLM_MODEL_FALLBACKS").split(",") if m.strip())
    return GeminiLLM(key, model, fallbacks)
