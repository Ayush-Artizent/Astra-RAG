# Testing Standards

Owner: QA Lead. Date: 2026-03-16.

## Coverage

Coverage rules.

### Thresholds

Line coverage for modules in com.acme.platform.guava must be at least 85 percent and branch coverage at least 75 percent. Upstream Guava code is not measured.

## Test types

Rules for test types.

### Unit and property tests

Collection extensions must include tests built with guava-testlib, for example MapTestSuiteBuilder and ListTestSuiteBuilder. Cache expiry tests must use FakeTicker.

### Compatibility tests

The android flavor runs the same suite on JDK 8 with the animal sniffer signature check. Open: adding a JDK 21 virtual-thread test lane is to decide.

## Performance

Performance rules.

### Benchmarks

Hot path changes in collect or hash require JMH results compared against the previous release. A regression above 5 percent blocks the change.
