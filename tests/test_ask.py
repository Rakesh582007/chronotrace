"""Step 9c: POST /patients/{id}/ask answers from the facts, with the summary checks."""

import pytest

from backend.demo.seed import seed
from backend.main import app, llm_dep
from backend.summaries.llm import LLMUnavailable
from tests.fake_llm import CHAT_VALID, FakeLLM, use_llm

ADVICE = {"answer": [{"text": "You should stop ramipril.", "report_ids": ["R10"]}], "in_facts": True}
INVENTED = {"answer": [{"text": "eGFR fell by 9.4 per year.", "report_ids": ["R10"]}], "in_facts": True}
REFUSAL = {"answer": [{"text": "ChronoTrace describes the results only; the decision is the doctor's.",
                       "report_ids": []}], "in_facts": False}


@pytest.fixture
def selvam(client, tmp_path):
    ids = seed(client, tmp_path, upto="R10")
    yield client, ids["patient_id"]
    app.dependency_overrides.pop(llm_dep, None)


def ask(c, pid, q="Why is the kidney card amber?"):
    return c.post(f"/patients/{pid}/ask", json={"question": q})


def test_a_checked_answer_with_report_chips(selvam):
    c, pid = selvam
    fake = use_llm(app, llm_dep, FakeLLM(CHAT_VALID))
    r = ask(c, pid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["in_facts"] is True and [x["label"] for x in body["reports"]] == ["R7", "R8", "R9", "R10"]
    assert '"guideline_criteria"' in fake.prompts[0] and '"kdigo_category"' in fake.prompts[0]
    assert "K. Selvam" not in fake.prompts[0]


@pytest.mark.parametrize("bad", [ADVICE, INVENTED])
def test_advice_and_invented_numbers_are_retried_then_rejected(selvam, bad):
    c, pid = selvam
    fake = use_llm(app, llm_dep, FakeLLM(bad, bad))
    r = ask(c, pid)
    assert r.status_code == 502 and len(fake.prompts) == 2
    fake = use_llm(app, llm_dep, FakeLLM(bad, CHAT_VALID))
    assert ask(c, pid).status_code == 200 and "It was rejected" in fake.prompts[1]


def test_a_decision_question_gets_the_refusal(selvam):
    c, pid = selvam
    use_llm(app, llm_dep, FakeLLM(REFUSAL))
    body = ask(c, pid, "Should I stop ramipril?").json()
    assert body["in_facts"] is False and body["reports"] == []


def test_unavailable_model_is_502_after_one_round(selvam):
    c, pid = selvam
    fake = use_llm(app, llm_dep, FakeLLM(LLMUnavailable("every model was unavailable"), CHAT_VALID))
    assert ask(c, pid).status_code == 502 and len(fake.prompts) == 1


def test_empty_question_is_422(selvam):
    c, pid = selvam
    assert c.post(f"/patients/{pid}/ask", json={"question": ""}).status_code == 422
