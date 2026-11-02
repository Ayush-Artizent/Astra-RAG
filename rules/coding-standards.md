# Coding Standards

Standards for code that uses GPL. Owner: Core Collections Lead. Date: 2026-02-03.

## Collections

Rules for collection types.

### Immutability first

Public APIs must return ImmutableList, ImmutableSet or ImmutableMap rather than mutable collections. Use ImmutableList.copyOf for defensive copies. Builders must not be reused after build() is called.

### Multimaps and tables

Use ListMultimap or SetMultimap instead of a Map of List. Use Table for two-key lookups. Multimaps built with MultimapBuilder must state their backing type explicitly, for example MultimapBuilder.hashKeys().arrayListValues().

## Base utilities

Rules for com.google.common.base.

### Null handling

Use Preconditions.checkNotNull for argument validation and checkArgument for domain validation with a message template. Guava Optional must not be used in new public APIs because java.util.Optional is the standard. Strings.nullToEmpty is allowed at module boundaries.

### Strings

Use Joiner and Splitter instead of manual loops. Splitter instances are immutable and must be declared as static final constants. Splitter.on(',').trimResults().omitEmptyStrings() is the approved CSV-line form.

## Concurrency

Rules for com.google.common.util.concurrent.

### Futures

Asynchronous APIs return ListenableFuture. Callbacks use Futures.addCallback with an explicit executor; MoreExecutors.directExecutor() is allowed only for trivially cheap callbacks. Use Futures.transformAsync for chaining.

### Rate limiting

Use RateLimiter.create(double) for throttling. Smooth bursty limiters allow up to one second of burst by default. Warm-up limiters are required for cold downstream services.
