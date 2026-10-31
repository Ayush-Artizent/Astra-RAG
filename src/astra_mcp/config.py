"""Configuration for the MCP server. Everything is read from the environment at spawn."""
import os
import re
from dataclasses import dataclass

# The code plane turns org and project ids into directory names, so its pattern is the stricter of
# the two (the doc plane also allows dots). An id has to work on both planes, so we enforce this one.
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

DEFAULT_DOC_URL = "http://127.0.0.1:5000"
DEFAULT_CODE_URL = "http://127.0.0.1:8091"
DEFAULT_TIMEOUT_MS = 30_000
MIN_ENVELOPE_KEY_CHARS = 16  # the code adapter refuses a shorter key, so refuse it here too


class ConfigError(Exception):
    """Startup refused. The message reaches whoever spawned the server, so it must be safe to show."""


@dataclass(frozen=True)
class Config:
    """One project on one pair of planes. Bound at spawn, never per call."""
    org_id: str
    project_id: str
    doc_url: str
    code_url: str
    envelope_key: str
    timeout_ms: int

    @property
    def timeout_seconds(self) -> float:
        return self.timeout_ms / 1000


def _required(env: dict, name: str) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise ConfigError(f"{name} is required.")
    return value


def _identifier(env: dict, name: str) -> str:
    value = _required(env, name)
    if not ID_PATTERN.fullmatch(value):
        raise ConfigError(
            f"{name} must start with a letter or digit and hold only letters, digits, '_' or '-' "
            f"(at most 64 characters), because the code plane uses it as a directory name."
        )
    return value


def _url(env: dict, name: str, default: str) -> str:
    value = (env.get(name) or "").strip() or default
    if not value.startswith(("http://", "https://")):
        raise ConfigError(f"{name} must be an http or https URL.")
    return value.rstrip("/")


def _timeout(env: dict) -> int:
    raw = (env.get("ASTRA_MCP_TIMEOUT_MS") or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_MS
    if not raw.isdigit() or int(raw) <= 0:
        raise ConfigError("ASTRA_MCP_TIMEOUT_MS must be a positive whole number of milliseconds.")
    return int(raw)


def load(env: dict | None = None) -> Config:
    """Read and check the environment. Raises ConfigError naming the first problem found."""
    env = os.environ if env is None else env
    key = _required(env, "ASTRA_ENVELOPE_KEY")
    if len(key) < MIN_ENVELOPE_KEY_CHARS:
        # Never name the value, only its length requirement.
        raise ConfigError(f"ASTRA_ENVELOPE_KEY must be at least {MIN_ENVELOPE_KEY_CHARS} characters.")
    return Config(
        org_id=_identifier(env, "ASTRA_ORG_ID"),
        project_id=_identifier(env, "ASTRA_PROJECT_ID"),
        doc_url=_url(env, "ASTRA_DOC_URL", DEFAULT_DOC_URL),
        code_url=_url(env, "ASTRA_CODE_URL", DEFAULT_CODE_URL),
        envelope_key=key,
        timeout_ms=_timeout(env),
    )
