import copy

import pytest

from data import validate_drugs as vd


@pytest.fixture(scope="module")
def data():
    return vd.load()


def cls(data, cid):
    return next(c for c in data["classes"] if c["id"] == cid)


def test_catalogue_is_valid(data):
    assert vd.validate(data) == []


def test_classes_as_specified(data):
    by = {c["id"]: c for c in data["classes"]}
    assert set(by) == {"acei_arb", "sglt2i", "biguanide"}
    assert by["acei_arb"]["window_days"] == [7, 60] and by["sglt2i"]["window_days"] == [7, 90]
    assert by["biguanide"]["window_days"] == [90, 180]
    effects = {(c["id"], e["analyte"], e["direction"]) for c in data["classes"] for e in c["effects"]}
    assert effects == {("acei_arb", "creatinine", "rise"), ("acei_arb", "egfr", "fall"),
                       ("acei_arb", "potassium", "rise"), ("sglt2i", "egfr", "fall"), ("biguanide", "hba1c", "fall")}
    assert next(e for e in by["acei_arb"]["effects"] if e["analyte"] == "creatinine")["max_expected_percent"] == 30
    assert all(c["status"] == "unverified" and c["source"] for c in data["classes"])


@pytest.mark.parametrize("text, cid, generic", [
    ("Ramipril", "acei_arb", "ramipril"), ("RAMIPRIL 2.5 mg", "acei_arb", "ramipril"),
    ("Tab. Telma 40", "acei_arb", "telmisartan"), ("losartan", "acei_arb", "losartan"),
    ("Olmezest 20", "acei_arb", "olmesartan"), ("Jardiance 10 mg", "sglt2i", "empagliflozin"),
    ("dapagliflozin", "sglt2i", "dapagliflozin"), ("Metformin SR 500", "biguanide", "metformin"),
    ("glycomet", "biguanide", "metformin"), ("Atorvastatin 10", "unknown", None), ("", "unknown", None),
])
def test_resolve(data, text, cid, generic):
    assert vd.resolve(data, text) == (cid, generic)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: cls(d, "sglt2i")["generics"].append("ramipril"), "also used by"),
    (lambda d: cls(d, "biguanide")["effects"].append({"analyte": "ferritin", "direction": "fall", "note": "x"}),
     "not in analytes.yaml"),
    (lambda d: cls(d, "acei_arb")["effects"][0].update(direction="up"), "direction"),
    (lambda d: cls(d, "acei_arb").update(window_days=[60, 7]), "window_days"),
    (lambda d: cls(d, "acei_arb").update(status="maybe"), "status"),
    (lambda d: cls(d, "acei_arb")["brands"].update(Foo="aspirin"), "not one of this class's generics"),
    (lambda d: cls(d, "biguanide").update(source=""), "missing field 'source'"),
])
def test_validator_rejects(data, mutate, message):
    bad = copy.deepcopy(data)
    mutate(bad)
    assert any(message in e for e in vd.validate(bad))
