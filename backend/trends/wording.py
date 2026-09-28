"""Wording guardrail (CLAUDE.md): ChronoTrace describes observed change only. No drug effectiveness score,
no dose recommendation, no diagnosis words, and nothing that says what to do.

BANNED is checked against every text the trend engine and drug catalogue can show (tests/test_trend_wording.py)
and against every LLM summary before it is saved (backend/summaries/guard.py).
"""

from __future__ import annotations

import re

BANNED = re.compile(
    r"\b(effective(ness)?|efficacy|score|better|worse|improv\w*|good|poor|success\w*|"
    r"should|must|recommend\w*|advis\w*|consider|continue|stop(ped|ping)?|discontinu\w*|titrat\w*|"
    r"switch|increase the dose|reduce the dose|reason to|re-?assess\w*|re-?check\w*|repeat\w*|monitor\w*|"
    r"diagnos\w*|disease|progress\w*|uncontrolled|controlled|kidney (failure|injury|damage)|abnormal)\b", re.I)

# Summaries only: a lab change is shown *after* a medication event, never as caused by it.
CAUSAL = re.compile(r"\b(caus(e|ed|es|ing)|due to|thanks to|attribut\w*|led to|as a result of|lowered|worked)\b",
                    re.I)


def offending(text: str, allowed: tuple[str, ...] = (), patterns: tuple[re.Pattern, ...] = (BANNED,)) -> list[str]:
    """Banned words in `text`, after removing `allowed` phrases (e.g. the patient's recorded conditions,
    which the doctor entered, such as "chronic kidney disease")."""
    for phrase in sorted(allowed, key=len, reverse=True):
        if phrase:
            text = re.sub(re.escape(phrase), " ", text, flags=re.I)
    return [m.group(0) for p in patterns for m in p.finditer(text)]
