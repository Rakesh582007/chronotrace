"""Nutrition figures for this patient (step 9d): grouped by the patient's conditions, each tied to the patient's own
results, medicines, sex and weight.

A group appears for a recorded condition or a met criterion. Each item quotes one guideline figure, says which of
the patient's values or medicines it applies to (with the reports), turns per-kg figures into amounts from the
recorded weight, and adds a note where another of the patient's conditions or medicines limits the figure (for
example the hypertension potassium figure excludes CKD). Nothing here is a meal plan: the figures are for the
doctor and dietitian to confirm. Every figure is `unverified` until checked against the cited source.
"""

from __future__ import annotations

import datetime as dt

from . import MET, _d, _fmt, _values, a_category, code_for, recorded

UNVERIFIED = "unverified"
CKD_G_LOW = {"G3a", "G3b", "G4", "G5"}
NOTE = ("Figures quoted from the cited guidelines for this patient's recorded conditions, results and medicines. "
        "Amounts use the recorded weight. For the doctor and a dietitian to confirm and adapt.")

S_KDIGO_PROTEIN = "KDIGO 2024 CKD guideline, section 3.3.1 (protein intake, Recommendation 3.3.1.1)"
S_KDIGO_PROTEIN_HIGH = "KDIGO 2024 CKD guideline, section 3.3.1 (practice point: avoid more than 1.3 g/kg/day)"
S_KDIGO_DM_PROTEIN = "KDIGO 2022 guideline for diabetes management in CKD, Recommendation 3.1.1"
S_KDIGO_SODIUM = "KDIGO 2024 CKD guideline, Recommendation 3.3.2.1"
S_KDIGO_K = "KDIGO 2024 CKD guideline, section 3.3.3 (dietary potassium)"
S_KDOQI_ENERGY = "KDOQI 2020 clinical practice guideline for nutrition in CKD (energy intake 25–35 kcal/kg/day)"
S_ADA_MNT = "ADA Standards of Care in Diabetes 2025, section 5 (medical nutrition therapy)"
S_ADA_B12 = "ADA Standards of Care in Diabetes 2025, section 9 (vitamin B12 with long-term metformin)"
S_ADA_PREDIABETES = "ADA Standards of Care in Diabetes 2025, section 3 (7% weight loss in prediabetes)"
S_ADA_LIPIDS = "ADA Standards of Care in Diabetes 2025, section 10 (lifestyle for lipids)"
S_DGA = "Dietary Guidelines for Americans 2020–2025 (saturated fat under 10% of energy)"
S_AHA_HTN = "ACC/AHA 2017 high blood pressure guideline, section 6 (nonpharmacological interventions)"
S_ATA = "ATA 2014 hypothyroidism guideline (Jonklaas et al., Thyroid 2014;24:1670-1751), levothyroxine absorption"


# ---------------------------------------------------------------- helpers

def _k(p: dict) -> str:
    """Potassium to one decimal: 5.0, not 5, next to the 5.0 mmol/L limit."""
    return f"{p['value']:.1f} mmol/L on {_d(p).strftime('%d %b %Y')}"


def _latest(trends, analyte):
    v = _values(trends, analyte)
    return v[-1] if v else None


def _span(points: list[dict], unit: str = "") -> str:
    """"from 79.3 on 12 Jun 2023" when there is an earlier result, else ""."""
    return f", from {_fmt(points[0], unit)}" if len(points) >= 2 else ""


def _active(events, class_id: str, today: dt.date | None = None):
    """The start event of a drug class still running (no later stop), or None."""
    start = None
    for e in sorted(events or [], key=lambda e: e.date):
        if e.drug_class != class_id:
            continue
        if e.change == "stop":
            start = None
        elif e.change == "start" or start is None:      # a dose change with no start on file: already on it
            start = e
    return start


def _since(e) -> str:
    return f"{e.generic or e.drug} since {e.date.strftime('%d %b %Y')}"


def _years(e, on: dt.date) -> str:
    days = (on - e.date).days
    return f"about {round(days / 365.25)} years" if days >= 548 else f"about {max(1, round(days / 30.4))} months"


def _amt(v: float | None, step: float = 1) -> float | None:
    if v is None:
        return None
    r = round(v / step) * step
    return int(r) if float(r).is_integer() else round(r, 1)


def _item(iid, title, figure, applies_because, source, amount=None, amount_high=None, unit="", report_ids=(),
          note=None, superseded_by=None) -> dict:
    return {"id": iid, "title": title, "figure": figure, "amount": amount, "amount_high": amount_high, "unit": unit,
            "applies_because": applies_because, "report_ids": sorted({r for r in report_ids if r is not None}),
            "note": note, "superseded_by": superseded_by, "source": source, "status": UNVERIFIED}


def _group(gid, label, is_recorded, basis, report_ids, items) -> dict:
    return {"id": gid, "label": label, "recorded": is_recorded, "basis": basis,
            "report_ids": sorted({r for r in report_ids if r is not None}), "items": items}


def _met(crit, cid, prefix=None) -> dict | None:
    return next((c for c in crit if c["id"] == cid and c["status"] == MET
                 and (prefix is None or c["title"].startswith(prefix))), None)


def _names(condition: str) -> list[str]:
    c = code_for(condition)
    return c["names"] if c else [condition]


# ---------------------------------------------------------------- groups

def _kidney(ctx) -> dict | None:
    crit, conditions, w = ctx["crit"], ctx["conditions"], ctx["w"]
    rec = recorded(conditions, _names("chronic kidney disease"))
    if not (rec or _met(crit, "ckd_kdigo")):
        return None
    trends, cur = ctx["trends"], ctx["kd"]["current"]
    egfr, uacr, k = _values(trends, "egfr"), _values(trends, "uacr"), _values(trends, "potassium")
    rids, basis = [], []
    if cur:
        cat = cur["g"] + (f" {cur['a']}" if cur["a"] else "")
        basis.append(f"KDIGO {cat}: eGFR {_fmt(egfr[-1])}{_span(egfr)}")
        rids += [egfr[-1]["report_id"], egfr[0]["report_id"]]
    if uacr:
        basis.append(f"urine ACR {_fmt(uacr[-1], 'mg/g')}"
                     + ("" if cur and cur["a"] else f" (category {a_category(uacr[-1]['value'])})"))
        rids.append(uacr[-1]["report_id"])
    if not cur:
        basis.append("no eGFR on file, so the G category is not known")
    basis.append("CKD recorded" if rec else "KDIGO CKD criterion met, not recorded")

    items = []
    diabetes = ctx["diabetes"]
    g = cur["g"] if cur else None
    if g in CKD_G_LOW or diabetes:
        why = (f"category {g} from eGFR {_fmt(egfr[-1])}" if g in CKD_G_LOW else "diabetes with CKD")
        why += ", not on dialysis"
        src = S_KDIGO_PROTEIN if g in CKD_G_LOW else S_KDIGO_DM_PROTEIN
        if g in CKD_G_LOW and diabetes:
            src += "; " + S_KDIGO_DM_PROTEIN
        items.append(_item("protein_ckd", "Protein", "0.8 g per kg body weight per day", why, src,
                           _amt(0.8 * w) if w else None, unit="g/day",
                           report_ids=[egfr[-1]["report_id"]] if g in CKD_G_LOW else []))
    else:
        items.append(_item("protein_ckd", "Protein", "no more than 1.3 g per kg body weight per day",
                           f"CKD with {'category ' + g if g else 'no eGFR on file'}; the 0.8 g/kg figure is for G3–G5",
                           S_KDIGO_PROTEIN_HIGH, _amt(1.3 * w) if w else None, unit="g/day (upper limit)"))
    if w:
        lo, hi = ctx["energy"]
        items.append(_item("energy_ckd", "Energy", "25–35 kcal per kg body weight per day",
                           f"CKD, recorded weight {w:g} kg; the point in the range depends on age, activity and "
                           "weight goals", S_KDOQI_ENERGY, lo, hi, "kcal/day"))
    htn = ctx["hypertension"]
    items.append(_item("sodium", "Sodium", "less than 2 g of sodium per day (less than 5 g of salt)",
                       "CKD" + (" and hypertension both recorded" if htn else ""), S_KDIGO_SODIUM, 2.0,
                       unit="g sodium/day (upper limit)",
                       note=("The ACC/AHA 2017 hypertension guideline gives an optimal figure below 1.5 g per day."
                             if htn else None)))
    if k:
        last = k[-1]
        ace = ctx["acei"]
        why = f"latest potassium {_k(last)}{', from ' + _k(k[0]) if len(k) >= 2 else ''}"
        if ace:
            why += f"; {_since(ace)}"
        if last["value"] > 5.0:
            fig = "an individualised dietary potassium plan (no fixed figure)"
        else:
            fig = "no fixed limit at this value; dietary potassium limits are tied to potassium above 5.0 mmol/L"
        note = None
        if ace and ace.klass and ace.klass.effect_on("potassium"):
            n = ace.klass.effect_on("potassium").note
            note = n[0].upper() + n[1:] + " (drug catalogue)."
        items.append(_item("potassium_ckd", "Potassium", fig, why, S_KDIGO_K, report_ids=[last["report_id"]],
                           note=note))
    return _group("kidney", "Kidney (CKD)", rec, "; ".join(basis) + ".", rids, items)


def _glucose(ctx) -> dict | None:
    crit, conditions, trends, w = ctx["crit"], ctx["conditions"], ctx["trends"], ctx["w"]
    names = _names("type 2 diabetes") + _names("type 1 diabetes") + ["diabetes"]
    rec = recorded(conditions, names)
    dm, pre = _met(crit, "diabetes_ada", "Diabetes"), _met(crit, "diabetes_ada", "Prediabetes")
    a1c = _values(trends, "hba1c")
    if pre and not rec:
        last = a1c[-1]
        return _group("glucose", "Prediabetes range", False, f"HbA1c {_fmt(last, '%')}, in the 5.7–6.4% range.",
                      [last["report_id"]], [
                          _item("weight_prediabetes", "Weight", "a 7% loss of initial body weight",
                                f"HbA1c {_fmt(last, '%')}; recorded weight {w:g} kg" if w else
                                f"HbA1c {_fmt(last, '%')}; no weight recorded",
                                S_ADA_PREDIABETES, _amt(0.07 * w, 0.5) if w else None, unit="kg (total)",
                                report_ids=[last["report_id"]])])
    if not (rec or dm):
        return None
    rids, basis = [], []
    goal = ctx["infos"]["hba1c"].target
    if a1c:
        last = a1c[-1]
        side = "above" if last["value"] > goal.high else "at or below"
        basis.append(f"HbA1c {_fmt(last, '%')}{_span(a1c, '%')}; {side} the ADA goal of {goal.label} for many adults")
        rids += [last["report_id"], a1c[0]["report_id"]]
    else:
        basis.append("no HbA1c on file")
    meds = [e for e in (ctx["metformin"], ctx["sglt2i"]) if e]
    if meds:
        basis.append("on " + ", ".join(_since(e) for e in meds))
    basis.append("diabetes recorded" if rec else "ADA diabetes criteria met, not recorded")

    a1c_why = f"HbA1c {_fmt(a1c[-1], '%')}, goal {goal.label}" if a1c else "diabetes recorded"
    a1c_rid = [a1c[-1]["report_id"]] if a1c else []
    items = [_item("mnt_diabetes", "Carbohydrate, fat and protein",
                   "no single ideal split; an individualised meal plan (medical nutrition therapy)", a1c_why, S_ADA_MNT,
                   report_ids=a1c_rid,
                   note=("The protein figure for CKD is in the kidney group." if ctx["ckd"] else None))]
    lo, hi = ctx["energy"]
    fib_note = None
    k = _latest(trends, "potassium")
    if ctx["ckd"] and k:
        fib_note = (f"With CKD, fibre-rich plant foods also carry potassium (latest {_k(k)}); "
                    "see the kidney group.")
    items.append(_item("fibre", "Fibre", "at least 14 g per 1,000 kcal, from minimally processed high-fibre foods",
                       "diabetes" + (f"; amounts use the CKD energy range {lo:g}–{hi:g} kcal/day" if lo else
                                     "; no energy figure on file, so no daily amount"),
                       S_ADA_MNT, _amt(14 * lo / 1000) if lo else None, _amt(14 * hi / 1000) if hi else None,
                       "g/day", note=fib_note))
    items.append(_item("drinks", "Drinks", "water or no-calorie drinks in place of sugar-sweetened drinks", a1c_why,
                       S_ADA_MNT, report_ids=a1c_rid))
    met = ctx["metformin"]
    if met:
        items.append(_item("b12_metformin", "Vitamin B12",
                           "long-term metformin is associated with vitamin B12 deficiency; periodic B12 measurement",
                           f"{_since(met)} ({_years(met, ctx['today'])}); no vitamin B12 result on file"
                           if not _values(trends, "vitamin_b12") else f"{_since(met)} ({_years(met, ctx['today'])})",
                           S_ADA_B12))
    return _group("glucose", "Diabetes", rec, "; ".join(basis) + ".", rids, items)


def _pressure(ctx) -> dict | None:
    if not ctx["hypertension"]:
        return None
    ckd, ace, sex = ctx["ckd"], ctx["acei"], ctx["sex"]
    k = _latest(ctx["trends"], "potassium")
    basis = "Hypertension recorded; blood pressure readings are not in the lab data"
    if ace:
        basis += f"; on {_since(ace)}"
    items = []
    if not ckd:
        items.append(_item("sodium", "Sodium", "optimal below 1.5 g of sodium per day, or at least 1 g per day less "
                           "than current intake", "hypertension recorded", S_AHA_HTN, 1.5,
                           unit="g sodium/day (optimal)"))
    items.append(_item("dash", "Eating pattern", "DASH: fruit, vegetables, whole grains and low-fat dairy, with less "
                       "saturated and total fat", "hypertension recorded", S_AHA_HTN,
                       note=("DASH is high in potassium and phosphorus; with CKD it is adapted to the latest "
                             "potassium and eGFR (see the kidney group)." if ckd else None)))
    limits = []
    if ckd:
        limits.append("CKD is recorded")
    if ace:
        limits.append(f"{ace.generic or ace.drug} reduces potassium excretion")
    if k and k["value"] > 5.0:
        limits.append(f"latest potassium is {_k(k)}")
    items.append(_item("potassium_htn", "Potassium", "3.5–5 g of potassium per day from food",
                       "hypertension recorded", S_AHA_HTN, 3.5, 5, "g/day",
                       report_ids=[k["report_id"]] if k and limits else [],
                       note=("The guideline figure excludes CKD and drugs that reduce potassium excretion: "
                             + "; ".join(limits) + "." if limits else None),
                       superseded_by="kidney" if ckd and limits else None))
    if sex in {"male", "female"}:
        n = 2 if sex == "male" else 1
        items.append(_item("alcohol", "Alcohol", f"no more than {n} standard drink{'s' if n > 1 else ''} per day "
                           f"({'men' if n == 2 else 'women'})", f"sex recorded as {sex}", S_AHA_HTN, n,
                           unit="drinks/day (upper limit)"))
    return _group("pressure", "Blood pressure (hypertension)", True, basis + ".", [], items)


def _lipids(ctx) -> dict | None:
    trends, infos = ctx["trends"], ctx["infos"]
    ldl, tg, hdl = _latest(trends, "ldl"), _latest(trends, "triglycerides"), _latest(trends, "hdl")
    rec = recorded(ctx["conditions"], _names("dyslipidaemia"))
    ldl_goal = infos["ldl"].target
    ldl_hi = ldl is not None and ldl_goal is not None and ldl["value"] > ldl_goal.high
    tg_hi = tg is not None and tg["value"] >= 150
    if not (rec or ldl_hi or tg_hi):
        return None
    parts, rids = [], []
    for name, p in (("LDL", ldl), ("triglycerides", tg), ("HDL", hdl)):
        if p:
            parts.append(f"{name} {_fmt(p, 'mg/dL')}")
            rids.append(p["report_id"])
    basis = "; ".join(parts) + ("; dyslipidaemia recorded" if rec else "")
    items = []
    lo, hi = ctx["energy"]
    if ldl_hi or rec:
        why = (f"LDL {_fmt(ldl, 'mg/dL')}, above the general goal {ldl_goal.label}" if ldl_hi else
               "dyslipidaemia recorded")
        items.append(_item("sat_fat", "Saturated fat", "less than 10% of daily energy (about 22 g at 2,000 kcal)",
                           why + (f"; amounts use the CKD energy range {lo:g}–{hi:g} kcal/day" if lo else ""),
                           S_DGA + "; " + S_ADA_LIPIDS, _amt(0.1 * lo / 9) if lo else None,
                           _amt(0.1 * hi / 9) if hi else None, "g/day (upper limit)",
                           report_ids=[ldl["report_id"]] if ldl_hi else []))
    if tg_hi:
        items.append(_item("triglycerides", "Sugar, refined carbohydrate and alcohol",
                           "less added sugar, refined carbohydrate and alcohol; more fibre and n-3 fatty acids",
                           f"triglycerides {_fmt(tg, 'mg/dL')}, at or above 150", S_ADA_LIPIDS,
                           report_ids=[tg["report_id"]]))
    return _group("lipids", "Lipids", rec, basis + ".", rids, items)


def _thyroid(ctx) -> dict | None:
    levo = ctx["levothyroxine"]
    rec = recorded(ctx["conditions"], _names("hypothyroidism"))
    if not levo:
        return None
    tsh = _values(ctx["trends"], "tsh")
    target = ctx["infos"]["tsh"].target
    basis, rids = [f"On {_since(levo)}"], []
    if tsh:
        last = tsh[-1]
        side = ("above" if last["value"] > target.high else "below" if last["value"] < target.low else "within")
        basis.append(f"TSH {_fmt(last, 'mIU/L')}, {side} {target.label}{_span(tsh, 'mIU/L')}")
        rids.append(last["report_id"])
    basis.append("hypothyroidism recorded" if rec else "hypothyroidism not recorded")
    why = f"{_since(levo)}" + (f"; latest TSH {_fmt(tsh[-1], 'mIU/L')}" if tsh else "")
    items = [
        _item("levo_timing", "Levothyroxine and meals",
              "on an empty stomach, 60 minutes before breakfast, or at bedtime 3 or more hours after the evening meal",
              why, S_ATA, report_ids=rids,
              note="Coffee, soy and high-fibre meals close to the dose interfere with absorption (ATA 2014)."
              + (" Relevant with the diabetes fibre figure." if ctx["diabetes"] else "")),
        _item("levo_supplements", "Calcium and iron",
              "calcium and iron supplements taken about 4 hours apart from levothyroxine", why, S_ATA, report_ids=rids),
    ]
    return _group("thyroid", "Thyroid (hypothyroidism)", rec, "; ".join(basis) + ".", rids, items)


# ---------------------------------------------------------------- entry point

def nutrition(kd: dict, crit: list[dict], weight_kg: float | None, trends: list[dict], conditions: list[str] = (),
              infos: dict | None = None, events=(), sex: str | None = None, today: dt.date | None = None) -> dict:
    """Guideline nutrition figures grouped by the patient's conditions, tied to their results and medicines."""
    from ..trends.dictionary import infos_by_id

    conditions = list(conditions)
    w = weight_kg
    ckd = recorded(conditions, _names("chronic kidney disease")) or bool(_met(crit, "ckd_kdigo"))
    ctx = {
        "kd": kd, "crit": crit, "w": w, "trends": trends, "conditions": conditions, "sex": sex,
        "infos": infos or infos_by_id(), "today": today or dt.date.today(), "ckd": ckd,
        "diabetes": recorded(conditions, _names("type 2 diabetes") + _names("type 1 diabetes") + ["diabetes"])
        or bool(_met(crit, "diabetes_ada", "Diabetes")),
        "hypertension": recorded(conditions, _names("hypertension")),
        "energy": (_amt(25 * w, 10), _amt(35 * w, 10)) if (w and ckd) else (None, None),
        "acei": _active(events, "acei_arb"), "metformin": _active(events, "biguanide"),
        "sglt2i": _active(events, "sglt2i"), "levothyroxine": _active(events, "thyroid_hormone"),
    }
    groups = [g for g in (_kidney(ctx), _glucose(ctx), _pressure(ctx), _lipids(ctx), _thyroid(ctx)) if g]
    return {"weight_kg": w, "groups": groups, "note": NOTE}
