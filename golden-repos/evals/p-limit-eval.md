# p-limit golden repo evaluation

Corpus: golden-repos/p-limit-golden. Source facts verified against sindresorhus/p-limit (package version 7.3.3).

| # | Category | Question | Expected answer | Source |
|---|---|---|---|---|
| 1 | factual | What is the minimum supported Node.js version? | Node.js 20 (`engines.node` is `>=20`). | policies.md#versioning/node-js-support; requirements/requirements-v2.md NFR-001 |
| 2 | factual | What is the single runtime dependency and its version range? | `yocto-queue` at `^1.2.1`. | policies.md#dependencies/runtime-dependency-budget; architecture/adr-001-queue-implementation.md |
| 3 | factual | What is the default value of `rejectOnClear`? | `false`. | change-requests/CR-101-reject-on-clear.md |
| 4 | factual | What error type and message does invalid concurrency produce? | `TypeError`: Expected `concurrency` to be a number from 1 and up. | rules/coding-standards.md#validation/concurrency-validation |
| 5 | factual | Who raised the request for `rejectOnClear` and why? | Payments Platform Lead; batch job hung on Promise.all after clearQueue. | emails/2026-02-10-rejectonclear-request.md |
| 6 | conflict/superseded | Is concurrency of 0 allowed? | No. Requirements v1 allowed it but is superseded; v2 rejects 0 with TypeError. | requirements/requirements-v1.md vs requirements-v2.md REQ-003 |
| 7 | conflict/superseded | What was the minimum Node.js version in requirements v1, and is it current? | 18, but superseded; current minimum is 20. | requirements/requirements-v1.md NFR-001; requirements-v2.md |
| 8 | conflict/superseded | Should clearQueue reject pending promises by default? | No. CR-102 proposing it was rejected; CR-101 keeps opt-in default false. | change-requests/CR-102-reject-by-default.md |
| 9 | open-item | Is there a maximum queue length? | Not enforced; an open item to confirm a maximum (LIM-245 To Do). | requirements/requirements-v2.md#open-items; jira-export/lim-issues.csv |
| 10 | open-item | What is the confirmed document naming format? | Not confirmed; interim `<DOCTYPE>-<short-title>-<YYYY-MM-DD>.md`. | nomenclature.md#document-naming/document-file-names |
| 11 | open-item | Are benchmarks to be published in release notes? | Undecided (open in 2026-04-08 meeting; LIM-240 To Do). | meeting-notes/2026-04-08-release-planning.md |
| 12 | rule-selection | For a RELEASE-NOTES doc at stage release, which rule files apply besides always rules? | rules/release-and-versioning.md (priority 60); always rules are policies.md#versioning (10) and nomenclature.md (5). | golden.yaml |
| 13 | rule-selection | Which rule applies to a TEST-PLAN at stage test? | rules/testing.md (priority 50). | golden.yaml; rules/testing.md |
| 14 | rule-selection | Which release-notes variant is the default, and which fits a deadlock fix? | Default is `standard`; `hotfix` fits a deadlock fix. | golden.yaml; rules/release-and-versioning.md#hotfix-handling |
| 15 | code-plus-golden | Which function does the code use for concurrency validation, and does it accept Infinity? | `validateConcurrency` in index.js accepts integers above 0 or Infinity, consistent with REQ-003. | architecture/architecture-overview.md; source index.js |
| 16 | code-plus-golden | What reason is passed when pending promises are rejected on clear, and is it recorded in design decisions? | `AbortSignal.abort().reason`, an AbortError, decided 2026-02-17. | meeting-notes/2026-02-17-design-review.md; source index.js clearQueue |
| 17 | code-plus-golden | Does limitFunction expose map or concurrency on the returned function? | No, only `clearQueue`. | change-requests/CR-103-limitfunction-reject-on-clear.md; source limitFunction |
| 18 | factual | Which service had the highest limiter calls in 2026-04? | search, 131.2 million. | analytics/usage-metrics.csv key search-2026-04 |
| 19 | negative | What is the p-limit rate limit per second? | Not in corpus; the charter puts time-window rate limiting out of scope. | none (project-data/charter/project-charter.md#out-of-scope is related) |
| 20 | negative | Which cloud region hosts LimitKit? | Not in corpus; the library makes no network calls. | none |
