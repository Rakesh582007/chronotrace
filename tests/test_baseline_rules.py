import pytest

import baseline_rules


@pytest.mark.parametrize("words, tags", [
    (["S.Creatinine", "1.11", "mg%", "0.7", "-", "1.3"], ["B-TEST", "B-VALUE", "B-UNIT", "B-RANGE", "I-RANGE", "I-RANGE"]),
    (["Albumin,", "Serum", "3.5", "-", "5.2", "3.9", "g/dL"],
     ["B-TEST", "I-TEST", "B-RANGE", "I-RANGE", "I-RANGE", "B-VALUE", "B-UNIT"]),
    (["LDL", "117", "High", "mg%", "<", "100"], ["B-TEST", "B-VALUE", "B-FLAG", "B-UNIT", "B-RANGE", "I-RANGE"]),
    (["eGFR", "CKD-EPI", "2021", "22", "mL/min/1.73m²", ">", "90"],
     ["B-TEST", "O", "O", "B-VALUE", "B-UNIT", "B-RANGE", "I-RANGE"]),
    (["HbA1c", "5.2", "%", "of", "total", "Hb", "4.0-5.6"], ["B-TEST", "B-VALUE", "B-UNIT", "I-UNIT", "I-UNIT", "I-UNIT", "B-RANGE"]),
    (["Platelet", "Count", "2,45,000", "/cumm", "1,50,000", "-", "4,10,000"],
     ["B-TEST", "I-TEST", "B-VALUE", "B-UNIT", "B-RANGE", "I-RANGE", "I-RANGE"]),
    (["LDL", "calculated", "by", "Friedewald", "equation", "below", "400", "mg/dL."], ["O"] * 8),
    (["Page", "1", "of", "2"], ["O"] * 4),
])
def test_baseline_rules(words, tags):
    assert baseline_rules.tag_row(words) == tags
