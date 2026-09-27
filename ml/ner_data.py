"""Load labelled report rows and align word-level BIO tags to DistilBERT sub-tokens.

Each row in labels.jsonl is one printed line: "tokens" (words as pdfplumber reads them) and
"tags" (one BIO tag per word). Only the first sub-token of each word carries the word's label;
the other sub-tokens and the special tokens get -100 so the loss ignores them. At prediction
time each word takes the label predicted for its first sub-token.

The label list is generator.labeler.TAGS; train_ner.py saves it in the model config
(id2label / label2id), so inference reads it from the model, not from this file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # ml/, so "generator" imports

from generator.labeler import TAGS  # noqa: E402
from shared import ner_infer  # noqa: E402  (labeler puts the repo root on sys.path)

LABELS: list[str] = list(TAGS)
LABEL2ID = {t: i for i, t in enumerate(LABELS)}
ID2LABEL = dict(enumerate(LABELS))
IGNORE = -100
MAX_LENGTH = ner_infer.MAX_LENGTH
BASE_MODEL = "distilbert-base-uncased"
DEFAULT_LABELS = Path(__file__).resolve().parent / "generated" / "labels.jsonl"


def load_rows(path: Path = DEFAULT_LABELS, split: str | None = None) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    return [r for r in rows if split is None or r["split"] == split]


def align_labels(word_ids: list[int | None], word_tags: list[str]) -> list[int]:
    """Label id for the first sub-token of each word; IGNORE elsewhere."""
    labels, prev = [], None
    for w in word_ids:
        labels.append(IGNORE if w is None or w == prev else LABEL2ID[word_tags[w]])
        prev = w
    return labels


def encode(tokenizer, words: list[str], tags: list[str] | None = None, max_length: int = MAX_LENGTH) -> dict:
    enc = tokenizer(words, is_split_into_words=True, truncation=True, max_length=max_length)
    out = {"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"]}
    word_ids = enc.word_ids()
    if tags is not None:
        out["labels"] = align_labels(word_ids, tags)
    out["word_ids"] = word_ids
    return out


def word_tags_from_predictions(word_ids: list[int | None], pred_ids: list[int], n_words: int) -> list[str]:
    """Each word's tag is the prediction at its first sub-token. Words cut off by truncation get "O"."""
    return ner_infer.word_tags_from_predictions(word_ids, pred_ids, n_words, ID2LABEL)


class NerDataset:
    """Pre-encoded rows, for a torch DataLoader with DataCollatorForTokenClassification."""

    def __init__(self, tokenizer, rows: list[dict], max_length: int = MAX_LENGTH):
        self.items = []
        for r in rows:
            e = encode(tokenizer, r["tokens"], r["tags"], max_length)
            del e["word_ids"]
            self.items.append(e)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, i: int) -> dict:
        return self.items[i]


def predict(model, tokenizer, rows: list[dict], device, batch_size: int = 64,
            max_length: int = MAX_LENGTH) -> list[list[str]]:
    """Word-level BIO tags for each row (shared with the backend: shared.ner_infer)."""
    return ner_infer.predict_tags(model, tokenizer, [r["tokens"] for r in rows], device, batch_size,
                                  max_length, ID2LABEL)
