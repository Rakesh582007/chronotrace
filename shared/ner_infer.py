"""Word-level BIO tags from a token-classification model.

Only the first sub-token of each word carries the word's label (ml/ner_data.py aligns training
labels the same way), so each word takes the prediction at its first sub-token. Words cut off
by truncation get "O". Used by training evaluation (ml/) and by the backend.
"""

from __future__ import annotations

MAX_LENGTH = 64


def word_tags_from_predictions(word_ids: list[int | None], pred_ids: list[int], n_words: int,
                               id2label: dict[int, str]) -> list[str]:
    tags = ["O"] * n_words
    prev = None
    for w, p in zip(word_ids, pred_ids):
        if w is not None and w != prev:
            tags[w] = id2label[int(p)]
        prev = w
    return tags


def predict_tags(model, tokenizer, rows: list[list[str]], device, batch_size: int = 64,
                 max_length: int = MAX_LENGTH, id2label: dict[int, str] | None = None) -> list[list[str]]:
    """Tag each row (a list of words). Labels come from the model config unless given."""
    import torch

    id2label = id2label or {int(k): v for k, v in model.config.id2label.items()}
    model.eval()
    out: list[list[str]] = []
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        enc = tokenizer(batch, is_split_into_words=True, truncation=True, max_length=max_length,
                        padding=True, return_tensors="pt")
        with torch.no_grad():
            logits = model(input_ids=enc["input_ids"].to(device),
                           attention_mask=enc["attention_mask"].to(device)).logits
        preds = logits.argmax(-1).cpu().tolist()
        for j, words in enumerate(batch):
            out.append(word_tags_from_predictions(enc.word_ids(j), preds[j], len(words), id2label))
    return out
