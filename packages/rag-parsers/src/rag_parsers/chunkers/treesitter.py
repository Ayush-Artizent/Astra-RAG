"""tree-sitter chunker: one chunk per function/method/class (§5). OWNER: index & retrieval pod.

Install with ``uv sync --extra treesitter``. Not registered by default until implemented.

TODO(Phase 1):
* Per-language node-type queries for top customer languages (decide list in week 1).
* Very large symbols split on inner blocks; small adjacent symbols may merge.
* ``symbol`` = qualified path (``Class.method``), ``signature`` = declaration line(s).
* File-level ``imports`` edges (§6.3 Phase 2 scope, cheap to emit now).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rag_parsers.base import ParsedChunk, ParsedEdge, SourceFile


@dataclass
class TreeSitterChunker:
    name: str = "treesitter"
    languages: frozenset[str] = field(default_factory=frozenset)

    def supports(self, path: str, language: str | None) -> bool:
        return language in self.languages

    def chunk(self, file: SourceFile) -> list[ParsedChunk]:
        raise NotImplementedError("tree-sitter chunking lands in Phase 1, see module docstring")

    def edges(self, file: SourceFile) -> list[ParsedEdge]:
        raise NotImplementedError
