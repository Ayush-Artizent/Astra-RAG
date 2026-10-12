"""Logging + tracing setup. Trace IDs propagate from the caller through every stage (§12).

Never log raw chunk text, query text or redaction values — only redacted text, counts and types.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from opentelemetry import trace


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        span = trace.get_current_span().get_span_context()
        if span.is_valid:
            payload["trace_id"] = format(span.trace_id, "032x")
        for key in ("tenant_id", "repo", "job_id"):
            if (value := record.__dict__.get(key)) is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _JsonFormatter()
        if json_logs
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def get_tracer(name: str) -> trace.Tracer:
    """OTel tracer. Exporter (Azure Monitor) is wired by the service at startup, not here."""
    return trace.get_tracer(name)
