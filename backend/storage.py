"""Files the API keeps: uploaded documents, patient photos and rendered report pages.

Everything lives under backend/uploads/ (git-ignored), or CHRONOTRACE_UPLOADS when set (tests use a
temporary folder). Paths stored in the database are relative to that folder.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parent / "uploads"

# File signatures of the accepted types (the extension and content type from the browser are not trusted).
KINDS = {"pdf": (b"%PDF", "application/pdf"), "jpg": (b"\xff\xd8\xff", "image/jpeg"),
         "png": (b"\x89PNG\r\n\x1a\n", "image/png")}


def root() -> Path:
    path = Path(os.environ.get("CHRONOTRACE_UPLOADS") or DEFAULT_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_type(data: bytes, allowed: tuple[str, ...]) -> str | None:
    """"pdf", "jpg" or "png" from the file's first bytes, if it is one of `allowed`."""
    return next((k for k in allowed if data.startswith(KINDS[k][0])), None)


def media_type(path: str) -> str:
    return KINDS.get(Path(path).suffix.lstrip(".").lower(), (b"", "application/octet-stream"))[1]


def save(relative: str, data: bytes) -> str:
    target = root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative


def absolute(relative: str) -> Path:
    return root() / relative


def remove(relative: str | None) -> None:
    if relative:
        (root() / relative).unlink(missing_ok=True)
