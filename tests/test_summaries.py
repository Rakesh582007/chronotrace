"""LLM summaries with a fake model: facts, guards, retry, 502 with the last saved summary (step 7)."""

import copy
import json

import pytest
from backend import main
from backend.demo import data as demo
from backend.demo.reports import write_pdf
from backend.demo.seed import seed
from backend.main import app
from backend.summaries import guard
from backend.summaries.llm import LLMError
from backend.trends.dictionary import infos_by_id
from backend.trends.wording import offending
from tests.conftest import signed_in_client, use_fresh_database

# A summary a careful model could write from the whole-history facts of the demo patient (R1-R10).
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


def variant(path, value):
    """VALID with one text replaced: path like ("key_finding", "text")."""
    out = copy.deepcopy(VALID)
    target = out
    for k in path[:-1]:
        target = target[k]
    target[path[-1]] = value
    return out


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


def use_llm(fake):
    app.dependency_overrides[main.llm_dep] = lambda: (lambda: fake)
    return fake


@pytest.fixture(scope="module")
def pdf_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    for r in demo.REPORTS:
        write_pdf(r, out)
    return out


@pytest.fixture
def selvam(pdf_dir, tmp_path):
    """The demo patient with R1-R10 confirmed (the whole history of the design's summary)."""
    use_fresh_database(tmp_path / "uploads")
    c = signed_in_client()
    ids = seed(c, pdf_dir)
    r10 = next(pdf_dir.glob("selvam_R10_*.pdf"))
    with open(r10, "rb") as f:
        rid = c.post(f"/patients/{ids['patient_id']}/reports",
                     files={"file": (r10.name, f, "application/pdf")}).json()["report"]["id"]
    assert c.post(f"/reports/{rid}/confirm", json={}).status_code == 200
    yield c, ids["patient_id"]
    app.dependency_overrides.clear()


def generate(c, pid, **body):
    return c.post(f"/patients/{pid}/summaries", json={"period": "all", **body})


def saved(c, pid, period="all"):
    return c.get(f"/patients/{pid}/summaries/latest?period={period}")


# ---------------------------------------------------------------- saving

def test_a_valid_summary_is_saved_with_report_ids(selvam):
    c, pid = selvam
    fake = use_llm(FakeLLM(VALID))
    r = generate(c, pid)
    assert r.status_code == 201, r.text
    s = r.json()
    assert len(fake.prompts) == 1 and s["model"] == "fake-llm" and len(s["facts_sha256"]) == 64
    assert (s["period"], s["from"], s["to"]) == ("all", "2023-06-12", "2026-03-02")
    content = s["content"]
    labels = {x["report_id"]: x["label"] for x in content["reports"]}
    assert [labels[i] for i in content["key_finding"]["report_ids"]] == ["R7", "R8", "R9", "R10"]
    assert content["basis"] == {"flags": 6, "medication_responses": 3, "reports": 10, "labs": 3}
    timeline_ids = {p["report_id"] for a in c.get(f"/patients/{pid}/timeline").json()["analytes"] for p in a["points"]}
    assert set(labels) <= timeline_ids                         # every chip links to a real report
    assert saved(c, pid).json() == s


def test_the_same_facts_give_the_same_hash(selvam):
    c, pid = selvam
    use_llm(FakeLLM(VALID, VALID))
    assert generate(c, pid).json()["facts_sha256"] == generate(c, pid).json()["facts_sha256"]


# ---------------------------------------------------------------- guards

@pytest.mark.parametrize("bad,error", [
    (variant(("key_finding", "text"), "eGFR fell by 9.4 mL/min/1.73 m² per year."), "the number 9.4 is not in the facts"),
    (variant(("sections", 1, "sentences", 0, "text"), "HbA1c fell 21% after metformin."), "the number 21 is not"),
    (variant(("sections", 0, "sentences", 0, "text"), "Consider reviewing the ramipril dose."), "'Consider'"),
    (variant(("sections", 1, "sentences", 0, "text"), "HbA1c fell because metformin worked."), "'worked'"),
    (variant(("key_finding", "text"), "The kidney disease is progressing."), "'progressing'"),
    (variant(("sections", 0, "sentences", 0, "text"), "eGFR fell by 7.1 per year, so monitor it."), "'monitor'"),
    (variant(("key_finding", "report_ids"), ["R7", "R99"]), "['R99'] are not reports in the facts"),
    (variant(("key_finding", "report_ids"), []), "cite at least one report"),
    (variant(("medication_rows", 0, "drug"), "Glipizide"), "is not a medication event in the facts"),
    ("not json", "not valid JSON"),
    ({"key_finding": {"text": "x"}}, "does not match the schema"),
], ids=["invented-number", "computed-percent", "advice", "effectiveness", "diagnosis", "monitor", "unknown-report",
        "uncited", "invented-drug", "not-json", "schema"])
def test_a_rejected_answer_is_retried_with_the_errors(selvam, bad, error):
    c, pid = selvam
    fake = use_llm(FakeLLM(bad, VALID))
    r = generate(c, pid)
    assert r.status_code == 201, r.text
    assert len(fake.prompts) == 2 and error in fake.prompts[1] and "was rejected" in fake.prompts[1]


def test_two_failures_are_502_and_nothing_is_saved(selvam):
    c, pid = selvam
    bad = variant(("key_finding", "text"), "eGFR fell by 9.4 per year; consider a review.")
    use_llm(FakeLLM(bad, bad))
    r = generate(c, pid)
    assert r.status_code == 502
    body = r.json()
    assert body["last_saved"] is None and "9.4" in body["detail"] and "'consider'" in body["detail"]
    assert saved(c, pid).status_code == 404


def test_timeout_is_502_with_the_last_saved_summary(selvam):
    c, pid = selvam
    use_llm(FakeLLM(VALID))
    first = generate(c, pid).json()
    fake = use_llm(FakeLLM(LLMError("ReadTimeout: timed out"), LLMError("ReadTimeout: timed out")))
    r = generate(c, pid)
    assert r.status_code == 502 and len(fake.prompts) == 2
    assert "timed out" in r.json()["detail"] and r.json()["last_saved"] == first
    assert saved(c, pid).json() == first                     # the saved version stays


def test_not_configured_is_503_with_the_last_saved_summary(selvam):
    c, pid = selvam                                          # conftest blanks LLM_PROVIDER: the real factory refuses
    r = generate(c, pid)
    assert r.status_code == 503 and "LLM_PROVIDER" in r.json()["detail"] and r.json()["last_saved"] is None


# ---------------------------------------------------------------- facts

def test_facts_hold_no_name_and_no_report_text(selvam):
    c, pid = selvam
    fake = use_llm(FakeLLM(VALID))
    generate(c, pid)
    facts = fake.prompts[0]
    rows, tests = set(), set()
    for rid in {p["report_id"] for a in c.get(f"/patients/{pid}/timeline").json()["analytes"] for p in a["points"]}:
        for o in c.get(f"/reports/{rid}").json()["observations"]:
            rows.add(o["row_text"])
            tests.add(o["test_text"])
    canonical = {a.name for a in infos_by_id().values()}     # the facts name analytes by the dictionary's names
    assert "selvam" not in facts.lower() and demo.PATIENT["name"] not in facts
    assert rows and not [t for t in rows if t in facts]
    assert not [t for t in tests - canonical if f'"{t}"' in facts]
    assert "CT-0001" in facts and "chronic kidney disease" in facts          # code and recorded conditions only


def test_facts_quote_the_engine(selvam):
    c, pid = selvam
    fake = use_llm(FakeLLM(VALID))
    generate(c, pid)
    facts = json.loads(fake.prompts[0].split("Facts:\n", 1)[1])
    flags = c.get(f"/patients/{pid}/flags").json()["flags"]
    assert len(facts["flags"]) == len(flags) == 6
    kdigo = next(f for f in facts["flags"] if f["level"] == "guideline")
    engine_kdigo = next(f for f in flags if f["rule_id"] == "KDIGO_RAPID_EGFR")
    assert kdigo["slope_per_year"] == round(engine_kdigo["compared"]["slope"]["per_year"], 2) == -7.08
    assert (kdigo["span_days"], kdigo["results_used"], kdigo["reports"]) == (503, 4, ["R7", "R8", "R9", "R10"])
    assert [e["drug"] for e in facts["medication_events"]] == ["Metformin", "Ramipril", "Empagliflozin"]
    assert facts["data_notes"][-1] == "Adherence is not recorded."
    labs = tuple({r["lab"] for r in facts["reports"]})
    assert not offending(json.dumps(facts, ensure_ascii=False), ("chronic kidney disease", *labs))   # guardrail


# ---------------------------------------------------------------- periods

def test_periods(selvam):
    c, pid = selvam
    between_visits = VALID | {"medication_rows": []}
    fake = use_llm(FakeLLM(between_visits))
    since = generate(c, pid, period="since_last_visit")
    assert since.status_code == 201, since.text
    assert (since.json()["from"], since.json()["to"]) == ("2025-09-01", "2026-03-02")
    facts = json.loads(fake.prompts[0].split("Facts:\n", 1)[1])
    assert facts["period"]["reports_in_period"] == 2 and facts["medication_events"] == []
    assert {f["date"] for f in facts["flags"]} == {"2026-03-02"}          # flags since the previous visit only
    # No drug event happened between the visits, so a medication row is invented.
    use_llm(FakeLLM(VALID, VALID))
    r = generate(c, pid, period="since_last_visit")
    assert r.status_code == 502 and "is not a medication event in the facts" in r.json()["detail"]
    assert r.json()["last_saved"] == since.json()
    assert generate(c, pid, period="range").status_code == 422                          # no dates
    assert generate(c, pid, period="range", **{"from": "2026-01-01", "to": "2025-01-01"}).status_code == 422
    assert generate(c, pid, period="range", **{"from": "2022-01-01", "to": "2022-12-31"}).status_code == 422
    assert saved(c, pid, "range").status_code == 404


def test_a_patient_without_reports_and_scoping(client, other_doctor):
    pid = client.post("/patients", json={"name": "Empty", "sex": "male", "birth_year": 1970}).json()["id"]
    use_llm(FakeLLM())
    assert client.post(f"/patients/{pid}/summaries", json={"period": "all"}).status_code == 422
    assert other_doctor.post(f"/patients/{pid}/summaries", json={"period": "all"}).status_code == 404
    assert other_doctor.get(f"/patients/{pid}/summaries/latest?period=all").status_code == 404
    assert client.get(f"/patients/{pid}/summaries/latest?period=weekly").status_code == 422


# ---------------------------------------------------------------- the checks themselves

def test_number_rounding_rules():
    from backend.summaries.facts import Facts
    facts = Facts({"a": 78.42, "b": -7.08, "d": "2024-10-15", "u": "mL/min/1.73 m²"}, {})
    ok = guard.allowed_numbers(facts)
    assert {"78.42", "78.4", "78", "7.08", "7.1", "7", "2024", "10", "15", "1.73", "1.7"} <= ok
    assert "78.5" not in ok and "78.420" not in ok and "7.2" not in ok
    assert guard.NUMBER.findall("R7–R10 HbA1c free T4 eGFR 54.1 on 2024-10-15") == ["54.1", "2024", "10", "15"]


def test_recorded_conditions_are_exempt_but_nothing_else():
    assert offending("Recorded conditions: chronic kidney disease.", ("chronic kidney disease",)) == []
    assert offending("No sign of kidney disease progression.", ("chronic kidney disease",)) == ["disease", "progression"]


def test_lab_names_pass_the_wording_check(selvam):
    c, pid = selvam
    named = variant(("sections", 1, "sentences", 0, "text"), "HbA1c was 7.1% at ASTERLANE DIAGNOSTICS.")
    fake = use_llm(FakeLLM(named))
    assert generate(c, pid).status_code == 201 and len(fake.prompts) == 1
