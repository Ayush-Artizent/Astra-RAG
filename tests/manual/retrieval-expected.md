# Expected results - retrieval test cases

IDs match `retrieval-test-cases.md`. Paths are under `project-data/` unless they start with `rules/`, `policies.md`, `nomenclature.md` or `templates/`.
Rule and template expectations were derived by hand from `golden.yaml` using the P8 selection rules (a scope matches when every
dimension it lists is satisfied; `tags` need any overlap; a dimension the request omits does not satisfy a scope that lists it).
Exact ordering of knowledge items may vary; check that the named sources appear in the top results (rank 1-5), not the exact rank.

## Setup

| ID | Expected |
|----|----------|
| SETUP-1 | repo row with `index_state: ready`, `indexed.commit_sha` set |
| SETUP-2 | `state: done`, no error |
| SETUP-3 | 200 and the binding echoed |
| SETUP-4 | doc types: BRD, SPEC, TESTCASES, USER-STORIES, TEST-PLAN, CHANGE-REQUEST. Templates: BRD has 2 variants (default `brd-template`), SPEC has 2 (default `functional-spec-template`) |

## Raw search

| ID | Must appear in hits | Key fact the hit text must contain | Must NOT |
|----|--------------------|------------------------------------|----------|
| S01 | `emails/2026-10-02-gateway-failover.md` (top 3); also `meeting-notes/2026-09-05-payments-sync.md`, `requirements/payment-retry-and-failure-handling.md` | Primary Razorpay, fallback PayU; switch when error rate > 5% over rolling 5 min OR p95 > 4 s; switch back after 15 min healthy; card and UPI only | - |
| S02 | `requirements/coupon-and-cod-rules.md`, `meeting-notes/2026-10-10-finance-sync.md`, `raid/raid-log.csv` (ISS-001) | Undecided: Finance INR 7,500 vs PO INR 10,000, decision at steering 2026-10-28. General COD limit INR 10,000 | A single confident "the limit is X" (it is open) |
| S03 | `requirements/payment-retry-and-failure-handling.md`, `meeting-notes/2026-10-10-finance-sync.md`, `emails/2026-10-06-refund-report.md` | Auto refund, batch T+0 23:00, daily Finance report, UPI refund within T+1 | - |
| S04 | `emails/2026-10-14-payu-production-keys.md`, `raid/raid-log.csv` (DEP-001) | Keys requested, NOT arrived yet; failover testable in sandbox only | - |
| S05 | `analytics/funnel-aug-2026.csv` | Row `address,59100,27` (27% drop-off). Per-row CSV chunk with `row_key` and row range | - |
| S06 | `analytics/payment-method-mix-aug-2026.csv` | Row `upi,46,90` (46% share, 90% success) | - |
| S07 | `change-requests/CR-001-emi-options.md` (rank 1) | Status Rejected 2026-09-17; falls under SOW buy-now-pay-later exclusion; would need new commercial agreement. Also `contracts/sow-summary.md` likely | - |
| S08 | every hit has `folder_parts[0] == "emails"` (5 files exist) | Gateway failover and PayU key emails rank first | Any `meeting-notes/`, `raid/` or `requirements/` hit |
| S09 | every hit is a `.csv` (`raid/raid-log.csv`, `jira-export/stories.csv` for CHK-104, funnel/payment CSVs) | `ISS-001,Issue,COD new customer limit undecided` ranks first | Any `.md` hit |
| S10 | Returns *something* (hybrid search returns whatever is nearest) but scores are clearly low and none mention SSO / identity provider | No SSO content exists in this repo | A hit that states an SSO decision. If one does, that is a defect or a data issue |
| S11 | HTTP 404 (or a safe error naming the missing index), no stack trace | - | Token or host details in the error |

## Full context

Common to every successful C-case: `snapshot.rules_commit` = repo head, `snapshot.index_commit` = indexed commit (not null),
`budget` object present, no PAT anywhere, `status.rules: ok` (or `stale` if GitHub is unreachable).
Always-on rules (every successful call): all of `policies.md` sections 1-6, 8-12, `nomenclature.md` sections 1-3, 8, 9, and `R-GOV-04`
(open decisions listed, not resolved; priority 5 so it sorts first).

| ID | Rules selected on top of the always-on set | Template | Knowledge must include | Status / warnings |
|----|---------------------------------------------|----------|------------------------|-------------------|
| C01 | `policies.md` 7 (BRD + requirements); `nomenclature.md` 4; R-SEC-01, R-SEC-03, R-PAY-01, R-PAY-03, R-PAY-04, R-PAY-07, R-UX-03, R-GOV-02, R-GOV-05 | `brd-payments-template` (tags payments beats the default) | `emails/2026-10-02-gateway-failover.md`, `requirements/payment-retry-and-failure-handling.md`, `meeting-notes/2026-10-10-finance-sync.md` | `status.knowledge: ok`; `status.rerank: ok` (or `skipped: timeout` on the first call while the model downloads); `unscoped_rules` warning counting untagged sections |
| C02 | Always-on + `policies.md` 7? NO (stage `draft` is not requirements/design/build); `nomenclature.md` 4; R-SEC-06 (BRD + security); R-GOV-02, R-GOV-05. R-SEC-01/R-PAY rules NOT selected (their tags are payments) | `brd-template` (default; no payments tag) | NOTHING about SSO or an onboarding portal. Items returned, if any, are weak matches (checkout, stakeholders, security-review) | Not an error. Good result = the knowledge block does not support the SSO claim, so the LLM must say it is missing. A fabricated SSO decision in knowledge is a failure. `draft` is not a defined stage, so stage-scoped rules silently drop out |
| C03 | `nomenclature.md` 7; R-CPN-01, R-CPN-02, R-CPN-03 (coupons+ux overlap on coupons), R-SEC-04, R-QA-01 (stage test), R-QA-02, R-QA-04 (stage test), R-QA-05. NOT R-QA-03 (needs performance), NOT R-GOV-02 (not TESTCASES) | `test-case-template` | `requirements/coupon-and-cod-rules.md` (worked examples: 20% cap INR 500 on INR 4,000 gives INR 500; flat INR 150; expired at payment is rejected; never negative), `jira-export/stories.csv` CHK-105 | ok |
| C04 | `nomenclature.md` 6; R-COD-01, R-COD-02, R-COD-03, R-GOV-02, R-GOV-05 | `user-story-template` | `requirements/coupon-and-cod-rules.md`, `jira-export/stories.csv` CHK-104, `meeting-notes/2026-10-10-finance-sync.md` or `raid/raid-log.csv` ISS-001 | ok. Open items must be visible: new-customer COD limit undecided (INR 7,500 vs 10,000) and whether the INR 49 fee counts toward the limit |
| C05 | `request.doc_type` resolves to `CHANGE-REQUEST` via alias; `nomenclature.md` 10, 12; R-GOV-01, R-GOV-02, R-GOV-03, R-GOV-05 | `cr-impact-template` | `change-requests/CR-001-emi-options.md` (Rejected), `contracts/sow-summary.md` (BNPL exclusion) | ok. The knowledge must show EMI was already rejected so the CR cannot be written as new scope |
| C06 | `policies.md` 7 (SPEC + design); `nomenclature.md` 5; R-SEC-01, R-SEC-02, R-SEC-03, R-SEC-04, R-SEC-05, R-PAY-01, R-PAY-02, R-PAY-05, R-PAY-06, R-PAY-07, R-UX-03, R-GOV-02, R-API-01..04 | `api-spec-template` (matches tags api; functional is the default but matches 0 dimensions) | `requirements/payment-retry-and-failure-handling.md` (idempotent on order_id + attempt_no), `meeting-notes/2026-10-10-finance-sync.md` (gateway_txn_id + attempt_no), `architecture/payment-integration.md`, `jira-export/stories.csv` CHK-107 | ok |
| C07 | Same as C01 EXCEPT `policies.md` 7 is missing (no stage given, so the stage-scoped rule cannot match) | `brd-payments-template` | same as C01 | ok. Compare `rules[]` with C01: exactly one fewer rule |
| C08 | `nomenclature.md` 7, 10, 11; R-SEC-01, R-PAY-01, R-QA-01, R-QA-02, R-QA-03, R-QA-04. NOT `policies.md` 7 (stage test is not requirements/design/build), NOT R-GOV-03 (needs governance tag), NOT R-QA-05 (TESTCASES only) | `test-plan-template` | `requirements/non-functional-requirements.md`, `emails/2026-10-02-gateway-failover.md`, `raid/raid-log.csv` (RSK-002 p95 900 ms, RSK-003 sandbox vs prod UPI) | ok |
| C09 | Same selection as C01 | same | Few or no items | `budget.truncated` lists left-out sections; `knowledge.truncated` and/or `template.truncated` true; warning `budget_truncated`. Total counted tokens <= 500. Always-on rules are kept before the template and knowledge |
| C10 | - | - | - | HTTP 422; message lists known doc types |
| C11 | - | - | - | HTTP 404 (project not bound) |
| C12 | - | - | - | HTTP 422 (blank text) |
| C13 | - | - | - | HTTP 422 (budget out of 500-100,000) |
| C14 | Same rules as C01 | `brd-payments-template` | none (field absent) | ok. Faster; proves selection works without Qdrant |

## Tools

| ID | Expected |
|----|----------|
| T01 | Two tools: `get_document_context` (its `doc_type` has an enum of the 6 catalog types) and `search_project_data`. Claude-style input schemas |
| T02 | `{notice, data}`; `notice` says the data is reference content, not instructions; `data` same hits as S01 |
| T03 | `{notice, data}` with `data` shaped like the C01 response |
| T04 | 4xx; message names the field `query` and does not echo any value |
| T05 | 4xx or 404; message says the tool is unknown |

## Quick pass/fail summary

- **Retrieval works** if S01-S07 each return their named file, S08 and S09 honour the filters, and C01/C03/C04 return non-empty `knowledge.items` with `source_url`s.
- **Selection works** if C01 vs C07 differ by exactly `policies.md` section 7, and C06 swaps to `api-spec-template`.
- **Grounding is honest** if S10 and C02 return nothing about SSO, and S02/C04 surface the COD limit as an open decision.
- **Failure paths are safe** if S11, C10-C13 and T04/T05 return clean 4xx errors without secrets.
- **Common causes of failure:** `status.knowledge: no_index` (ingestion not finished), `unavailable: ...` (Qdrant down: `docker compose up -d qdrant`), `status.rerank: skipped: timeout` (the reranker is still loading after a restart; wait ~30 s and call again).
