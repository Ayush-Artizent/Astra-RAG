"""The code plane's query modes as MCP tools, built from the vendored OpenAPI contract.

Each mode is its own tool so that the rules the adapter enforces at runtime — exactly one symbol for
callers and impact, at least two for flow, search terms for lookup — are expressed in the schema
instead, where the calling model sees them before it calls rather than as a 422 afterwards.

Argument definitions (types, lengths, limits) are read from `contracts/code-adapter.openapi.yaml`,
so they cannot drift from the adapter unnoticed. `tests/mcp/test_code_contract.py` pins what we rely
on; if the code plane changes it, that test names the field.
"""
from functools import cache
from pathlib import Path
from typing import Any, Callable

import yaml

CONTRACT = Path(__file__).parent / "contracts" / "code-adapter.openapi.yaml"

# `mode` is set by the tool, and `fallback_origin` describes how the caller derived its terms, which
# is not something an MCP client can answer. Neither is exposed.
SHARED = ("path_prefix", "limit", "include_code", "max_code_chars")


@cache
def request_properties() -> dict[str, Any]:
    """`CodeQueryRequest.properties` exactly as the contract defines them."""
    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return spec["components"]["schemas"]["CodeQueryRequest"]["properties"]


def _props(*names: str, **extra: dict) -> dict:
    chosen = {name: dict(request_properties()[name]) for name in names}
    chosen.update(extra)
    return chosen


def _single_symbol(what: str) -> dict:
    """The contract's symbol item type as one string: the "exactly one" rule, in the schema."""
    return {**dict(request_properties()["symbols"]["items"]), "description": what}


def _object(properties: dict, required: list[str] | None = None, **extra) -> dict:
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    schema.update(extra)
    return schema


def _body(mode: str, args: dict, *, symbol_as_list: bool = False) -> dict:
    """A validated adapter request. Only contract fields are passed: it refuses anything else.

    `mode` and `fallback_origin` belong to the tool, not the caller, so they are dropped from the
    arguments and set here. Otherwise a caller could pass `mode` and make one tool run another's
    query, which is exactly what splitting the modes into separate tools is meant to prevent.
    """
    allowed = set(request_properties()) - {"mode", "fallback_origin"}
    sent = {key: value for key, value in args.items() if key in allowed}
    if symbol_as_list and args.get("symbol"):
        sent["symbols"] = [args["symbol"]]
    return {**sent, "mode": mode}


SYMBOL_HINT = (
    "Qualified name, for example TokenService.issue. Pin a file with path/to/file.py::Class.method "
    "when a bare name is ambiguous."
)

TOOLS: dict[str, dict[str, Any]] = {
    "find_symbol": {
        "description": (
            "Find where symbols are defined in this project's code, by qualified name or by keyword. "
            "Returns each one's file, line range and source, with a citation. Use it to locate code "
            "before reasoning about it."
        ),
        "schema": _object(
            _props("symbols", "keywords", *SHARED),
            anyOf=[{"required": ["symbols"]}, {"required": ["keywords"]}],
        ),
        "build": lambda args: _body("lookup", args),
    },
    "find_callers": {
        "description": (
            "List what calls a symbol, directly or through a few hops. Each result says how it is "
            "linked (calls, instantiates, references, imports) and where the call site is."
        ),
        "schema": _object(
            _props("depth", *SHARED, symbol=_single_symbol(SYMBOL_HINT)),
            required=["symbol"],
        ),
        "build": lambda args: _body("callers", args, symbol_as_list=True),
    },
    "analyze_impact": {
        "description": (
            "What depends on a symbol, and so what could break if it changes. Wider than callers: it "
            "follows dependents outwards, three hops by default."
        ),
        "schema": _object(
            _props("depth", *SHARED, symbol=_single_symbol(SYMBOL_HINT)),
            required=["symbol"],
        ),
        "build": lambda args: _body("impact", args, symbol_as_list=True),
    },
    "trace_flow": {
        "description": (
            "Trace the path through the code between two or more symbols, in the order given, for "
            "example from a controller to the service it ends up calling. Returns the hops between "
            "each consecutive pair."
        ),
        "schema": _object(
            _props(*SHARED, symbols={**dict(request_properties()["symbols"]), "minItems": 2,
                                     "description": f"Two or more, in order. {SYMBOL_HINT}"}),
            required=["symbols"],
        ),
        "build": lambda args: _body("flow", args),
    },
    "code_index_status": {
        "description": (
            "Whether this project's code index is ready, which commit it reflects and how far behind "
            "the repository it is. Worth checking when a code search returns nothing."
        ),
        "schema": _object({}),
        "build": None,  # not a query: the client calls /status
    },
}


def builder(name: str) -> Callable[[dict], dict] | None:
    return TOOLS[name]["build"]
