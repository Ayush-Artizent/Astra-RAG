"""Eval dataset format: JSONL, one :class:`EvalCase` per line.

Sources (§10 bootstrap plan): ``baseline`` current-system captures, ``golden`` past BRDs ->
linked code, ``synthetic`` LLM-generated from known chunks, ``sme`` hand-labelled tickets
(highest value), ``feedback`` from submit_feedback / BRD edits.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class CaseSource(StrEnum):
    BASELINE = "baseline"
    GOLDEN = "golden"
    SYNTHETIC = "synthetic"
    SME = "sme"
    FEEDBACK = "feedback"


class Tool(StrEnum):
    SEARCH_CODE = "search_code"
    SEARCH_DOCS = "search_docs"
    FIND_SIMILAR_REQUIREMENTS = "find_similar_requirements"


class ExpectedSource(BaseModel):
    repo: str
    path: str
    lines: tuple[int, int] | None = None  # None = any chunk of this file counts
    grade: int = Field(default=1, ge=1, le=3)  # graded relevance for nDCG


class EvalCase(BaseModel):
    id: str
    tool: Tool = Tool.SEARCH_CODE
    query: str
    expected: list[ExpectedSource]
    source: CaseSource
    tags: list[str] = Field(default_factory=list)  # e.g. impact, business-rule, similar-brd


def load(path: Path) -> list[EvalCase]:
    with path.open(encoding="utf-8") as f:
        return [EvalCase.model_validate_json(line) for line in f if line.strip()]
