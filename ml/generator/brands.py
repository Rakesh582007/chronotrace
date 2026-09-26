"""Real Indian lab and hospital brand names that must never appear in synthetic reports.

Used by ml/check_dataset.py and the tests. Ambiguous words that are also common Indian
names (for example "Lal", "Anand", "Max") are only matched as part of the brand phrase.
"""

from __future__ import annotations

import re

REAL_LAB_BRANDS = [
    "Lal PathLabs", "Lal Path Labs", "SRL", "Metropolis", "Thyrocare", "Apollo", "Suburban Diagnostics",
    "Vijaya Diagnostic", "Neuberg", "Healthians", "Redcliffe", "Tata 1mg", "Orange Health",
    "Pathkind", "Max Lab", "Max Healthcare", "Agilus", "Lucid Diagnostics", "Medall",
    "Aarthi Scans", "Tenet Diagnostics", "Anand Diagnostic", "Quest Diagnostics", "Oncquest",
    "Core Diagnostics", "Krsnaa", "Unipath", "Sterling Accuris", "Ganesh Diagnostic",
    "Mahajan Imaging", "Lifecell", "Hitech Diagnostic", "Dangs Lab", "Fortis", "Medanta",
    "Manipal Hospitals", "Narayana Health", "Aster Labs", "Pathcare Labs", "Kauvery",
]

_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(b).replace(r"\ ", r"\s*") for b in REAL_LAB_BRANDS) + r")\b",
    re.IGNORECASE,
)


def find_brands(text: str) -> list[str]:
    """Return every real-brand match in `text` (empty list when clean)."""
    return [m.group(0) for m in _PATTERN.finditer(text)]
