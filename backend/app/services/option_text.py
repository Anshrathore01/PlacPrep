"""Canonical MCQ option parsing and presentation helpers.

Option labels belong to ``mcq_options.option_key``.  The option text must never
need to carry (or recreate) that label in a client component.
"""

from __future__ import annotations

import html
import re
from typing import Any


# Only remove real formatting tags.  In particular, do not treat mathematical
# comparisons such as ``x < y`` as HTML.
_FORMAT_TAG = re.compile(
    r"</?(?:p|div|span|strong|b|em|i|br|li|ul|ol|code|pre)\b[^>]*>",
    re.IGNORECASE,
)
_BREAK_TAG = re.compile(r"<br\s*/?>", re.IGNORECASE)
_WRAPPER_PAIRS = (("**", "**"), ("__", "__"), ("`", "`"))


def normalize_option_text(value: str | None) -> str:
    """Remove transport/source artifacts without flattening meaningful lines.

    This deliberately does *not* apply a general Markdown renderer or strip
    arbitrary angle-bracketed text: both can change source mathematics and
    code-like options.  Each non-blank line has only horizontal whitespace
    collapsed, while intentional line breaks are retained.
    """
    if value is None:
        return ""

    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    # These sequences are artifacts emitted by JSON/CSV-style imports. They
    # are converted before line-level whitespace handling, not flattened.
    text = re.sub(r"(?<!\\)\\r\\n|(?<!\\)\\n", "\n", text)
    text = html.unescape(text).replace("\u00a0", " ")
    text = _BREAK_TAG.sub("\n", text)
    text = _FORMAT_TAG.sub("", text)

    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()

    # Preserve paragraph boundaries, but discard accidental runs of empty
    # source lines inside a single option.
    compact: list[str] = []
    for line in lines:
        if not line and compact and compact[-1] == "":
            continue
        compact.append(line)
    text = "\n".join(compact)

    for opening, closing in _WRAPPER_PAIRS:
        if text.startswith(opening) and text.endswith(closing) and len(text) > len(opening) + len(closing):
            text = text[len(opening):-len(closing)].strip()
    return text


def canonical_option(option: dict[str, Any]) -> dict[str, Any]:
    """Return the one option shape used by student-facing API responses.

    Legacy aliases stay present temporarily so existing API consumers that use
    ``option_key`` and ``option_text`` continue to work.  New clients should
    render ``label`` and ``text`` and submit ``option_key``.
    """
    option_id = option.get("option_id")
    label = str(option.get("option_key") or "").strip().upper()
    order = int(option.get("display_order") or 0)
    text = normalize_option_text(option.get("option_text"))
    # A legacy importer occasionally persisted the source marker alongside the
    # separately stored key. Remove only an exact leading marker for *this*
    # option; punctuation elsewhere remains source content.
    if label:
        text = re.sub(
            rf"^\s*(?:{re.escape(label)}[.)]|\({re.escape(label)}\))\s*",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    # Strip numeric markers (e.g. 1., (1), etc.)
    text = re.sub(r"^\s*(?:[1-5][.)]|\([1-5]\))\s*", "", text, count=1)
    if label:
        text = re.sub(
            rf"^\s*(?:{re.escape(label)}[.)]|\({re.escape(label)}\))\s*",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    return {
        "id": option_id,
        "label": label,
        "text": text,
        "order": order,
        "option_key": label,
        "option_text": text,
        "display_order": order,
    }
