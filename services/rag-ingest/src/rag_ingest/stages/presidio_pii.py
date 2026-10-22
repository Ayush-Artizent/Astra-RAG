"""Presidio NER detector for PII that regex cannot find: names, phone numbers, locations (§9).

Needs the ``pii`` extra (``uv sync --extra pii``), which installs presidio-analyzer and the spaCy
English model. Email, card, SSN and IBAN are left to the regex rules in rag_core, so each finding
is counted under one kind.

Construction fails if the model is missing. A missing model must never mean "no PII checks ran".
"""

from __future__ import annotations

import importlib.util

from rag_core.redaction import EntitySpan

# NER entities the regex rules do not already cover. Other Presidio entities stay disabled.
NER_ENTITIES = ["PERSON", "PHONE_NUMBER", "LOCATION"]
DEFAULT_MODEL = "en_core_web_sm"
DEFAULT_MIN_SCORE = 0.6


class PresidioPiiDetector:
    def __init__(self, model: str = DEFAULT_MODEL, min_score: float = DEFAULT_MIN_SCORE) -> None:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
        except ImportError as exc:
            raise RuntimeError("presidio is not installed: run `uv sync --extra pii`") from exc
        # Presidio downloads a missing model and then calls sys.exit. Check first, so that
        # neither the network nor a SystemExit can slip in during worker startup.
        if importlib.util.find_spec(model) is None:
            raise RuntimeError(f"spaCy model {model!r} is not installed: run `uv sync --extra pii`")
        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": model}],
            }
        )
        nlp_engine = provider.create_engine()
        self._engine = AnalyzerEngine(
            nlp_engine=nlp_engine, supported_languages=["en"], default_score_threshold=min_score
        )
        self.min_score = min_score

    def find(self, line: str) -> list[EntitySpan]:
        if not any(ch.isalpha() for ch in line):
            return []  # nothing a name or location could be on this line
        results = self._engine.analyze(
            text=line, language="en", entities=NER_ENTITIES, score_threshold=self.min_score
        )
        return [EntitySpan(r.start, r.end, r.entity_type) for r in results]
