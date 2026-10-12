"""Parser plugins: ``supports(path, language)``, ``chunk(file)``, ``edges(file)`` (§5).

New languages are added by registering a plugin, without touching the pipeline.
"""

from rag_parsers.base import ParsedChunk, ParsedEdge, ParserPlugin, SourceFile
from rag_parsers.registry import ParserRegistry, default_registry

__all__ = [
    "ParsedChunk",
    "ParsedEdge",
    "ParserPlugin",
    "ParserRegistry",
    "SourceFile",
    "default_registry",
]
