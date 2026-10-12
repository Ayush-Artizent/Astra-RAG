"""Language-agnostic fallback (§5): structure-aware line windows with overlap.

Nothing should ever fail on an unsupported language. Windows prefer to break on blank lines
or dedents near the target size so chunks stay roughly whole.
"""

from __future__ import annotations

from dataclasses import dataclass

from rag_parsers.base import ParsedChunk, ParsedEdge, SourceFile


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


@dataclass
class WindowChunker:
    name: str = "window"
    target_lines: int = 60
    max_lines: int = 100
    overlap: int = 8

    def supports(self, path: str, language: str | None) -> bool:
        return True

    def chunk(self, file: SourceFile) -> list[ParsedChunk]:
        lines = file.text.splitlines()
        if not lines:
            return []
        out: list[ParsedChunk] = []
        start = 0
        while start < len(lines):
            end = min(start + self.max_lines, len(lines))
            if end < len(lines):
                end = self._best_break(lines, start, end)
            body = "\n".join(lines[start:end])
            if body.strip():
                out.append(ParsedChunk(text=body, start_line=start + 1, end_line=end))
            if end >= len(lines):
                break
            start = max(end - self.overlap, start + 1)
        return out

    def _best_break(self, lines: list[str], start: int, hard_end: int) -> int:
        lo = start + self.target_lines // 2
        for i in range(min(start + self.target_lines, hard_end), lo, -1):
            if not lines[i - 1].strip() or (
                i < len(lines) and _indent(lines[i]) == 0 and lines[i].strip()
            ):
                return i
        return hard_end

    def edges(self, file: SourceFile) -> list[ParsedEdge]:
        return []
