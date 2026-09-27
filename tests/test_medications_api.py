import pytest

PATIENT = {"name": "K. Selvam", "sex": "male", "birth_year": 1968, "conditions": ["type 2 diabetes", "CKD"]}


@pytest.fixture
def pid(client):
    return client.post("/patients", json=PATIENT).json()["id"]


def add(client, pid, **body):
    return client.post(f"/patients/{pid}/medications", json={"change": "start", "dose_text": "", **body})


def test_add_resolves_the_class(client, pid):
    r = add(client, pid, drug="Ramipril", dose_text="2.5 mg OD", date="2024-03-04")
    assert r.status_code == 201
    assert r.json() == {"id": r.json()["id"], "patient_id": pid, "drug": "Ramipril", "generic": "ramipril",
                        "drug_class": "acei_arb", "drug_class_name": "ACE inhibitor / angiotensin receptor blocker",
                        "change": "start", "dose_text": "2.5 mg OD", "date": "2024-03-04"}


def test_unknown_drug_is_kept(client, pid):
    r = add(client, pid, drug="Atorvastatin", date="2024-01-01").json()
    assert (r["drug_class"], r["generic"], r["drug_class_name"]) == ("unknown", None, None)


def test_list_is_sorted_by_date_and_delete(client, pid):
    ids = [add(client, pid, drug=d, date=day).json()["id"] for d, day in
           [("Empagliflozin", "2024-05-06"), ("Metformin", "2023-10-02"), ("Ramipril", "2024-03-04")]]
    got = client.get(f"/patients/{pid}/medications").json()
    assert [m["date"] for m in got] == ["2023-10-02", "2024-03-04", "2024-05-06"]
    assert client.delete(f"/medications/{ids[0]}").status_code == 204
    assert [m["drug"] for m in client.get(f"/patients/{pid}/medications").json()] == ["Metformin", "Ramipril"]
    assert client.delete(f"/medications/{ids[0]}").status_code == 404


@pytest.mark.parametrize("body", [
    {"drug": "Ramipril", "date": "1950-01-01"},              # before birth year
    {"drug": "Ramipril", "date": "2999-01-01"},              # future
    {"drug": "Ramipril", "date": "2024-01-01", "change": "increase"},
    {"drug": "", "date": "2024-01-01"},
])
def test_invalid_events_are_rejected(client, pid, body):
    assert client.post(f"/patients/{pid}/medications", json={"change": "start", **body}).status_code == 422


def test_unknown_patient(client):
    assert add(client, 999, drug="Ramipril", date="2024-01-01").status_code == 404
    assert client.get("/patients/999/medications").status_code == 404
