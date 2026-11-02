# Dependency Management Rules

Owner: Build Engineering Lead. Date: 2026-02-17.

## Approved dependencies

Rules about what GPL may depend on.

### Transitive dependencies

GPL depends on failureaccess 1.0.2, jspecify and error_prone_annotations. No other runtime dependencies may be added without a change request. The listenablefuture artifact is an empty stub kept for classpath compatibility.

### Bill of materials

Consumers must import the guava-bom artifact in dependencyManagement and not pin individual versions. Version overrides require an exception.

## Shading and relocation

Rules for embedding GPL.

### Relocation policy

GPL is not shaded by default. Libraries that embed GPL must relocate com.google.common to com.acme.shaded.guava. Open: relocation guidance for Gradle plugin authors is to decide.

## Vulnerability handling

Rules for vulnerabilities.

### SLA

Critical vulnerabilities in GPL or its dependencies are patched within 5 business days, high within 15 business days, medium within 45 days. Patch releases increment the acme suffix only.
