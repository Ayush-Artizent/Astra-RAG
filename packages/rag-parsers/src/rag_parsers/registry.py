"""Ordered plugin registry: first plugin whose ``supports`` returns True wins; fallback is last."""

from __future__ import annotations

from rag_parsers.base import ParserPlugin
from rag_parsers.chunkers.markdown import MarkdownChunker
from rag_parsers.chunkers.window import WindowChunker


class ParserRegistry:
    def __init__(self, fallback: ParserPlugin | None = None) -> None:
        self._plugins: list[ParserPlugin] = []
        self._fallback: ParserPlugin = fallback or WindowChunker()

    def register(self, plugin: ParserPlugin) -> None:
        self._plugins.append(plugin)

    def resolve(self, path: str, language: str | None) -> ParserPlugin:
        for plugin in self._plugins:
            if plugin.supports(path, language):
                return plugin
        return self._fallback


def default_registry() -> ParserRegistry:
    reg = ParserRegistry()
    reg.register(MarkdownChunker())
    return reg
