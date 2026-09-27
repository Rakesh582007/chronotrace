"""Guardrail on wording: flags and medication responses describe observed change only.

CLAUDE.md: no drug effectiveness score, no dose recommendations, no diagnosis words, and no flag says
what to do. This scans every note, message, source and status the engine can show (demo patient,
random patients, the drug catalogue) for such words.
"""

import json
import re

import yaml

from backend.trends import engine as E
from backend.trends.dictionary import analyte_infos, infos_by_id
from tests.test_trends_engine import demo_patient
from tests.test_trends_property import random_patient

BANNED = re.compile(
    r"\b(effective(ness)?|efficacy|score|better|worse|improv\w*|good|poor|success\w*|"
    r"should|must|recommend\w*|advis\w*|consider|continue|stop(ped|ping)?|discontinu\w*|titrat\w*|"
    r"switch|increase the dose|reduce the dose|reason to|re-?assess\w*|re-?check\w*|repeat\w*|monitor\w*|"
    r"diagnos\w*|disease|progress\w*|uncontrolled|controlled|kidney (failure|injury|damage)|abnormal)\b", re.I)
SHOWN = {"message", "note", "source", "status", "reason", "label", "baseline_note", "drug_class_name"}


def shown_texts(obj, key=None, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            shown_texts(v, k, out)
    elif isinstance(obj, list):
        for v in obj:
            shown_texts(v, key, out)
    elif isinstance(obj, str) and key in SHOWN:
        out.add(obj)
    return out


def engine_texts():
    texts = set()
    runs = [demo_patient("R10")] + [random_patient(seed) for seed in range(50)]
    for points, events in runs:
        trends, flags = E.analyse_patient(list(analyte_infos()), points, events)
        responses = [E.response(e, infos_by_id(), points, events) for e in events]
        shown_texts(json.loads(json.dumps({"t": trends, "f": flags, "r": responses}, default=str)), out=texts)
    return texts


def catalogue_texts():
    data = yaml.safe_load(open("data/drugs.yaml", encoding="utf-8"))
    return {" ".join(c["source"].split()) for c in data["classes"]} | \
        {e["note"] for c in data["classes"] for e in c["effects"]}


# Guideline terms quoted as a citation, as the guardrail review asked; not a statement about the patient.
CITATIONS = {E.KDIGO_SOURCE}


def test_no_advice_scores_or_diagnosis_words():
    texts = (engine_texts() | catalogue_texts()) - CITATIONS
    assert len(texts) > 30
    offending = sorted((m.group(0), t) for t in texts for m in [BANNED.search(t)] if m)
    assert offending == []


def test_the_scan_catches_advice():
    assert BANNED.search("continue ACEi/ARB unless creatinine rises by more than 30%")
    assert BANNED.search("is not a reason to stop it")
    assert BANNED.search("reassess HbA1c about 3 months after a change in therapy")
    assert not BANNED.search("a creatinine rise of up to 30% is expected after starting an ACE inhibitor or ARB")
