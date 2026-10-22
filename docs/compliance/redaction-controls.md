# Redaction controls: security and compliance notes

Status: working notes for the compliance review. Not a compliance certification. Owner: ingestion pod.
Design reference: §9 of the design doc (see [README](../../README.md)). Code: `packages/rag-core/src/rag_core/redaction.py`,
`services/rag-ingest/src/rag_ingest/stages/`.

## 1. Control statement

Secrets and personal data are removed from code and documents **before** chunking, embedding, logging
or tracing. If redaction cannot run or fails, the file is **not indexed** (fail closed). Query text is
redacted before it is written to the trace.

## 2. Where redaction sits in the data flow

| Stage | Input | Redacted before? |
|---|---|---|
| Ingest step 5 (`IndexPipeline._process_file`) | raw file text from git | Yes: before parse, chunk, hash, embed, store |
| Retrieval trace (`rag_api` `_traceable`) | caller query text | Yes: before the trace record is stored |
| Retrieval response text | indexed chunks | Already redacted at ingest |
| Logs (`rag_core.observability`) | - | Policy: never log raw chunk text, query text or redaction values |

## 3. What is detected

| Detector | Kinds | Where it runs | Notes |
|---|---|---|---|
| Specific secret formats (regex) | AWS, GitHub, GitLab, Slack, Slack webhook, Google, Stripe, SendGrid, npm, Anthropic, OpenAI, JWT, Azure storage, connection-string password | All files | Hand-ported subset of the gitleaks defaults |
| Generic assignments (regex) | `password = "..."`, `api_key: "..."` and similar | All files | Keeps the key name, redacts the value |
| Private key blocks | PEM `BEGIN … PRIVATE KEY` to `END` | All files | Whole block is replaced |
| Entropy check | Quoted tokens of 20+ chars with at least 4.2 bits per char and mixed classes | All files | Tuned on this repo; see §5 |
| PII regex | Email, credit card (Luhn), US SSN, IBAN (mod-97) | All files | Test and example domains are allowlisted |
| PII NER (Presidio) | Person names, phone numbers, locations | **Prose only** (`.md`, `.rst`, `.txt`, `.adoc`), **off by default** | See §5 |

Typed placeholders such as `[REDACTED:AWS_KEY]` replace the matched text. Line counts never change, so
citation line ranges still point at the right code.

## 4. Fail-closed behaviour

| Failure | Result | Covered by test |
|---|---|---|
| File over `max_chars` (5 MB) | `RedactionError`, file skipped | `test_file_over_limit_is_refused` |
| Any detector raises | `RedactionError`, file skipped | `test_detector_error_is_refused_not_passed_through` |
| Pipeline sees redaction error | File counted in `files_failed_redaction`, rest of job indexed | `test_redaction_failure_skips_only_that_file` |
| Query redaction raises | Trace stores `[REDACTED:REDACTION_FAILED]`; the request still answers | `test_query_trace_fails_closed` |
| Presidio requested but `pii` extra or spaCy model missing | Construction raises at startup; the worker does not start | `test_missing_model_fails_at_startup` |
| Line count changes during redaction | `RedactionError` | Built into `_redact` |

Presidio is checked with `importlib.util.find_spec` before it loads. Otherwise Presidio tries to
download the model and calls `sys.exit`, which bypasses the normal error path.

## 5. Known limits and evidence

- **NER on prose is not precise enough to enable by default.** Test run on this repo's 11 prose files:
  44 hits, all false positives. Examples: `Blob`, `Key Vault`, `Terraform`, `Docker`, `Kubernetes`,
  `Astra RAG`, `Jira`. Raising the score threshold from 0.6 to 0.85 changed nothing, because these
  entities come with fixed scores.
- **NER on code is unusable.** The first run flagged 500+ identifiers in repo code as names or
  locations, for example `cache[user_id]` as LOCATION. The NER is therefore restricted to prose.
- **NER is slow on whole repos.** About 63 s for the repo's files with NER on every file; about 2.5 s
  for 11 prose files.
- **Regex PII covers only four types.** Names, phone numbers, postal addresses, dates of birth and
  other free-text personal data are not detected unless NER is on and works for that text.
- **Secret rules are a subset.** The full gitleaks ruleset is not loaded here. `.gitleaks.toml` only
  extends the defaults of the gitleaks binary, which is not installed in this environment. Run
  gitleaks in CI as the backstop.
- **Entropy threshold is tuned on one repo.** Expect false positives and negatives on other code.
- **No PDFs or Office documents yet.** Redaction only sees text the parsers produce. Binary and
  converted documents are not covered until those parsers exist.
- **No per-tenant allowlists yet.** Only the module default allowlist exists.

## 6. Operational notes

- **Re-index required.** `INDEX_VERSION` is 2. Chunks indexed under version 1 may contain text that the
  current rules would now redact. A full re-index is needed to remove them. Version 1 data still needs
  to be purged or re-indexed by ops.
- **Eval baseline.** `eval/baselines/smoke.json` still records `index_version: 1`. Regenerate it with
  `rag-eval`. Do not edit it by hand.
- **Logging.** The per-job redaction report logs `files_failed`, and `counts` per kind. It never logs
  matched values. Keep it that way: any change to the log format needs review.
- **Enabling NER** needs `uv sync --extra pii`, and `build_redactor(ner=True)` wired into the worker.
  The worker wiring does not exist yet.

## 7. Open decisions (for the compliance review)

1. Should NER be on by default for prose? Retrieval quality would drop, because technical terms get
   redacted. Compliance coverage would rise. Needs a tuned allowlist before it can be on.
2. Should per-tenant allowlists be required before go-live?
3. Is a regex-only PII set acceptable for the first release, with NER added later?
4. Which PII categories must be covered for the tenants' data? This list has not been agreed.
5. Retention of the redaction report counts and of the trace records: not decided.

## 8. Evidence

- Unit tests: `packages/rag-core/tests/test_redaction.py`, covering every sample secret and PII type,
  false-positive guards, line stability, citation line stability and fail-closed behaviour.
- Pipeline tests: `services/rag-ingest/tests/test_pipeline.py`.
- Query trace tests: `services/rag-api/tests/test_api.py`.
- NER tests: `services/rag-ingest/tests/test_presidio_pii.py` (skip the NER tests without the `pii` extra).
- Sample PII and secret values in the tests are fake: AWS documentation examples and published Luhn and
  mod-97 test vectors.
