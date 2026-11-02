# Target Architecture

Date: 2025-06-20
Owner: Platform Architect
Status: Approved

## Module layout

GPL has modules guava-platform-core, guava-platform-cache, guava-platform-hash and guava-platform-concurrent under com.acme.platform.guava. Upstream packages com.google.common.collect, cache, base, hash, util.concurrent and io are consumed unchanged.

## Build and publishing

Maven multi-module build, published to the internal repository as com.acme.platform:guava-platform and guava-bom. Both flavors are built from one tag.

## Runtime baseline

JDK 8 minimum for the jre flavor with tests on JDK 8, 11, 17 and 21.
