"""The report-row NER model, loaded once per process.

Model source, in order: the CHRONOTRACE_MODEL environment variable (a local folder or a Hugging
Face Hub id), then ml/models/chronotrace-ner if it exists, then the Hub model. Runs on CPU unless
a GPU is available.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[2]
LOCAL_MODEL = ROOT / "ml" / "models" / "chronotrace-ner"
HUB_MODEL = "Rip-Shadw/chronotrace-report-ner"


class Tagger(Protocol):
    source: str

    def tag(self, rows: list[list[str]]) -> list[list[str]]:
        """One BIO tag per word for each row."""
        ...


def model_source() -> str:
    env = os.environ.get("CHRONOTRACE_MODEL", "").strip()
    if env:
        return env
    if (LOCAL_MODEL / "config.json").exists():
        return str(LOCAL_MODEL)
    return HUB_MODEL


class NerTagger:
    def __init__(self, source: str | None = None):
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        self.source = source or model_source()
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(self.source)
        self.model = AutoModelForTokenClassification.from_pretrained(self.source).to(self.device).eval()

    def tag(self, rows: list[list[str]]) -> list[list[str]]:
        from shared.ner_infer import predict_tags

        return predict_tags(self.model, self.tokenizer, rows, self.device) if rows else []


_lock = threading.Lock()
_tagger: NerTagger | None = None


def get_tagger() -> NerTagger:
    """The process-wide tagger (loaded on first use)."""
    global _tagger
    with _lock:
        if _tagger is None:
            _tagger = NerTagger()
        return _tagger
