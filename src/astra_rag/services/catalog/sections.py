"""Splits a markdown file into heading sections with stable ids."""
import re

from .models import Section

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_YAML_KEY = re.compile(r"^[A-Za-z_][\w-]*\s*:")


def slugify(text: str) -> str:
    return _NON_ALNUM.sub("-", text.lower()).strip("-")


def strip_front_matter(text: str) -> str:
    """Blank out a leading YAML front-matter block (kept as empty lines so line numbers stay right)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    first = next((ln for ln in lines[1:] if ln.strip()), "")
    if not _YAML_KEY.match(first):  # a horizontal rule, not front-matter
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "\n".join([""] * (i + 1) + lines[i + 1:])
    return text


def headings(text: str) -> list[tuple[int, str, int]]:
    """Return (level, title, line_number) for each ATX heading outside code fences."""
    found, in_fence = [], False
    for number, line in enumerate(strip_front_matter(text).splitlines(), start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and (m := _HEADING.match(line)) and m.group(2):
            found.append((len(m.group(1)), m.group(2), number))
    return found


def split_sections(file: str, text: str) -> list[Section]:
    """One Section per heading (text up to the next heading of any level); text before the first heading is a preamble."""
    text = strip_front_matter(text)
    lines = text.splitlines()
    marks = headings(text)
    sections: list[Section] = []
    used: dict[str, int] = {}

    def add(title: str, path: tuple[str, ...], level: int, start: int, end: int) -> None:
        body = "\n".join(lines[start - 1:end]).strip()
        if not body:
            return
        base = f"{file}#{'/'.join(slugify(p) for p in path) or 'preamble'}"
        used[base] = used.get(base, 0) + 1
        sid = base if used[base] == 1 else f"{base}-{used[base]}"
        sections.append(Section(sid, file, title, path, level, start, end, body))

    first = marks[0][2] if marks else len(lines) + 1
    if first > 1:
        add("Preamble", (), 0, 1, first - 1)

    stack: list[tuple[int, str]] = []
    for i, (level, title, number) in enumerate(marks):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        end = marks[i + 1][2] - 1 if i + 1 < len(marks) else len(lines)
        body_lines = [ln for ln in lines[number:end] if ln.strip()]
        if body_lines:  # a heading with no body adds nothing; its children carry it in their path
            add(title, tuple(t for _, t in stack), level, number, end)
    return sections


def normalise(text: str) -> str:
    return " ".join(text.lower().split())


def matches_heading(section: Section, wanted: str) -> bool:
    """True when `wanted` names this section's heading, or an ancestor heading, or the full 'A > B' path."""
    want = normalise(wanted)
    path = [normalise(p) for p in section.heading_path]
    return want in path or want == " > ".join(path)
