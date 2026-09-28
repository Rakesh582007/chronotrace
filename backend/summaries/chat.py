"""Ask about this patient (step 9c): a question answered only from the computed facts, with report citations.

The model gets the same facts as the whole-history summary (backend/summaries/facts.py: no name, no PDF, no
report text) plus the clinical-support results (KDIGO category, guideline criteria, eGFR projection). Its
answer passes the same checks as a summary before it is shown: every number is in the facts, every cited
report exists, and no advice, judgement, diagnosis or causal wording. One retry with the errors listed, then
the call fails. Questions and answers are not stored.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from ..trends.wording import BANNED, CAUSAL, offending
from .facts import Facts
from .guard import NUMBER, Cited, _normal, allowed_numbers
from .llm import LLM, LLMError, LLMUnavailable

MAX_QUESTION = 500

SYSTEM = """You answer a doctor's question about one patient from the JSON facts you are given. The facts were
computed by ChronoTrace from the patient's confirmed lab reports. You see no report and no patient name.

Rules
1. Use only the facts. If the facts do not contain the answer, set in_facts to false and answer in one
   sentence that the computed results do not include it.
2. Numbers: copy them from the facts (a value of 10 or more rounded to one decimal; below 10 as in the
   facts). Never calculate a new number.
3. Put the report labels (such as "R7") behind each sentence in its report_ids, only labels in facts.reports.
   Do not write the labels in the text.
4. Describe observed values, changes, thresholds and the guideline criteria in the facts. If the question
   asks what to do, which drug or dose to give, or for a diagnosis, set in_facts to false and answer that
   ChronoTrace describes the results only and the decision is the doctor's.
5. Never use these words: effective, efficacy, score, better, worse, improve, good, poor, success, should,
   must, recommend, advise, consider, continue, stop, stopped, discontinue, titrate, switch, reason to,
   reassess, recheck, repeat, monitor, diagnosis, disease, progress, progression, controlled, uncontrolled,
   abnormal, cause, caused, due to, led to, lowered, worked, attributed. The patient's recorded conditions may
   be named exactly as written.
6. One to four short sentences.

Output: {"answer": [{"text": ..., "report_ids": [...]}], "in_facts": true|false}"""


class ChatAnswer(BaseModel):
    answer: list[Cited]
    in_facts: bool


class AskFailed(RuntimeError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def check(text: str, facts: Facts) -> tuple[ChatAnswer | None, list[str]]:
    try:
        ans = ChatAnswer.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as e:
        return None, [f"the answer does not match the schema ({str(e)[:200]})"]
    errors = []
    if not ans.answer or not any(c.text.strip() for c in ans.answer):
        errors.append("the answer is empty")
    allowed = allowed_numbers(facts)
    for i, c in enumerate(ans.answer, 1):
        for n in NUMBER.findall(c.text):
            if _normal(n) not in allowed:
                errors.append(f'sentence {i}: the number {n} is not in the facts ("{c.text}")')
        words = offending(c.text, facts.allowed_phrases, (BANNED, CAUSAL))
        if words:
            errors.append(f'sentence {i}: uses the word(s) {", ".join(repr(w) for w in words)} ("{c.text}")')
        unknown = [r for r in c.report_ids if r not in facts.label_to_id]
        if unknown:
            errors.append(f"sentence {i}: report_ids {unknown} are not reports in the facts")
    return (ans if not errors else None), errors


def with_clinical(facts: Facts, clinical: dict, projection: dict | None) -> Facts:
    """The summary facts plus the clinical-support results, report ids turned into labels."""
    label = {v: k for k, v in facts.label_to_id.items()}
    labels = lambda ids: [label[i] for i in ids if i in label]
    cur = clinical["kdigo"]["current"]
    extra = {
        "kdigo_category": ({"g": cur["g"], "a": cur["a"], "risk": cur["risk"], "egfr": cur["egfr"]["value"],
                            "uacr": cur["uacr"]["value"] if cur["uacr"] else None,
                            "reports": labels([cur["egfr"]["report_id"]] + ([cur["uacr"]["report_id"]] if cur["uacr"] else []))}
                           if cur else None),
        "guideline_criteria": [{"title": c["title"], "status": c["status"], "evidence": c["evidence"],
                                "recorded_condition": c["recorded"], "reports": labels(c["report_ids"]),
                                "source": c["source"]} for c in clinical["criteria"]],
        "egfr_projection": ({"note": projection["note"], "threshold": projection["threshold"],
                             "category": projection["category"]} if projection else None),
    }
    data = {**facts.data, **extra}
    return Facts(data=data, label_to_id=facts.label_to_id, counts=facts.counts, allowed_phrases=facts.allowed_phrases)


def ask(llm: LLM, facts: Facts, question: str) -> ChatAnswer:
    first = f"Facts:\n{json.dumps(facts.data, indent=1, ensure_ascii=False, default=str)}\n\nQuestion: {question.strip()}"
    prompt, errors = first, []
    for _ in range(2):
        try:
            text = llm.generate(SYSTEM, prompt, ChatAnswer)
        except LLMUnavailable as e:
            raise AskFailed([f"the model call failed: {e}"]) from None
        except LLMError as e:
            text, errors = "", [f"the model call failed: {e}"]
        else:
            ans, errors = check(text, facts)
            if ans is not None:
                return ans
        listed = "\n".join(f"- {e}" for e in errors[:12])
        prompt = f"{first}\n\nYour previous answer:\n{text}\n\nIt was rejected:\n{listed}\n\nAnswer again, fixing each problem."
    raise AskFailed(errors)
