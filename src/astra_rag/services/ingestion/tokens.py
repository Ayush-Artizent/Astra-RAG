"""Cheap, dependency-free token estimate, deliberately a little pessimistic for WordPiece."""
import math
import re

_PIECE = re.compile(r"\w+|[^\w\s]")


def count_tokens(text: str) -> int:
    total = 0
    for piece in _PIECE.findall(text):
        total += max(1, math.ceil(len(piece) / 4)) if (piece[0].isalnum() or piece[0] == "_") else 1
    return total
