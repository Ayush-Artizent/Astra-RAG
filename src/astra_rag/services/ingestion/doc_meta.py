"""Header metadata (doc type, date, author/attendees...) and open-item lines, read from the text itself.

Everything here is information for the LLM: nothing ranks or filters by it.
"""
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ...config import DEFAULT_DOC_TYPE, DOC_TYPE_BY_FOLDER, PROJECT_DATA_DIR_NAME

_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_HEADER_LINES = 8          # metadata lives at the top of a document
_VALUE_MAX_CHARS = 300
_EMAIL_KEYS = {"from", "to", "cc", "date", "subject"}
_EMAIL_LINE = re.compile(r"^([A-Za-z][A-Za-z ]{0,19}):\s*(.+)$")
_BOLD_FIELD = re.compile(r"\*\*([^*:]+?):\*\*\s*(.*?)(?=\s*[·|]\s*\*\*|$)")
_ITALIC_LINE = re.compile(r"^[_*](.+?)[_*]$")
_OPEN_ITEM = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?(?:open(?:\s+(?:question|item|issue)s?)?|tbd|pending decision)\s*[:\-]"
                        r"|\bto decide\b|\bundecided\b", re.IGNORECASE)


@dataclass
class DocMeta:
    doc_type: str
    date: str | None = None
    fields: dict[str, str] = field(default_factory=dict)


def extract_metadata(path: str, text: str) -> DocMeta:
    """doc_type comes from the folder; date and fields from the header lines (emails, meeting notes, CRs)."""
    pure = PurePosixPath(path)
    folders = [p for p in pure.parent.parts if p != PROJECT_DATA_DIR_NAME]
    top = folders[0] if folders else ""
    doc_type = DOC_TYPE_BY_FOLDER.get(top, top or DEFAULT_DOC_TYPE)

    header = [ln.strip() for ln in text.splitlines() if ln.strip()][:_HEADER_LINES]
    fields = _email_fields(text)
    fields.update(_inline_fields(header))

    date = None
    if "date" in fields and (m := _DATE.search(fields["date"])):
        date = m.group(0)
    elif m := _DATE.match(pure.name):
        date = m.group(0)
    else:
        for line in header:
            if (it := _ITALIC_LINE.match(line)) and (m := _DATE.search(it.group(1))):
                date = m.group(0)
                break
    return DocMeta(doc_type, date, fields)


def open_items(text: str) -> list[str]:
    """Lines that mark something as unresolved ('Open: ...', 'Finance to decide')."""
    return [ln.strip() for ln in text.splitlines() if _OPEN_ITEM.search(ln)]


def _clean_key(key: str) -> str:
    return re.sub(r"\s+", "_", key.strip().lower())


def _email_fields(text: str) -> dict[str, str]:
    """A leading block of `Key: value` lines (From/To/Date/Subject), ended by the first blank line."""
    found: dict[str, str] = {}
    started = False
    for line in text.splitlines():
        if not line.strip():
            if started:
                break
            continue
        started = True
        m = _EMAIL_LINE.match(line.strip())
        if not m:
            break
        found[_clean_key(m.group(1))] = m.group(2).strip()[:_VALUE_MAX_CHARS]
    return found if len(found) >= 2 and set(found) & _EMAIL_KEYS else {}


def _inline_fields(header: list[str]) -> dict[str, str]:
    """`**Date:** x · **Attendees:** y` and `_Owner: x · 2026-08-28_` lines."""
    found: dict[str, str] = {}
    for line in header:
        if line.startswith("#") or line.startswith("|"):
            continue
        for m in _BOLD_FIELD.finditer(line):
            found[_clean_key(m.group(1))] = m.group(2).strip()[:_VALUE_MAX_CHARS]
        if (it := _ITALIC_LINE.match(line)) and "**" not in line:
            for part in re.split(r"\s*·\s*", it.group(1)):
                key, sep, value = part.partition(":")
                if sep and key.strip() and len(key) <= 20 and value.strip():
                    found[_clean_key(key)] = value.strip()[:_VALUE_MAX_CHARS]
    return found
