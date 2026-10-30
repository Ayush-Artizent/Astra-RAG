"""One token budget for a whole response, spent in a fixed order; whatever does not fit is left out and flagged."""
from dataclasses import dataclass, field
from typing import Callable, TypeVar

from ..ingestion.tokens import count_tokens

T = TypeVar("T")


@dataclass
class Budget:
    limit: int
    used: int = 0
    truncated: list[str] = field(default_factory=list)  # section names that lost content

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def flag(self, section: str) -> None:
        if section not in self.truncated:
            self.truncated.append(section)

    def take_items(self, items: list[T], section: str, text_of: Callable[[T], str]) -> list[T]:
        """The leading items that fit whole. The first one that does not ends the list (order is priority)."""
        kept: list[T] = []
        for item in items:
            cost = count_tokens(text_of(item))
            if cost > self.remaining:
                self.flag(section)
                break
            self.used += cost
            kept.append(item)
        return kept

    def take_text(self, text: str, section: str) -> str:
        """The whole text, or the leading whole lines that fit."""
        kept: list[str] = []
        for line in text.splitlines(keepends=True):
            cost = count_tokens(line)
            if cost > self.remaining:
                self.flag(section)
                break
            self.used += cost
            kept.append(line)
        return "".join(kept)
