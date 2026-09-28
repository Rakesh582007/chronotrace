"""A fake summary writer for tests and for the documented API examples (no network, deterministic)."""

import json

# A summary a careful model could write from the whole-history facts of the demo patient K. Selvam (R1-R10).
VALID = {
    "key_finding": {
        "text": "eGFR fell by 7.1 mL/min/1.73 m² per year from October 2024 to March 2026 (63.9 to 54.1 over "
                "4 results, 503 days), faster than the KDIGO 2012 threshold of 5 per year.",
        "report_ids": ["R7", "R8", "R9", "R10"]},
    "sections": [
        {"title": "Kidney", "sentences": [
            {"text": "eGFR is 31% below the baseline (78.4 to 54.1) and creatinine is 34% above it "
                     "(1.11 to 1.49 mg/dL); the values come from different labs.",
             "report_ids": ["R1", "R2", "R3", "R10"]}]},
        {"title": "Glucose control", "sentences": [
            {"text": "HbA1c fell from a baseline of 8.8% to 7.1%.", "report_ids": ["R1", "R2", "R10"]}]}],
    "medication_rows": [
        {"date": "2023-10-02", "drug": "Metformin", "dose": "500 mg BD",
         "observed": "HbA1c -15.9% (mean 8.8 to 7.4); expected fall"},
        {"date": "2024-03-04", "drug": "Ramipril", "dose": "2.5 mg OD",
         "observed": "Creatinine +15.5%, within the ≤30% rise expected after ACEi/ARB start"},
        {"date": "2024-05-06", "drug": "Empagliflozin", "dose": "10 mg OD", "observed": "eGFR fell after the start"}],
    "data_notes": ["Reports come from 3 labs; between-lab variation is larger than the change thresholds assume.",
                   "Adherence is not recorded."],
}

# Fails the number check (9.4 is not in the facts) and the wording check ("consider").
INVALID = {**VALID, "key_finding": {"text": "eGFR fell by 9.4 per year; consider a review.",
                                    "report_ids": ["R7", "R10"]}}


class FakeLLM:
    model = "fake-llm"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def generate(self, system, prompt):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)


def use_llm(app, llm_dep, fake):
    """Make the API's summary endpoint use `fake`."""
    app.dependency_overrides[llm_dep] = lambda: (lambda: fake)
    return fake
