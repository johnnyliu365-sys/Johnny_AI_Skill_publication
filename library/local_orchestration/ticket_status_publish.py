"""Join the two halves and put the page where the owner will find it.

The pipeline reads the repository, the template renders the document, and
neither knows about the other — this is the only module that names both, so
the halves stay independently testable and independently owned.

It exists for three decisions that belong to neither half:

**UTF-8 is written explicitly.** The page is almost entirely Chinese and
declares `<meta charset="utf-8">`. On this host Python's default text encoding
is cp950, so a plain `write_text` would encode the page in one charset while
the page announces another, and the owner would double-click their way to
mojibake with every test still green. The UI owner flagged that nobody owned
this boundary; this module owns it.

**The write is atomic.** The page is replaced through a temporary file and
`os.replace`, so a browser refreshing on its own timer never loads a half-
written document and shows the owner a truncated list of what needs them.

**The path is derived, never configured**, like every other owned path.
"""

from __future__ import annotations

import os
from pathlib import Path

from .johnny_root_layout import JohnnyRootLayout
from .ticket_status_pipeline import build_document
from .ticket_status_template import render

_FILE_NAME = "ticket-status.html"
_ENCODING = "utf-8"


def page_path(layout: JohnnyRootLayout) -> Path:
    """Where the owner's page lives inside the per-user root."""

    return layout.base / _FILE_NAME


def write_page(layout: JohnnyRootLayout, body: str) -> Path:
    """Replace the page atomically, in the charset the page declares."""

    path = page_path(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".html.tmp")
    temporary.write_text(body, encoding=_ENCODING)
    os.replace(temporary, path)
    return path


def publish(repository_root: Path, layout: JohnnyRootLayout) -> Path:
    """Read the repository, render the page, replace it. The whole entry."""

    return write_page(layout, render(build_document(repository_root)))


__all__ = ["page_path", "publish", "write_page"]
