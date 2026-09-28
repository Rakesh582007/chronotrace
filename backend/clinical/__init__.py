"""Clinical support computed from the trend engine's output (step 9c): KDIGO risk grid, guideline criteria,
condition codes (ICD-10, SNOMED CT, LOINC) and guideline nutrition figures.

Everything here is a rule with a cited source applied to confirmed results. Nothing is a diagnosis: a
criterion says which published definition the results meet, for the doctor to confirm; codes are shown for
recorded conditions and suggested from a met criterion; nutrition figures quote a guideline for the patient's
computed category. Pure functions (no database); the API passes the trends and the patient.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONDITIONS = ROOT / "data" / "conditions.yaml"

KDIGO_SOURCE = ("KDIGO 2024 CKD guideline: GFR categories G1–G5, albuminuria categories A1–A3 and the heat map "
                "of prognosis by both")
G_CATS = [(90, "G1"), (60, "G2"), (45, "G3a"), (30, "G3b"), (15, "G4"), (float("-inf"), "G5")]
RISK = {
    "G1": ("low", "moderate", "high"), "G2": ("low", "moderate", "high"),
    "G3a": ("moderate", "high", "very high"), "G3b": ("high", "very high", "very high"),
    "G4": ("very high", "very high", "very high"), "G5": ("very high", "very high", "very high"),
}
A_INDEX = {"A1": 0, "A2": 1, "A3": 2}
MARKER_DAYS = 90                    # KDIGO: markers present for more than 3 months
UACR_PAIR_DAYS = 365                # an eGFR is paired with the latest UACR up to a year before it

MET, NOT_MET, NOT_ENOUGH = "met", "not met", "not enough data"


@lru_cache(maxsize=1)
def condition_codes() -> dict:
    return yaml.safe_load(CONDITIONS.read_text(encoding="utf-8"))


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("-", " ").split())


def code_for(condition: str) -> dict | None:
    n = _norm(condition)
    return next((c for c in condition_codes()["conditions"] if n in {_norm(x) for x in c["names"]}), None)


def recorded(conditions: list[str], names: list[str]) -> bool:
    have = {_norm(c) for c in conditions}
    return any(_norm(n) in have for n in names)


def g_category(egfr: float) -> str:
    return next(cat for lo, cat in G_CATS if egfr >= lo)


def a_category(uacr: float) -> str:
    return "A3" if uacr > 300 else "A2" if uacr >= 30 else "A1"


def risk(g: str, a: str) -> str:
    return RISK[g][A_INDEX[a]]


def _values(trends: list[dict], analyte: str) -> list[dict]:
    t = next((t for t in trends if t["analyte_id"] == analyte), None)
    return [p for p in (t["points"] if t else []) if not p["censored"]]


def _ref(p: dict) -> dict:
    return {"date": p["date"], "value": round(p["value"], 2), "report_id": p["report_id"]}


def _d(p: dict) -> dt.date:
    return p["date"] if isinstance(p["date"], dt.date) else dt.date.fromisoformat(str(p["date"]))


# ---------------------------------------------------------------- KDIGO grid

def kdigo(trends: list[dict]) -> dict:
    egfr, uacr = _values(trends, "egfr"), _values(trends, "uacr")
    history = []
    for e in egfr:
        pair = [u for u in uacr if 0 <= (_d(e) - _d(u)).days <= UACR_PAIR_DAYS]
        u = pair[-1] if pair else None
        g = g_category(e["value"])
        a = a_category(u["value"]) if u else None
        history.append({"date": e["date"], "g": g, "a": a, "risk": risk(g, a) if a else None,
                        "egfr": _ref(e), "uacr": _ref(u) if u else None})
    return {"current": history[-1] if history else None, "history": history, "source": KDIGO_SOURCE}


# ---------------------------------------------------------------- criteria

def _sustained(points: list[dict], test) -> tuple[dict, dict] | None:
    """The first and the latest result of the most recent run of results that all pass `test`, when that run
    spans more than 90 days (KDIGO: more than 3 months)."""
    run: list[dict] = []
    for p in points:
        run = run + [p] if test(p["value"]) else []
    if len(run) >= 2 and (_d(run[-1]) - _d(run[0])).days > MARKER_DAYS:
        return run[0], run[-1]
    return None


def _crit(cid, title, status, evidence, report_ids, source, conditions, names, codes, extra=None) -> dict:
    return {"id": cid, "title": title, "status": status, "evidence": evidence, "report_ids": sorted(set(report_ids)),
            "source": source, "recorded": recorded(conditions, names), "codes": codes, **(extra or {})}


def _fmt(p: dict, unit: str = "") -> str:
    return f"{p['value']:.4g}{(' ' + unit) if unit and unit != '%' else unit} on {_d(p).strftime('%d %b %Y')}"


def ckd_criterion(trends, conditions) -> dict:
    egfr, uacr = _values(trends, "egfr"), _values(trends, "uacr")
    names = ["chronic kidney disease", "ckd"]
    source = ("KDIGO 2024 CKD guideline, definition: abnormalities of kidney structure or function present for "
              "more than 3 months (eGFR < 60 mL/min/1.73 m², or albuminuria with ACR ≥ 30 mg/g)")
    low = _sustained(egfr, lambda v: v < 60)
    alb = _sustained(uacr, lambda v: v >= 30)
    parts, rids = [], []
    if low:
        parts.append(f"eGFR below 60 from {_fmt(low[0])} to {_fmt(low[1])} ({(_d(low[1]) - _d(low[0])).days} days)")
        rids += [low[0]["report_id"], low[1]["report_id"]]
    if alb:
        parts.append(f"urine ACR at or above 30 mg/g from {_fmt(alb[0], 'mg/g')} to {_fmt(alb[1], 'mg/g')} "
                     f"({(_d(alb[1]) - _d(alb[0])).days} days)")
        rids += [alb[0]["report_id"], alb[1]["report_id"]]
    codes = []
    if parts and egfr:
        g = g_category(egfr[-1]["value"])
        stage = condition_codes()["ckd_stage_codes"][g]
        base = code_for("chronic kidney disease")
        codes = [{"system": "ICD-10-CM", "code": stage["icd10_cm"], "title": stage["title"],
                  "why": f"KDIGO category {g} from the latest eGFR ({_fmt(egfr[-1])})"},
                 {"system": "SNOMED CT", "code": base["snomed"], "title": base["snomed_term"], "why": "condition"}]
    if parts:
        return _crit("ckd_kdigo", "CKD (KDIGO definition)", MET, "; ".join(parts) + ".", rids, source, conditions,
                     names, codes)
    if len(egfr) < 2 and len(uacr) < 2:
        return _crit("ckd_kdigo", "CKD (KDIGO definition)", NOT_ENOUGH,
                     "Needs two eGFR or two urine ACR results more than 3 months apart.", [], source, conditions, names, [])
    return _crit("ckd_kdigo", "CKD (KDIGO definition)", NOT_MET,
                 "No run of eGFR below 60, or urine ACR at or above 30, lasting more than 3 months.", [], source,
                 conditions, names, [])


def diabetes_criterion(trends, conditions) -> dict | None:
    a1c, fpg = _values(trends, "hba1c"), _values(trends, "fasting_glucose")
    if not a1c and not fpg:
        return None
    names = ["type 2 diabetes", "type 1 diabetes", "type 2 diabetes mellitus", "diabetes"]
    source = ("ADA Standards of Care in Diabetes 2025, section 2: HbA1c ≥ 6.5% or fasting plasma glucose "
              "≥ 126 mg/dL, confirmed on a second result; HbA1c 5.7–6.4% is the prediabetes range")
    hi_a1c = [p for p in a1c if p["value"] >= 6.5]
    hi_fpg = [p for p in fpg if p["value"] >= 126]
    base = code_for("type 2 diabetes")
    codes = [{"system": "ICD-10", "code": base["icd10"], "title": base["icd10_title"], "why": "if type 2 is confirmed"},
             {"system": "SNOMED CT", "code": base["snomed"], "title": base["snomed_term"], "why": "if type 2 is confirmed"}]
    for name, hits, unit in (("HbA1c", hi_a1c, "%"), ("Fasting glucose", hi_fpg, "mg/dL")):
        if len(hits) >= 2:
            return _crit("diabetes_ada", "Diabetes (ADA criteria)", MET,
                         f"{name} at or above the ADA cut-off on {len(hits)} results, first {_fmt(hits[0], unit)} "
                         f"and {_fmt(hits[1], unit)}. The type (1 or 2) is not in the lab data.",
                         [hits[0]["report_id"], hits[1]["report_id"]], source, conditions, names, codes)
    if a1c and 5.7 <= a1c[-1]["value"] < 6.5 and not hi_a1c:
        return _crit("diabetes_ada", "Prediabetes range (ADA)", MET,
                     f"Latest HbA1c {_fmt(a1c[-1], '%')} is in the 5.7–6.4% range.", [a1c[-1]["report_id"]], source,
                     conditions, ["prediabetes"],
                     [{"system": "ICD-10-CM", "code": "R73.03", "title": "Prediabetes", "why": "HbA1c 5.7–6.4%"}])
    return _crit("diabetes_ada", "Diabetes (ADA criteria)", NOT_MET,
                 "No two results at or above the ADA cut-offs.", [], source, conditions, names, [])


def thyroid_pattern(trends, conditions, infos) -> dict | None:
    tsh, ft4 = _values(trends, "tsh"), _values(trends, "free_t4")
    if not tsh:
        return None
    last = tsh[-1]
    same = next((p for p in reversed(ft4) if p["date"] == last["date"]), None)
    tt, ft = infos["tsh"].target, infos["free_t4"].target
    names = ["hypothyroidism", "hyperthyroidism"]
    source = ("ATA 2014 hypothyroidism guideline (Jonklaas et al., Thyroid 2014;24:1670-1751): overt primary "
              "hypothyroidism is a TSH above and free T4 below the reference range; subclinical is a raised TSH with "
              "free T4 within range. Ranges are lab-specific")
    rids = [last["report_id"]] + ([same["report_id"]] if same else [])
    hypo = code_for("hypothyroidism")
    if last["value"] > tt.high:
        if same is not None and same["value"] < ft.low:
            return _crit("thyroid_pattern", "Overt primary hypothyroidism pattern", MET,
                         f"TSH {_fmt(last, 'mIU/L')} above {tt.high:g} with free T4 {same['value']:.3g} below {ft.low:g}.", rids,
                         source, conditions, names,
                         [{"system": "ICD-10", "code": hypo["icd10"], "title": hypo["icd10_title"], "why": "pattern"},
                          {"system": "SNOMED CT", "code": hypo["snomed"], "title": hypo["snomed_term"], "why": "pattern"}])
        return _crit("thyroid_pattern", "Subclinical hypothyroidism pattern", MET,
                     f"TSH {_fmt(last, 'mIU/L')} above {tt.high:g}" + (f" with free T4 {same['value']:.3g} within range."
                                                            if same is not None else " (no free T4 on that report)."),
                     rids, source, conditions, names, [])
    if last["value"] < tt.low and same is not None and same["value"] > ft.high:
        return _crit("thyroid_pattern", "Overt hyperthyroidism pattern", MET,
                     f"TSH {_fmt(last, 'mIU/L')} below {tt.low:g} with free T4 {same['value']:.3g} above {ft.high:g}.", rids,
                     source, conditions, names, [])
    return _crit("thyroid_pattern", "Thyroid results within range", NOT_MET,
                 f"Latest TSH {_fmt(last, 'mIU/L')} is within {tt.label}.", rids, source, conditions, names, [])


def potassium_criterion(trends, conditions) -> dict | None:
    k = _values(trends, "potassium")
    if not k or k[-1]["value"] <= 5.0:
        return None
    return _crit("hyperkalaemia", "Potassium above 5.0 mmol/L", MET, f"Latest potassium {_fmt(k[-1], 'mmol/L')}.",
                 [k[-1]["report_id"]], "KDIGO 2024 CKD guideline, section 3.10 (hyperkalaemia in CKD)", conditions,
                 ["hyperkalaemia", "hyperkalemia"],
                 [{"system": "ICD-10", "code": "E87.5", "title": "Hyperkalaemia", "why": "potassium > 5.0"}])


def criteria(trends, conditions, infos) -> list[dict]:
    has_kidney = bool(_values(trends, "egfr") or _values(trends, "uacr"))
    out = [ckd_criterion(trends, conditions) if has_kidney else None, diabetes_criterion(trends, conditions),
           thyroid_pattern(trends, conditions, infos), potassium_criterion(trends, conditions)]
    return [c for c in out if c is not None]


# ---------------------------------------------------------------- codes

def codes(conditions: list[str], trends: list[dict], infos_raw: dict[str, dict]) -> dict:
    cond = []
    for c in conditions:
        m = code_for(c)
        cond.append({"text": c, "icd10": m["icd10"] if m else None, "icd10_title": m["icd10_title"] if m else None,
                     "snomed": m["snomed"] if m else None, "snomed_term": m["snomed_term"] if m else None,
                     "status": m["status"] if m else "not in the code table"})
    tests = [{"analyte_id": t["analyte_id"], "name": t["name"], "loinc": infos_raw[t["analyte_id"]]["loinc"],
              "loinc_name": infos_raw[t["analyte_id"]].get("loinc_name", "")} for t in trends]
    return {"conditions": cond, "tests": tests,
            "note": "Codes for the doctor to confirm. ICD-10 (WHO), ICD-10-CM stage codes, SNOMED CT International "
                    "Edition (free in India through NRCeS), LOINC for each test."}


# ---------------------------------------------------------------- nutrition

def nutrition(kd: dict, crit: list[dict], weight_kg: float | None, trends: list[dict]) -> list[dict]:
    """Guideline nutrition figures for the patient's computed categories (quoted, with the source)."""
    out = []
    cur = kd["current"]
    ckd_met = any(c["id"] == "ckd_kdigo" and c["status"] == MET for c in crit)
    if cur and cur["g"] in {"G3a", "G3b", "G4", "G5"}:
        grams = round(0.8 * weight_kg) if weight_kg else None
        out.append({"id": "protein_ckd", "title": "Protein", "figure": "0.8 g per kg body weight per day",
                    "per_day": grams, "unit": "g/day",
                    "applies_because": f"KDIGO category {cur['g']} from the latest eGFR (G3–G5, not on dialysis)",
                    "source": "KDIGO 2024 CKD guideline, Recommendation 3.3.1.1", "status": "unverified"})
    if ckd_met:
        out.append({"id": "sodium_ckd", "title": "Sodium", "figure": "less than 2 g of sodium per day "
                    "(less than 5 g of salt)", "per_day": 2.0, "unit": "g sodium/day (upper limit)",
                    "applies_because": "the KDIGO CKD criterion is met",
                    "source": "KDIGO 2024 CKD guideline, Recommendation 3.3.2.1", "status": "unverified"})
    k = _values(trends, "potassium")
    if ckd_met and k and k[-1]["value"] > 5.0:
        out.append({"id": "potassium_ckd", "title": "Potassium",
                    "figure": "an individualised dietary potassium plan (no fixed figure)", "per_day": None, "unit": "",
                    "applies_because": f"latest potassium {_fmt(k[-1], 'mmol/L')} with the CKD criterion met",
                    "source": "KDIGO 2024 CKD guideline, Practice Point 3.3.3.1", "status": "unverified"})
    if any(c["id"] == "diabetes_ada" and c["status"] == MET and c["title"].startswith("Diabetes") for c in crit):
        out.append({"id": "mnt_diabetes", "title": "Carbohydrate, fat and protein",
                    "figure": "no single ideal split; individualised medical nutrition therapy", "per_day": None,
                    "unit": "", "applies_because": "the ADA diabetes criteria are met",
                    "source": "ADA Standards of Care in Diabetes 2025, section 5", "status": "unverified"})
    return out


def clinical(trends: list[dict], conditions: list[str], weight_kg: float | None, infos, infos_raw) -> dict:
    kd = kdigo(trends)
    crit = criteria(trends, conditions, infos)
    return {"kdigo": kd, "criteria": crit, "codes": codes(conditions, trends, infos_raw),
            "nutrition": nutrition(kd, crit, weight_kg, trends), "weight_kg": weight_kg}
