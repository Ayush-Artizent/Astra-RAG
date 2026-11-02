# Non-Functional Requirements

Date: 2026-02-25
Owner: Product Owner

## REQ-201 Python support

Supported Python is 3.10 and newer.

## REQ-202 Dependencies

Zero mandatory runtime dependencies. Colorama was removed in 8.5.0.

## REQ-203 Test coverage

Line coverage of `src/click` must be at least 95 percent.

## REQ-204 Typing

The package ships `py.typed` and passes mypy and pyright.
