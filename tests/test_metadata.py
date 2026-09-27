import datetime as dt

import pytest

from backend.extraction.metadata import find_lab, parse_date, read_metadata


@pytest.mark.parametrize("text, expected", [
    ("15/01/2024", dt.date(2024, 1, 15)),            # day first (Indian reports)
    ("15/01/202407:55", dt.date(2024, 1, 15)),       # date and time run together
    ("18.07.2025 10:16", dt.date(2025, 7, 18)),
    ("07-Jul-2025 11:38 AM", dt.date(2025, 7, 7)),
    ("7 Jul 2025", dt.date(2025, 7, 7)),
    ("12/25/2024", dt.date(2024, 12, 25)),          # month first when the second field > 12
    ("2024-01-15", dt.date(2024, 1, 15)),
    ("15/01/24", dt.date(2024, 1, 15)),
    ("31/02/2024", None),                           # not a date
    ("Kestrel Nagar", None),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_collected_is_preferred_over_reported():
    lines = ["Age / Sex :52 Y / Male Reported Date and Time :16/01/2024 14:05",
             "Registered Date and Time: 15/01/202407:55",
             "Ref By. :Dr. X Collected Date and Time :15/01/2024 08:40",
             "Collected At Somewhere,"]
    m = read_metadata([], lines)
    assert (m.date, m.date_label, m.collected_at, m.reported_at) == (
        dt.date(2024, 1, 15), "Collected", dt.date(2024, 1, 15), dt.date(2024, 1, 16))


def test_reported_is_the_fallback_and_missing_date_is_none():
    m = read_metadata([], ["Reported On : 16/01/2024 11:20", "Final Test Report Page 1 of 1"])
    assert (m.date, m.date_label) == (dt.date(2024, 1, 16), "Reported")
    m = read_metadata([], ["Final Test Report Page 1 of 1", "Registered : 15/01/2024"])
    assert (m.date, m.date_label) == (None, None)


@pytest.mark.parametrize("lines, lab", [
    (["Utkira Labs", "Complete Laboratory Services"], "Utkira Labs"),
    (["Varnika Clinical Labs Pvt. Ltd."], "Varnika Clinical Labs Pvt. Ltd."),
    (["Vedhya Diagnostic Centre"], "Vedhya Diagnostic Centre"),
    (["Tel No :12345 Sample :EXAMPLE HEALTHCARE LTD"], "EXAMPLE HEALTHCARE LTD"),
    (["LAB INVESTIGATION REPORT", "Lab Director"], None),
    (["Ref By. :Dr. Some Pathology Name"], None),
])
def test_find_lab(lines, lab):
    assert find_lab(lines) == lab


# ---------------------------------------------------------------- review findings (regressions)

@pytest.mark.parametrize("text, expected", [
    ("15/01/2408:40", dt.date(2024, 1, 15)),        # 2-digit year glued to the time, not the year 2408
    ("15-Jan-2408:40", dt.date(2024, 1, 15)),
    ("15/01/202408:40", dt.date(2024, 1, 15)),
    ("31/12/2999", None),                           # future: not a report date
    ("01/01/1901", None),
])
def test_glued_times_and_implausible_dates(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("lines", [
    ["Sample Collected At : 15/01/2024 08:40", "Reported On : 16/01/2024"],
    ["Collected/Received : 15/01/2024 08:40 / 15/01/2024 10:02", "Reported : 16/01/2024 14:05"],
    ["Coll. Date : 15/01/2024", "Report Date : 16/01/2024"],
])
def test_collected_label_variants(lines):
    m = read_metadata([], lines)
    assert (m.date, m.date_label) == (dt.date(2024, 1, 15), "Collected")


def test_collected_at_a_place_is_not_a_date():
    m = read_metadata([], ["Collected At Kestrel Nagar,", "Reported : 16/01/2024"])
    assert (m.date, m.date_label) == (dt.date(2024, 1, 16), "Reported")


@pytest.mark.parametrize("lines, lab", [
    (["Mrs Example Name Lab No. : 7788", "Tel No :123 Sample :EXAMPLE HEALTHCARE LTD"], "EXAMPLE HEALTHCARE LTD"),
    (["Age / Sex : 52 Y Lab No : 12345"], None),
    (["Ref By :DR.KUMAR CLINIC Reported :16/01/2024", "Tel No :123 Sample :EXAMPLE HEALTHCARE LTD"],
     "EXAMPLE HEALTHCARE LTD"),
])
def test_lab_name_is_not_a_field_label_patient_or_doctor(lines, lab):
    assert find_lab(lines) == lab


def test_lab_name_falls_back_to_the_top_lines():
    assert read_metadata(["Partial reproduction of this report is not permitted."],
                         ["Kestrelline Pathology Centre", "Test Result"]).lab == "Kestrelline Pathology Centre"
