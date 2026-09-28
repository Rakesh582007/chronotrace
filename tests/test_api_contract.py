"""docs/api.md must match the running API: same keys and value types for every documented example.

Each example block in the doc is preceded by `<!-- example: NAME request -->` or
`<!-- example: NAME response STATUS -->`. This test runs the documented scenario (tests/api_scenario.py)
against the API with the rule-based stand-in tagger and compares shapes, so the doc cannot drift from
the code. `python tests/api_scenario.py` refreshes the examples from a run with the real model.
"""

import typing

import pytest
from pydantic import BaseModel

from backend.main import app
from tests.api_scenario import DOC, documented, run_scenario
from tests.conftest import DOCTOR_A


def documented_examples() -> dict[str, dict]:
    return documented(DOC.read_text(encoding="utf-8"))


def kind_of(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    return {str: "string", list: "list", dict: "object"}[type(v)]


def nullable_fields() -> set[str]:
    """Names of response fields declared optional (`X | None`) in backend/schemas.py."""
    from backend import schemas
    out = set()
    for model in vars(schemas).values():
        if isinstance(model, type) and issubclass(model, BaseModel) and model is not BaseModel:
            for name, field in model.model_fields.items():
                if type(None) in typing.get_args(field.annotation):
                    out.add(name)
    return out


NULLABLE = nullable_fields()


def shape_errors(doc, actual, path="$", key=None) -> list[str]:
    """Differences in keys and value types between a documented and an actual JSON value.

    null is allowed only where the response schema declares the field optional; there it matches any
    documented type (nullable fields are null in some examples and set in others). Every other value
    must have the documented type, and every object exactly the documented keys.
    Lists: every actual element must match at least one documented element, so a doc list shows each
    variant (e.g. a tracked and a not-tracked observation).
    """
    if doc is None or actual is None:
        if (doc is None and actual is None) or key in NULLABLE:
            return []
        return [f"{path}: documented {kind_of(doc)}, API returns {kind_of(actual)} (field is not nullable)"]
    if kind_of(doc) != kind_of(actual):
        return [f"{path}: documented {kind_of(doc)}, API returns {kind_of(actual)}"]
    if isinstance(doc, dict):
        errs = [f"{path}: key '{k}' documented but not returned" for k in doc.keys() - actual.keys()]
        errs += [f"{path}: key '{k}' returned but not documented" for k in actual.keys() - doc.keys()]
        for k in doc.keys() & actual.keys():
            errs += shape_errors(doc[k], actual[k], f"{path}.{k}", k)
        return errs
    if isinstance(doc, list):
        if not doc:
            return [] if not actual else [f"{path}: documented as an empty list; add an example element"]
        errs = []
        for i, item in enumerate(actual):
            tries = [shape_errors(d, item, f"{path}[{i}]") for d in doc]
            if all(tries):
                errs += min(tries, key=len)
        return errs
    return []


@pytest.fixture(scope="module")
def docs():
    return documented_examples()


@pytest.fixture
def actual(client):
    return run_scenario(client, DOCTOR_A)


def test_every_documented_example_is_exercised(docs, actual):
    assert set(docs) == set(actual)


def test_documented_status_codes(docs, actual):
    assert {n: d["status"] for n, d in docs.items()} == {n: a["status"] for n, a in actual.items()}


def test_documented_responses_match_the_api(docs, actual):
    errors = {n: shape_errors(docs[n]["response"], actual[n]["response"]) for n in docs}
    assert {n: e for n, e in errors.items() if e} == {}


def test_documented_requests_match_what_the_api_accepts(docs, actual):
    errors = {n: shape_errors(docs[n]["request"], actual[n]["request"]) for n in docs if "request" in docs[n]}
    assert {n: e for n, e in errors.items() if e} == {}


def test_every_route_is_documented():
    """Every route in the OpenAPI schema (included routers too) has a `METHOD path` heading in the doc."""
    text = DOC.read_text(encoding="utf-8")
    routes = [(m.upper(), path) for path, methods in app.openapi()["paths"].items() for m in methods]
    missing = [f"{m} {p}" for m, p in routes if f"`{m} {p}`" not in text]
    assert missing == []


def test_shape_checker_catches_drift():
    doc = {"a": 1, "b": [{"x": None}, {"x": "s"}], "c": {"d": "t"}}
    assert shape_errors(doc, {"a": 2.5, "b": [{"x": "q"}, {"x": None}], "c": {"d": "u"}}) == []
    assert shape_errors(doc, {"a": "1", "b": [], "c": {"d": "u"}}) == ["$.a: documented number, API returns string"]
    typed = {"a": 1, "b": [{"x": "s"}], "c": {"d": "t"}}
    assert sorted(shape_errors(typed, {"a": 1, "b": [{"x": 3}], "c": {"d": "u", "e": 1}})) == [
        "$.b[0].x: documented string, API returns number", "$.c: key 'e' returned but not documented"]
    assert shape_errors(typed, {"a": 1, "b": [{}], "c": {"d": "u"}}) == ["$.b[0]: key 'x' documented but not returned"]
    assert shape_errors({"l": []}, {"l": [1]}) == ["$.l: documented as an empty list; add an example element"]


def test_null_is_only_accepted_for_nullable_fields():
    assert "comparator" in NULLABLE and "collected_at" in NULLABLE and "date" not in NULLABLE
    assert shape_errors({"comparator": "<"}, {"comparator": None}) == []
    assert shape_errors({"id": 1, "date": "2024-01-08"}, {"id": None, "date": None}) != []
