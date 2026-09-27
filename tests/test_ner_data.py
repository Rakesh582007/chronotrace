import pytest

from transformers import AutoTokenizer

import baseline_rules
import ner_data as nd
from generator.labeler import TAGS


@pytest.fixture(scope="module")
def tok():
    return AutoTokenizer.from_pretrained(nd.BASE_MODEL)


def test_label_list_is_the_generator_tag_list():
    assert nd.LABELS == TAGS
    assert [nd.ID2LABEL[nd.LABEL2ID[t]] for t in nd.LABELS] == nd.LABELS


def test_special_tokens_are_ignored(tok):
    e = nd.encode(tok, ["Urea", "35"], ["B-TEST", "B-VALUE"])
    assert e["word_ids"][0] is None and e["word_ids"][-1] is None
    assert e["labels"][0] == nd.IGNORE and e["labels"][-1] == nd.IGNORE
    assert len(e["labels"]) == len(e["input_ids"])


def test_only_first_subtoken_of_a_word_is_labelled(tok):
    words = ["S.Creatinine", "1.11", "mg%"]
    e = nd.encode(tok, words, ["B-TEST", "B-VALUE", "B-UNIT"])
    for w, tag in enumerate(["B-TEST", "B-VALUE", "B-UNIT"]):
        positions = [i for i, x in enumerate(e["word_ids"]) if x == w]
        assert len(positions) > 1, words[w]              # each of these words splits into sub-tokens
        assert e["labels"][positions[0]] == nd.LABEL2ID[tag]
        assert all(e["labels"][i] == nd.IGNORE for i in positions[1:])


def test_inside_tags_keep_their_label(tok):
    words = ["Fasting", "Plasma", "Glucose", "88", "mg/dL", "Up", "to", "99"]
    tags = ["B-TEST", "I-TEST", "I-TEST", "B-VALUE", "B-UNIT", "B-RANGE", "I-RANGE", "I-RANGE"]
    e = nd.encode(tok, words, tags)
    first = [nd.ID2LABEL[l] for l in e["labels"] if l != nd.IGNORE]
    assert first == tags


@pytest.mark.parametrize("words, tags", [
    (["Creatinine", "0.87", "mg%", "M:", "0.7-1.3", "F:", "0.6-1.1"],
     ["B-TEST", "B-VALUE", "B-UNIT", "B-RANGE", "I-RANGE", "I-RANGE", "I-RANGE"]),
    (["eGFR", "(CKD-EPI)", "89", "mL/min/1.73m²", ">", "90"],
     ["B-TEST", "I-TEST", "B-VALUE", "B-UNIT", "B-RANGE", "I-RANGE"]),
    (["LDL", "117", "High", "mg%", "<", "100"], ["B-TEST", "B-VALUE", "B-FLAG", "B-UNIT", "B-RANGE", "I-RANGE"]),
    (["Page", "1", "of", "2"], ["O", "O", "O", "O"]),
])
def test_labels_round_trip_to_word_tags(tok, words, tags):
    e = nd.encode(tok, words, tags)
    preds = [0 if l == nd.IGNORE else l for l in e["labels"]]
    assert nd.word_tags_from_predictions(e["word_ids"], preds, len(words)) == tags


def test_truncated_words_are_predicted_o(tok):
    words = ["HB"] + ["." * 40] * 3 + ["12.8"]
    e = nd.encode(tok, words, ["B-TEST", "O", "O", "O", "B-VALUE"], max_length=16)
    assert len(e["input_ids"]) == 16
    preds = [nd.LABEL2ID["B-VALUE"]] * 16
    assert nd.word_tags_from_predictions(e["word_ids"], preds, len(words))[-1] == "O"


# ---------------------------------------------------------------- rule baseline

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
