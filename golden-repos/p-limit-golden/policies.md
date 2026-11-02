# Engineering Policies

Policies for the Concurrency Limiter Library (internal name: LimitKit, published package `p-limit`).

## Versioning

Rules for how LimitKit releases are numbered and which runtimes they support.

### Semantic versioning

LimitKit follows semantic versioning. The current released version is 7.3.3. Breaking changes to the public API or to the minimum Node.js version require a major release.

### Node.js support

The minimum supported Node.js version is 20, declared in `engines.node` as `>=20`. Dropping a Node.js version is a major change.

## Dependencies

Rules limiting what the package depends on at runtime and in development.

### Runtime dependency budget

The library may have exactly one runtime dependency. Today it is `yocto-queue` at `^1.2.1`. Adding a second runtime dependency needs an approved ADR.

### Dev dependencies

Dev tooling is limited to `ava` for tests, `tsd` for type tests, `xo` for linting, plus helpers `in-range`, `random-int` and `time-span`.

## Change control

Rules for how changes to the library are requested and reviewed.

### Review requirement

Every change to `index.js` or `index.d.ts` needs two approvals, one from a code owner. Documentation-only changes need one approval.

### Change requests

Behavior changes to the public API must have a change request in `CR-NNN` format before implementation starts.

## Data handling

Rules for data used in examples and for retaining project records.

### No sensitive data in tasks

The library never inspects task arguments or results. Examples and test fixtures must not contain customer data or credentials.

### Retention of project records

Project records such as meeting notes and RAID logs are kept for 3 years after the last release of the major version they cover.
