# Base and IO Requirements

Date: 2025-11-03
Owner: Core Collections Lead
Status: Approved

## REQ-BASE-001 preconditions

Argument validation shall use Preconditions.checkArgument and checkNotNull with message templates.

## REQ-BASE-002 stopwatch

Elapsed time measurement shall use Stopwatch with an injectable Ticker for tests.

## REQ-IO-001 bounded reads

Reading untrusted streams shall use ByteStreams.limit with a maximum of 10 MB unless an ADR states otherwise.

## REQ-IO-002 charset

Text IO shall pass StandardCharsets.UTF_8 explicitly to CharSource and CharStreams.
