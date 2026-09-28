"""LLM summaries (step 7): the model writes prose from facts the trend engine computed; code checks it.

write_summary() asks once, checks the answer (backend/summaries/guard.py), and on failure asks once more,
listing what was wrong. A second failure raises SummaryFailed and nothing is saved.
"""

from __future__ import annotations

import json

from .facts import Facts
from .guard import LLMSummary, check_text
from .llm import LLM, LLMError

SYSTEM = """You write a short lab-trend summary of one patient for their doctor, from the JSON facts you are
given. The facts were computed by ChronoTrace's trend engine. You see no report and no patient name.

Rules
1. Use only the facts. Say nothing that is not in them.
2. Numbers: copy them from the facts, rounded to one decimal where the facts have more (78.42 -> 78.4,
   -7.08 -> 7.1). You may leave out a minus sign when the words give the direction ("fell by 7.1"). Never
   calculate a new number: no new percentages, differences, averages, ages or counts. Write dates as in the
   facts, or as month and year.
3. Put the report labels (such as "R7") behind each statement in its report_ids. Use only labels listed in
   facts.reports. Do not write the labels in the text.
4. Describe observed values and changes only. Give no advice and no next step. Do not judge a treatment or
   say it helped. Do not say a drug caused a change: say the value changed after the drug was started.
   Do not diagnose, stage or grade anything.
5. Never use these words: effective, efficacy, score, better, worse, improve, good, poor, success, should,
   must, recommend, advise, consider, continue, stop, stopped, discontinue, titrate, switch, reason to,
   reassess, recheck, repeat, monitor, diagnosis, disease, progress, progression, controlled, uncontrolled,
   abnormal, cause, caused, due to, led to, lowered, worked, attributed. The patient's recorded conditions may
   be named exactly as written. For a drug that was ended, write "ended".
6. Say whether each change you describe is beyond or within its threshold, as the facts give it
   (latest_change_beyond_threshold, beyond_threshold, flags). A change within its threshold is not a finding.
   Mention a slope only when its status is "ok". Say when compared values come from different labs.
7. Plain, short sentences for a clinician.

Output
- key_finding: the most important flag in one or two sentences, with its report_ids. If there is no flag,
  say that no change beyond the thresholds was found in the period, citing the period's reports.
- sections: one per item of facts.body_systems, in that order, titled with that name, each with one to
  three sentences.
- medication_rows: one row per item of facts.medication_events, in date order. date: YYYY-MM-DD exactly as in
  the facts; drug: the drug name; dose: the dose as in the facts, or ""; observed: what the lab values did
  after it, from facts.medication_responses, with the expected_effect note shortened when there is one (for
  example "HbA1c -15.9% (mean 8.8 -> 7.4); expected fall"), or "no result in the window yet".
- data_notes: the notes in facts.data_notes, shortened if you like, with nothing added."""

MAX_ERRORS_SHOWN = 12


class SummaryFailed(RuntimeError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:MAX_ERRORS_SHOWN]))
        self.errors = errors


def prompt_for(facts: Facts) -> str:
    return "Facts:\n" + json.dumps(facts.data, indent=1, ensure_ascii=False)


def retry_prompt(first: str, answer: str, errors: list[str]) -> str:
    listed = "\n".join(f"- {e}" for e in errors[:MAX_ERRORS_SHOWN])
    previous = f"\n\nYour previous answer:\n{answer}" if answer else ""
    return (f"{first}{previous}\n\nYour previous answer was rejected:\n{listed}\n\n"
            "Write the summary again. Follow every rule; fix each problem listed.")


def write_summary(llm: LLM, facts: Facts) -> LLMSummary:
    first = prompt_for(facts)
    prompt, errors = first, []
    for _ in range(2):
        try:
            answer = llm.generate(SYSTEM, prompt)
        except LLMError as e:
            answer, errors = "", [f"the model call failed: {e}"]
        else:
            summary, errors = check_text(answer, facts)
            if summary is not None:
                return summary
        prompt = retry_prompt(first, answer, errors)
    raise SummaryFailed(errors)


def to_content(summary: LLMSummary, facts: Facts) -> dict:
    """The saved summary: report labels turned into report ids, with the label list for the UI's chips."""
    ids = facts.label_to_id

    def cited(c) -> dict:
        return {"text": c.text, "report_ids": [ids[r] for r in c.report_ids]}

    return {
        "key_finding": cited(summary.key_finding),
        "sections": [{"title": s.title, "sentences": [cited(x) for x in s.sentences]} for s in summary.sections],
        "medication_rows": [r.model_dump() for r in summary.medication_rows],
        "data_notes": list(summary.data_notes),
        "reports": [{"report_id": ids[r["label"]], "label": r["label"], "date": r["date"], "lab": r["lab"]}
                    for r in facts.data["reports"]],
        "basis": dict(facts.counts),
    }
