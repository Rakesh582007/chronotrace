"""Validate data/drugs.yaml and resolve drug names to classes.

Usage:  python data/validate_drugs.py [path/to/drugs.yaml]
Exit code 0 when the catalogue is valid, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import validate_analytes as va  # noqa: E402
else:
    from . import validate_analytes as va

DEFAULT_PATH = Path(__file__).with_name("drugs.yaml")
DIRECTIONS = {"rise", "fall"}
STATUSES = {"verified", "unverified"}
UNKNOWN = "unknown"
# Words that are not part of a drug name on a prescription: form, strength, frequency.
_NOISE = re.compile(r"^(?:tab|tabs|tablet|cap|caps|capsule|inj|injection|syp|syrup|sr|xr|er|od|bd|tds|"
                    r"\d[\d.]*(?:mg|mcg|g|ml)?|mg|mcg)$")


def load(path: Path = DEFAULT_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name)).strip().lower()


def name_index(data: dict) -> dict[str, tuple[str, str]]:
    """Normalised drug name (generic or brand) -> (class id, generic name)."""
    out: dict[str, tuple[str, str]] = {}
    for c in data["classes"]:
        for g in c["generics"]:
            out[norm_name(g)] = (c["id"], g)
        for brand, g in (c.get("brands") or {}).items():
            out[norm_name(brand)] = (c["id"], g)
    return out


def resolve(data: dict, text: str) -> tuple[str, str | None]:
    """(class id, generic) for a prescribed drug text such as "Tab. Telma 40 mg"; ("unknown", None) otherwise.

    The whole text is tried first, then its first word after dropping form/strength words, so a
    combination brand ("Glycomet GP 1") resolves by its first word only.
    """
    index = name_index(data)
    t = norm_name(text)
    if t in index:
        return index[t]
    words = [w for w in re.split(r"[\s.,/+()-]+", t) if w and not _NOISE.match(w)]
    if words and words[0] in index:
        return index[words[0]]
    return UNKNOWN, None


def validate(data: dict, analytes: dict | None = None) -> list[str]:
    errors: list[str] = []
    classes = (data or {}).get("classes")
    if not isinstance(classes, list) or not classes:
        return ["top-level 'classes' list is missing"]
    analytes = analytes if analytes is not None else va.load()
    analyte_ids = {a["id"] for a in analytes["analytes"]}
    ids: set[str] = set()
    names: dict[str, str] = {}
    for c in classes:
        cid = c.get("id", "<missing id>")
        where = f"[{cid}]"
        for field in ("id", "name", "generics", "window_days", "effects", "source", "status"):
            if c.get(field) in (None, "", []):
                errors.append(f"{where} missing field '{field}'")
        if cid == UNKNOWN:
            errors.append(f"{where} '{UNKNOWN}' is reserved for drugs not in the catalogue")
        if cid in ids:
            errors.append(f"{where} duplicate id")
        ids.add(cid)
        if c.get("status") not in STATUSES:
            errors.append(f"{where} status must be one of {sorted(STATUSES)}")
        w = c.get("window_days")
        if not (isinstance(w, list) and len(w) == 2 and all(isinstance(x, int) for x in w) and 0 <= w[0] < w[1]):
            errors.append(f"{where} window_days must be [start, end] with 0 <= start < end (days)")
        generics = [norm_name(g) for g in c.get("generics") or []]
        for brand, g in (c.get("brands") or {}).items():
            if norm_name(g) not in generics:
                errors.append(f"{where} brand '{brand}' maps to '{g}', which is not one of this class's generics")
        for n in generics + [norm_name(b) for b in c.get("brands") or {}]:
            if n in names and names[n] != cid:
                errors.append(f"{where} drug name '{n}' also used by [{names[n]}]")
            names[n] = cid
        seen = set()
        for e in c.get("effects") or []:
            a, d = e.get("analyte"), e.get("direction")
            if a not in analyte_ids:
                errors.append(f"{where} effect analyte '{a}' is not in analytes.yaml")
            if d not in DIRECTIONS:
                errors.append(f"{where} effect direction '{d}' not in {sorted(DIRECTIONS)}")
            if (a, d) in seen:
                errors.append(f"{where} effect {a}/{d} listed twice")
            seen.add((a, d))
            if not e.get("note"):
                errors.append(f"{where} effect {a} needs a note")
            mx = e.get("max_expected_percent")
            if mx is not None and not (isinstance(mx, (int, float)) and mx > 0):
                errors.append(f"{where} effect {a} max_expected_percent must be a positive number")
    return errors


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PATH
    data = load(path)
    errors = validate(data)
    if errors:
        print(f"FAIL {path}: {len(errors)} error(s)")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK {path}: {len(data['classes'])} drug classes")
    for c in data["classes"]:
        effects = ", ".join(f"{e['analyte']} {e['direction']}" for e in c["effects"])
        print(f"  {c['id']:<10} days {c['window_days'][0]}-{c['window_days'][1]:<4} {effects}  "
              f"({len(c['generics'])} generics, {len(c.get('brands') or {})} brands, {c['status']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
