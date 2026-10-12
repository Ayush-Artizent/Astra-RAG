"""Plugin contract. Parsers are tenant-agnostic: they see already-redacted text only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from rag_core.schemas import DocType, EdgeKind, EdgeSource


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: str
    text: str  # redacted text; line count identical to the original file
    language: str | None
    doc_type: DocType


@dataclass(frozen=True, slots=True)
class ParsedChunk:
    text: str
    start_line: int  # 1-based, inclusive
    end_line: int
    symbol: str | None = None
    signature: str | None = None
    heading_path: list[str] | None = None


@dataclass(frozen=True, slots=True)
class ParsedEdge:
    src: str
    dst: str
    kind: EdgeKind
    confidence: float
    source: EdgeSource = EdgeSource.PARSER
    meta: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class ParserPlugin(Protocol):
    name: str

    def supports(self, path: str, language: str | None) -> bool: ...

    def chunk(self, file: SourceFile) -> list[ParsedChunk]: ...

    def edges(self, file: SourceFile) -> list[ParsedEdge]: ...
