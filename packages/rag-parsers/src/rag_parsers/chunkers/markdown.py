"""Markdown chunker for golden repos (§5).

Split on headings, keep the heading path (``Payments > Refunds > Eligibility``) as metadata,
and never split inside a fenced code block or a table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rag_parsers.base import ParsedChunk, ParsedEdge, SourceFile

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass
class MarkdownChunker:
    name: str = "markdown"
    max_lines: int = 150  # oversize sections are split on blank lines outside fences/tables

    def supports(self, path: str, language: str | None) -> bool:
        return language == "markdown"

    def chunk(self, file: SourceFile) -> list[ParsedChunk]:
        lines = file.text.splitlines()
        sections: list[tuple[int, int, list[str]]] = []  # (start_idx, end_idx_excl, heading_path)
        path: list[tuple[int, str]] = []
        start, in_fence = 0, False
        for i, line in enumerate(lines):
            if _FENCE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            m = _HEADING.match(line)
            if m:
                if i > start:
                    sections.append((start, i, [t for _, t in path]))
                level = len(m.group(1))
                path = [(lvl, t) for lvl, t in path if lvl < level] + [(level, m.group(2))]
                start = i
        sections.append((start, len(lines), [t for _, t in path]))

        out: list[ParsedChunk] = []
        for s, e, hp in sections:
            for ps, pe in self._split(lines, s, e):
                body = "\n".join(lines[ps:pe])
                if body.strip():
                    out.append(
                        ParsedChunk(
                            text=body, start_line=ps + 1, end_line=pe, heading_path=hp or None
                        )
                    )
        return out

    def _split(self, lines: list[str], s: int, e: int) -> list[tuple[int, int]]:
        if e - s <= self.max_lines:
            return [(s, e)]
        parts, cur, in_fence = [], s, False
        for i in range(s, e):
            if _FENCE.match(lines[i]):
                in_fence = not in_fence
            in_table = lines[i].lstrip().startswith("|")
            if i - cur >= self.max_lines and not in_fence and not in_table and not lines[i].strip():
                parts.append((cur, i))
                cur = i
        parts.append((cur, e))
        return parts

    def edges(self, file: SourceFile) -> list[ParsedEdge]:
        # Phase 2: `documents` edges from path / symbol mentions (§6.3).
        return []
