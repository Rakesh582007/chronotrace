"""Patient profiles and a consistent latent state for each synthetic report.

Each report belongs to one profile. For each body system ("axis") the profile gives the odds
of it being normal, abnormal or extreme; related values are then derived from one shared
state so they agree with each other:

- HbA1c drives fasting and post-prandial glucose (monotone mapping, so HbA1c < 5.7 never
  comes with fasting glucose > 200)
- creatinine drives urea; eGFR is computed later from the printed creatinine (CKD-EPI 2021)
- lipids follow Friedewald: TC = LDL + HDL + TG/5; VLDL and ratios derive from them
- free T4 moves opposite to TSH
- red-cell indices derive from Hb, MCV and MCHC (PCV = Hb x 100 / MCHC, RBC = PCV x 10 / MCV)
- the differential count (neutrophils ... basophils) is whole numbers summing to 100

These numbers only shape synthetic training data. They are not clinical rules and are not
used by the trend engine.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from . import dictionary as d

CLASSES = ("normal", "abnormal", "extreme")
N, A, X = "normal", "abnormal", "extreme"


@dataclass(frozen=True)
class Profile:
    weight: float
    panels: tuple[str, ...]                       # panels usually ordered for this condition
    axes: dict[str, tuple[float, float, float]]   # P(normal, abnormal, extreme) per axis


_BASE = {"glycaemic": (0.94, 0.05, 0.01), "renal": (0.94, 0.05, 0.01), "electrolytes": (0.94, 0.05, 0.01),
         "lipid": (0.83, 0.16, 0.01), "thyroid": (0.93, 0.06, 0.01), "cbc": (0.87, 0.12, 0.01),
         "liver": (0.92, 0.07, 0.01)}


def _axes(**over) -> dict[str, tuple[float, float, float]]:
    return {**_BASE, **over}


PROFILES: dict[str, Profile] = {
    "healthy": Profile(0.33, (), _axes()),
    "type2_diabetes": Profile(0.16, ("BIOCHEMISTRY", "LIPID PROFILE"), _axes(
        glycaemic=(0.08, 0.80, 0.12), renal=(0.75, 0.24, 0.01), lipid=(0.55, 0.42, 0.03),
        liver=(0.7, 0.28, 0.02))),
    "ckd": Profile(0.10, ("RENAL FUNCTION", "CBC"), _axes(
        renal=(0.0, 0.82, 0.18), electrolytes=(0.55, 0.38, 0.07), cbc=(0.35, 0.55, 0.10),
        lipid=(0.6, 0.38, 0.02))),
    "diabetes_ckd": Profile(0.14, ("BIOCHEMISTRY", "RENAL FUNCTION", "CBC"), _axes(
        glycaemic=(0.08, 0.80, 0.12), renal=(0.0, 0.82, 0.18), electrolytes=(0.55, 0.38, 0.07),
        cbc=(0.4, 0.52, 0.08), lipid=(0.45, 0.5, 0.05))),
    "dyslipidaemia": Profile(0.13, ("LIPID PROFILE", "LFT"), _axes(
        lipid=(0.0, 0.85, 0.15), liver=(0.6, 0.37, 0.03), glycaemic=(0.75, 0.25, 0))),
    "hypothyroid": Profile(0.14, ("THYROID PROFILE", "LIPID PROFILE"), _axes(
        thyroid=(0.0, 0.85, 0.15), lipid=(0.6, 0.39, 0.01))),
}

# Beyond these (canonical units) a value counts as "extreme": far outside the reference
# range but still physiologically possible.
EXTREME: dict[str, tuple[float | None, float | None]] = {
    "hba1c": (None, 11.0), "fasting_glucose": (50, 300), "pp_glucose": (None, 400),
    "creatinine": (None, 5.0), "urea": (None, 150), "egfr": (15, None), "uacr": (None, 2000),
    "sodium": (125, 155), "potassium": (2.8, 6.2), "tsh": (0.02, 35), "free_t4": (0.4, 3.5),
    "total_cholesterol": (None, 300), "ldl": (None, 220), "hdl": (25, None),
    "triglycerides": (None, 600), "alt": (None, 250), "ast": (None, 250),
    "haemoglobin": (7.0, 19.0), "platelets": (50, 700), "wbc": (2.0, 25.0),
}


def value_class(analyte: dict, canonical: float, sex: str) -> str:
    lo_x, hi_x = EXTREME[analyte["id"]]
    if (lo_x is not None and canonical < lo_x) or (hi_x is not None and canonical > hi_x):
        return X
    lo, hi = d.reference_range(analyte, sex)
    if (lo is not None and canonical < lo) or (hi is not None and canonical > hi):
        return A
    return N


def choose_profile(rng: random.Random) -> str:
    names = list(PROFILES)
    return rng.choices(names, weights=[PROFILES[n].weight for n in names])[0]


def choose_panels(rng: random.Random, profile: str) -> list[str]:
    """Condition panels usually, other panels sometimes; 1-4 panels in all."""
    primary = [p for p in PROFILES[profile].panels if rng.random() < 0.8]
    others = [p for p in d.PANELS if p not in primary and rng.random() < 0.33]
    rng.shuffle(others)
    panels = (primary + others)[:4]
    return panels or [rng.choice(list(d.PANELS))]


# ---------------------------------------------------------------- helpers

def _u(rng, lo, hi, log=False):
    if log:
        return math.exp(rng.uniform(math.log(lo), math.log(hi)))
    return rng.uniform(lo, hi)


def _interp(x, xs, ys):
    for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        if x <= x1:
            return y0 + (y1 - y0) * (max(x, x0) - x0) / (x1 - x0)
    return ys[-1]


def _range(aid, sex):
    return d.reference_range(d.analytes()[aid], sex)


# ---------------------------------------------------------------- axes

_A1C = [4.4, 5.6, 6.4, 8.0, 10.0, 12.0, 14.5]
_FPG = [78, 97, 120, 165, 230, 300, 380]


def glycaemic(rng, cls) -> dict:
    a1c = {N: _u(rng, 4.4, 5.6), A: _u(rng, 5.8, 10.5), X: _u(rng, 11.2, 14.5)}[cls]
    fpg = _interp(a1c, _A1C, _FPG) * _u(rng, 0.93, 1.07)
    pp = fpg * (_u(rng, 1.08, 1.35) if a1c < 5.7 else _u(rng, 1.2, 1.5))
    return {"hba1c": a1c, "fasting_glucose": fpg, "pp_glucose": pp}


def renal(rng, cls, sex, diabetic: bool) -> dict:
    lo, hi = _range("creatinine", sex)
    creat = {N: _u(rng, lo + 0.03, hi - 0.03), A: _u(rng, hi * 1.06, 4.6, log=True),
             X: _u(rng, 5.3, 11.0, log=True)}[cls]
    urea = max(12.0, creat * _u(rng, 20, 36))
    if cls == N:
        uacr = _u(rng, 30, 180, log=True) if diabetic and rng.random() < 0.2 else _u(rng, 4, 27, log=True)
    elif cls == A:
        uacr = _u(rng, 35, 1600, log=True)
    else:
        uacr = _u(rng, 2200, 4500, log=True)
    ulo, uhi = (3.5, 7.2) if sex == "male" else (2.6, 6.0)
    uric = _u(rng, ulo + 0.2, uhi - 0.2) if cls == N else _u(rng, uhi + 0.3, 11.0)
    calcium = _u(rng, 8.8, 10.0) if cls == N else _u(rng, 7.4, 8.5)
    return {"creatinine": creat, "urea": urea, "uacr": uacr, "uric_acid": uric, "calcium": calcium}


def electrolytes(rng, cls, renal_disease: bool) -> dict:
    na, k = _u(rng, 137, 144), _u(rng, 3.7, 4.9)
    if cls == A:
        if rng.random() < 0.5:
            na = _u(rng, 126, 134) if rng.random() < 0.75 else _u(rng, 146, 152)
        else:
            k = _u(rng, 5.25, 6.0) if rng.random() < (0.8 if renal_disease else 0.4) else _u(rng, 2.9, 3.4)
    elif cls == X:
        if rng.random() < 0.5:
            na = _u(rng, 116, 124)
        else:
            k = _u(rng, 6.3, 7.1) if rng.random() < 0.7 else _u(rng, 2.3, 2.7)
    return {"sodium": na, "potassium": k, "chloride": _u(rng, 99, 106) if cls == N else _u(rng, 94, 110)}


def lipid(rng, cls, sex) -> dict:
    hdl_lo = _range("hdl", sex)[0]
    if cls == N:
        hdl, tg, ldl = _u(rng, hdl_lo + 2, 70), _u(rng, 60, 145), _u(rng, 55, 97)
    elif cls == A:
        hdl = _u(rng, 28, hdl_lo - 1) if rng.random() < 0.6 else _u(rng, hdl_lo + 1, 55)
        tg = _u(rng, 155, 390) if rng.random() < 0.7 else _u(rng, 80, 145)
        ldl = _u(rng, 102, 190)
    elif rng.random() < 0.5:   # severe hypertriglyceridaemia
        hdl, tg, ldl = _u(rng, 18, 30), _u(rng, 650, 1800, log=True), _u(rng, 80, 160)
    else:                       # familial hypercholesterolaemia
        hdl, tg, ldl = _u(rng, 30, 50), _u(rng, 100, 240), _u(rng, 230, 320)
    tc = ldl + hdl + tg / 5
    return {"hdl": hdl, "triglycerides": tg, "ldl": ldl, "total_cholesterol": tc,
            "vldl": tg / 5, "non_hdl": tc - hdl, "tc_hdl_ratio": tc / hdl, "ldl_hdl_ratio": ldl / hdl}


def thyroid(rng, cls, hypothyroid: bool) -> dict:
    if cls == N:
        return {"tsh": _u(rng, 0.6, 3.8, log=True), "free_t4": _u(rng, 0.9, 1.6)}
    if cls == A:
        r = rng.random()
        if r < 0.45:
            return {"tsh": _u(rng, 10.5, 30, log=True), "free_t4": _u(rng, 0.45, 0.78)}
        if r < 0.85 or hypothyroid:
            return {"tsh": _u(rng, 4.5, 10, log=True), "free_t4": _u(rng, 0.85, 1.4)}
        return {"tsh": _u(rng, 0.03, 0.3, log=True), "free_t4": _u(rng, 1.9, 3.2)}
    if hypothyroid or rng.random() < 0.7:
        return {"tsh": _u(rng, 40, 120, log=True), "free_t4": _u(rng, 0.2, 0.38)}
    return {"tsh": _u(rng, 0.005, 0.015, log=True), "free_t4": _u(rng, 3.6, 6.0)}


def cbc(rng, cls, sex) -> dict:
    hb_lo, hb_hi = _range("haemoglobin", sex)
    parts = {"hb": N, "wbc": N, "plt": N}
    if cls != N:
        hit = rng.choices(list(parts), weights=[0.6, 0.2, 0.2])[0]
        parts[hit] = cls
        if cls == X and rng.random() < 0.3:
            parts[rng.choice([p for p in parts if p != hit])] = A

    mcv, mchc = _u(rng, 83, 97), _u(rng, 32.2, 34.3)
    if parts["hb"] == N:
        hb = _u(rng, hb_lo + 0.3, hb_hi - 0.3)
    elif parts["hb"] == A:
        hb = _u(rng, 8.0, hb_lo - 0.2) if rng.random() < 0.9 else _u(rng, hb_hi + 0.3, 18.5)
        if hb < hb_lo and rng.random() < 0.6:   # iron deficiency: small, pale cells
            mcv, mchc = _u(rng, 66, 80), _u(rng, 29.5, 31.4)
    else:
        hb = _u(rng, 4.8, 6.8)
        mcv, mchc = _u(rng, 60, 76), _u(rng, 28.5, 31.0)
    pcv = hb * 100 / mchc
    rbc = pcv * 10 / mcv
    mch = hb * 10 / rbc

    wbc = {N: _u(rng, 4.3, 9.6),
           A: _u(rng, 10.5, 18) if rng.random() < 0.65 else _u(rng, 2.6, 3.8),
           X: _u(rng, 26, 45) if rng.random() < 0.5 else _u(rng, 1.0, 1.9)}[parts["wbc"]]
    if wbc > 10:
        neut, lymph = _u(rng, 76, 88), _u(rng, 8, 18)
    else:
        neut, lymph = _u(rng, 45, 70), _u(rng, 22, 40)
    eos, mono = _u(rng, 1, 5), _u(rng, 2, 8)
    baso = _u(rng, 0.1, 1.9)
    scale = (100 - baso) / (neut + lymph + eos + mono)
    # Printed with 0 decimals: round, then give the rounding remainder to the largest (neutrophils)
    lymph, eos, mono, baso = (round(x) for x in (lymph * scale, eos * scale, mono * scale, baso))
    neut = 100 - lymph - eos - mono - baso

    plt = {N: _u(rng, 165, 395),
           A: _u(rng, 80, 145) if rng.random() < 0.6 else _u(rng, 420, 600),
           X: _u(rng, 15, 45) if rng.random() < 0.6 else _u(rng, 760, 1000)}[parts["plt"]]
    return {"haemoglobin": hb, "wbc": wbc, "platelets": plt, "rbc": rbc, "pcv": pcv, "mcv": mcv,
            "mch": mch, "mchc": mchc, "neutrophils": neut, "lymphocytes": lymph,
            "eosinophils": eos, "monocytes": mono, "basophils": baso}


def liver(rng, cls, sex) -> dict:
    alt_hi = _range("alt", sex)[1]
    ast_hi = _range("ast", sex)[1]
    tbil, alp = _u(rng, 0.3, 1.0), _u(rng, 55, 115)
    if cls == N:
        alt, ast = _u(rng, 9, alt_hi - 3), _u(rng, 12, ast_hi - 3)
    elif cls == A:
        alt = _u(rng, alt_hi * 1.1, 180, log=True)
        ast = max(ast_hi * 1.05, alt * _u(rng, 0.55, 0.9))
        if rng.random() < 0.35:
            tbil = _u(rng, 1.3, 3.2)
        if rng.random() < 0.3:
            alp = _u(rng, 150, 320)
    else:   # acute hepatitis pattern
        alt = _u(rng, 320, 1400, log=True)
        ast = alt * _u(rng, 0.6, 1.1)
        tbil = _u(rng, 3.5, 12)
    dbil = tbil * _u(rng, 0.15, 0.3) if tbil <= 1.2 else tbil * _u(rng, 0.4, 0.7)
    tp = _u(rng, 6.5, 8.0)
    alb = _u(rng, 3.7, 4.8) if cls == N else _u(rng, 3.0, 4.3)
    alb = min(alb, tp - 2.0)
    return {"alt": alt, "ast": ast, "total_bilirubin": tbil, "direct_bilirubin": dbil, "alp": alp,
            "total_protein": tp, "albumin": alb, "globulin": tp - alb, "ag_ratio": alb / (tp - alb)}


def patient_state(rng: random.Random, profile: str, sex: str) -> dict:
    """Canonical values for every dictionary analyte (except eGFR) and every extra test."""
    prof = PROFILES[profile]

    def cls(axis):
        return rng.choices(CLASSES, weights=prof.axes[axis])[0]

    diabetic = profile in ("type2_diabetes", "diabetes_ckd")
    renal_disease = profile in ("ckd", "diabetes_ckd")
    state = {}
    state.update(glycaemic(rng, cls("glycaemic")))
    state.update(renal(rng, cls("renal"), sex, diabetic))
    state.update(electrolytes(rng, cls("electrolytes"), renal_disease))
    state.update(lipid(rng, cls("lipid"), sex))
    state.update(thyroid(rng, cls("thyroid"), profile == "hypothyroid"))
    state.update(cbc(rng, cls("cbc"), sex))
    state.update(liver(rng, cls("liver"), sex))
    return state
