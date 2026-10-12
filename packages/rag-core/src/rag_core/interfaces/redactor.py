"""Secret + PII redaction, mandatory and before anything else (§9).

Contract:
* Replace in place with typed placeholders (``[REDACTED:AWS_KEY]``), keeping line count stable.
* Report counts and types only, never values.
* Fail closed: raise :class:`RedactionError` and the file is NOT indexed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class RedactionError(RuntimeError):
    """Redaction could not be guaranteed; caller must skip the file (fail closed)."""


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@runtime_checkable
class Redactor(Protocol):
    def redact(self, path: str, text: str) -> RedactionResult: ...
