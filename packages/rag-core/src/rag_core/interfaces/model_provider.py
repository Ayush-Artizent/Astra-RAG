"""LLM access for query rewrite and summaries (§12).

Which models may see customer code is an open policy question, so the provider is resolved
*per tenant* from config. Ship with Azure OpenAI; add self-hosted later without redesign.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable


class LLMPurpose(StrEnum):
    QUERY_REWRITE = "query_rewrite"
    SUMMARY = "summary"
    SYNTHETIC_EVAL = "synthetic_eval"


@runtime_checkable
class ModelProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    async def complete(
        self, prompt: str, *, purpose: LLMPurpose, max_tokens: int = 1024
    ) -> str: ...
