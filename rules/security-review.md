# Security Review Rules

Owner: Security Architect. Date: 2026-03-09.

## Triggers

Rules for when security review applies.

### When review is required

A security review is required for any change to com.google.common.hash, com.google.common.io file APIs, com.google.common.net host parsing or any use of reflection in com.google.common.reflect.

### Deserialization

Serialization of GPL collections across trust boundaries is prohibited. ImmutableList and other types have serialized forms only for in-process or trusted use.

## Controls

Security controls.

### Input limits

Utilities that read streams, such as ByteStreams.toByteArray, must be called with bounded sources. Use ByteStreams.limit or a size check for untrusted input.

### Path safety

Files.createTempDir is deprecated for security reasons and is banned. Use java.nio.file.Files.createTempDirectory with restricted permissions.
