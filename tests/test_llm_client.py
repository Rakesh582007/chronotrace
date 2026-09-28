"""Gemini availability: backoff on 429/503, fallback models, the 60 s cap (fake client, no network, no sleep)."""

import json

import pytest
from google.genai import errors

from backend import main
from backend.summaries import llm as L
from tests import fake_llm
from tests.fake_llm import VALID
from tests.test_summaries import generate, pdf_dir, saved, selvam  # noqa: F401  (fixtures)


def unavailable(code=503):
    cls = errors.ServerError if code >= 500 else errors.ClientError
    return cls(code, {"error": {"code": code, "message": "try again later", "status": "UNAVAILABLE"}})


class Answer:
    def __init__(self, text):
        self.text = text


class FakeClient:
    """Stands in for genai.Client: answers (or raises) from a script, per model, and keeps a clock."""

    def __init__(self, script, seconds_per_request=1.0):
        self.script = {m: list(v) for m, v in script.items()}
        self.calls = []
        self.now = 0.0
        self.sleeps = []
        self.per_request = seconds_per_request
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append((model, config.http_options.timeout))
        timeout = config.http_options.timeout / 1000
        if self.per_request > timeout:                               # the request is cut at its timeout
            self.now += timeout
            raise TimeoutError("read timed out")
        self.now += self.per_request
        outcome = self.script[model].pop(0) if self.script.get(model) else unavailable()
        if isinstance(outcome, Exception):
            raise outcome
        return Answer(outcome)

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s

    def clock(self):
        return self.now


def make(fake, fallbacks=("fallback-1", "fallback-2")):
    return L.GeminiLLM("secret-key", "main-model", fallbacks, client=fake, sleep=fake.sleep, clock=fake.clock)


def test_503_then_success():
    fake = FakeClient({"main-model": [unavailable(503), "answer"]})
    llm = make(fake)
    assert llm.generate("system", "prompt") == "answer"
    assert [m for m, _ in fake.calls] == ["main-model", "main-model"] and fake.sleeps == [2]
    assert llm.model == "main-model"


def test_429_is_retried_then_the_fallbacks_in_order():
    fake = FakeClient({"main-model": [unavailable(429), unavailable(503), unavailable(503)],
                       "fallback-1": [unavailable(503), "from fallback 1"]})
    llm = make(fake)
    assert llm.generate("system", "prompt") == "from fallback 1"
    assert [m for m, _ in fake.calls] == ["main-model"] * 3 + ["fallback-1"] * 2
    assert fake.sleeps == [2, 5, 2] and llm.model == "fallback-1"            # the model that answered


@pytest.mark.parametrize("error", [unavailable(400), unavailable(500), TimeoutError("read timed out")],
                         ids=["400", "500", "timeout"])
def test_other_errors_are_not_retried_here(error):
    fake = FakeClient({"main-model": [error, "never reached"]})
    with pytest.raises(L.LLMError, match="main-model"):
        make(fake).generate("system", "prompt")
    assert len(fake.calls) == 1 and fake.sleeps == []


def test_all_models_unavailable():
    fake = FakeClient({})
    with pytest.raises(L.LLMError, match="every model was unavailable") as e:
        make(fake).generate("system", "prompt")
    assert [m for m, _ in fake.calls] == ["main-model"] * 3 + ["fallback-1"] * 3 + ["fallback-2"] * 3
    assert fake.sleeps == [2, 5] * 3 and "secret-key" not in str(e.value)


def test_the_whole_call_stops_at_about_60_seconds():
    fake = FakeClient({}, seconds_per_request=12)                     # slow 503s
    with pytest.raises(L.LLMError):
        make(fake).generate("system", "prompt")
    assert fake.now <= L.TOTAL_SECONDS
    assert all(t <= L.TIMEOUT_SECONDS * 1000 for _, t in fake.calls)
    left_for_last = L.TOTAL_SECONDS - (fake.now - fake.per_request)
    assert fake.calls[-1][1] <= left_for_last * 1000                 # the last request fits in what was left


def test_fallbacks_come_from_the_settings(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "main-model")
    monkeypatch.setenv("LLM_MODEL_FALLBACKS", " fallback-1, ,fallback-2,main-model ")
    assert L.get_llm().models == ["main-model", "fallback-1", "fallback-2"]


# ---------------------------------------------------------------- through the endpoint

def use_client(fake):
    return fake_llm.use_llm(main.app, main.llm_dep, make(fake))


def test_endpoint_saves_the_fallback_models_answer(selvam):  # noqa: F811
    c, pid = selvam
    use_client(FakeClient({"main-model": [unavailable(503)] * 3, "fallback-1": [json.dumps(VALID)]}))
    r = generate(c, pid)
    assert r.status_code == 201, r.text
    assert r.json()["model"] == "fallback-1"


def test_endpoint_all_models_503_is_502_with_last_saved(selvam):  # noqa: F811
    c, pid = selvam
    use_client(FakeClient({"main-model": [json.dumps(VALID)]}))
    first = generate(c, pid).json()
    fake = FakeClient({})
    use_client(fake)
    r = generate(c, pid)
    assert r.status_code == 502
    assert "every model was unavailable" in r.json()["detail"] and r.json()["last_saved"] == first
    assert len(fake.calls) == 2 * 9                                  # the guard retry asks once more
    assert saved(c, pid).json() == first
