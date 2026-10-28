"""What a source adapter authenticates with. The secret never shows up in repr, str or logs."""
from typing import Protocol


class Credential(Protocol):
    def secret(self) -> str: ...


class PatCredential:
    """A personal access token. Read it only through `secret()`, at the moment it is sent."""

    __slots__ = ("_token",)  # no __dict__, so vars()/asdict-style dumps cannot expose it

    def __init__(self, token: str):
        self._token = token

    def secret(self) -> str:
        return self._token

    def __repr__(self) -> str:
        return "PatCredential(<redacted>)"

    __str__ = __repr__
