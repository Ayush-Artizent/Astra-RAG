# Eval: guava-golden

Corpus: golden-repos/guava-golden. Each item has question, expected answer, source, category.

## Questions

1. Q: What is the maximum time customer data may stay in a platform cache? A: 24 hours, via expireAfterWrite. Source: policies.md#data-handling/retention. Category: factual.
2. Q: Which hash functions are approved for new code? A: sha256(), sha512(), crc32c() (integrity only), murmur3_128() (non-security partitioning). Source: policies.md#hashing-and-integrity/approved-algorithms. Category: factual.
3. Q: What false positive probability must production Bloom filters use? A: 0.01 or lower (upstream default 0.03 only for non-production tooling). Source: policies.md#hashing-and-integrity/bloom-filter-sizing. Category: factual.
4. Q: What is the current deprecation window? A: At least 12 months and two minor releases. Source: policies.md#deprecation-and-support/deprecation-window. Category: factual.
5. Q: What is the default maximumSize of platform caches? A: 25,000 entries (ADR-019). Source: project-data/architecture/adr-019-cache-default-v2.md. Category: conflict/superseded.
6. Q: Was ADR-014 (10,000 entries) still valid? A: No, it is superseded by ADR-019. Source: project-data/architecture/adr-014-cache-default.md#status. Category: conflict/superseded.
7. Q: A product owner email asks for a 50,000 default. Is that approved? A: No; ADR-019 sets 25,000 and no CR exists for 50,000. Source: project-data/emails/2026-03-02-cache-default-conflict.md; 2026-03-03-cache-default-reply.md. Category: conflict/superseded.
8. Q: How long is the deprecation window per the 2022 notes versus the current policy? A: 6 months (superseded) versus 12 months and two minor releases. Source: project-data/legacy/deprecation-notes-2022.md; policies.md. Category: conflict/superseded.
9. Q: What is the critical patch time commitment? A: Conflicting: internal rule 5 business days patch; Northwind agreement 3 business days response. Not resolved. Source: rules/dependency-management.md#vulnerability-handling/sla; project-data/contracts/northwind-support-agreement.md. Category: conflict/superseded.
10. Q: What budget and team size does the active charter state? A: 1.6 million currency units and 12 engineers (charter v2; v1 with 1.2 million and 9 is superseded). Source: project-data/charter/project-charter-v2.md. Category: conflict/superseded.
11. Q: What was the old default cache expiry requirement in Cache Requirements v1 and is it current? A: v1 is superseded; REQ-CACHE-004 changed from 10,000 to 25,000 in v2. Source: project-data/requirements/cache-requirements.md; cache-requirements-v2.md. Category: conflict/superseded.
12. Q: Is the nomenclature format confirmed? A: No, Open: format unconfirmed and name validation blocked. Source: nomenclature.md#naming-conventions. Category: open-item.
13. Q: What is open about audit-log cache retention? A: Whether a separate 90-day limit applies is to decide by the Governance Board. Source: policies.md#data-handling/retention; project-data/compliance/data-retention-compliance.md. Category: open-item.
14. Q: What is open about the android flavor support window? A: Whether an 18 month window is feasible is undecided. Source: project-data/emails/2026-06-02-android-flavor-scope.md. Category: open-item.
15. Q: What is open about the Bloom filter design for ingestion? A: Tenant-salted funnel and filter serialization across nodes. Source: project-data/change-requests/CR-2026-038-bloom-filter-standard.md. Category: open-item.
16. Q: Which SBOM dependency license question is open? A: License and attribution of failureaccess 1.0.2. Source: project-data/contracts/oss-license-statement.md#open-items. Category: open-item.
17. Q: Is the Optional-in-APIs rule resolved? A: Guava Optional must not be used in new public APIs; CR-2026-041 approved removal path. Open: none for this item. Source: rules/coding-standards.md#base-utilities/null-handling; CR-2026-041. Category: factual.
18. Q: When drafting an ADR about hashing, which rule files are selected? A: nomenclature (always), security-review, hashing section of policies, and api-compatibility/deprecation where doc_type ADR matches. Source: golden.yaml. Category: rule-selection.
19. Q: Which rules apply to a TEST-PLAN? A: nomenclature (always), testing-standards, documentation-standards. Source: golden.yaml. Category: rule-selection.
20. Q: Which rule is always selected regardless of doc type? A: nomenclature.md. Source: golden.yaml. Category: rule-selection.
21. Q: What is the default runbook template variant? A: standard (others: lightweight, incident). Source: golden.yaml; templates/runbook/. Category: rule-selection.
22. Q: What is the default design-spec variant? A: short (alternative: full). Source: golden.yaml templates. Category: rule-selection.
23. Q: What lowest priority number rule is applied first among security-tagged rules? A: nomenclature priority 10, then rules/security-review.md priority 15. Source: golden.yaml. Category: rule-selection.
24. Q: What is the format of change request ids? A: CR-YYYY-NNN with -E suffix for emergencies. Source: nomenclature.md#identifiers/change-request-ids. Category: factual.
25. Q: What is the GPL version for the JRE flavor release published on 2026-04-14? A: 33.7.2-jre-acme.3. Source: project-data/emails/2026-04-14-release-33-7-2-acme-3.md. Category: factual.
26. Q: What did CR-2026-017 change? A: Default cache concurrencyLevel from 4 to 8, approved 2026-03-11. Source: project-data/change-requests/CR-2026-017-cache-concurrency.md. Category: code-plus-golden.
27. Q: What is the upstream CacheBuilder default concurrencyLevel in code, and how does the platform differ? A: Upstream DEFAULT_CONCURRENCY_LEVEL is 4 (CacheBuilder.java); platform sets 8 per CR-2026-017. Source: CacheBuilder.java plus CR-2026-017. Category: code-plus-golden.
28. Q: Which Guava class provides consistent hashing and how many shards does the platform use? A: Hashing.consistentHash with 64 shards. Source: ADR-016 (architecture/adr-016-hashing.md); hash/Hashing.java. Category: code-plus-golden.
29. Q: What RateLimiter settings do gateway services use? A: RateLimiter.create(200.0, 3, TimeUnit.SECONDS); 3 second warm-up. Source: architecture/adr-017-rate-limiting.md. Category: code-plus-golden.
30. Q: What Bloom filter parameters does the ingestion pipeline use and how much memory? A: expectedInsertions 50,000,000, fpp 0.001, about 86 MB. Source: emails/2026-05-11-bloom-filter-sizing.md. Category: code-plus-golden.
31. Q: Which util.concurrent classes manage long-running services? A: AbstractScheduledService or AbstractIdleService with ServiceManager. Source: requirements/concurrency-requirements.md (REQ-CONC-003). Category: code-plus-golden.
32. Q: What issue is GPL-1042? A: Flaky test in ExecutionSequencer wrapper, Open, Medium, QA Lead. Source: jira-export/gpl-issues.csv (issue_key GPL-1042). Category: factual.
33. Q: What are the cache settings for REG-001? A: Order Services, maximum_size 25000, concurrency 8, hit ratio 0.91. Source: analytics/cache-region-metrics.csv. Category: factual.
34. Q: How many cache regions hold customer-derived data per the compliance note? A: 37 of 200 as of 2026-03-01. Source: compliance/data-retention-compliance.md#evidence. Category: factual.
35. Q: Which team owns the target for exception CR-2026-030 and when does it expire? A: Mobile Platform Lead; android 33.7.2 exception until 2026-11-05. Source: change-requests/CR-2026-030-exception-guava-19.md. Category: factual.
36. Q: What did the board decide on EventBus deprecation? A: CR-2026-033 rejected; in-process EventBus remains allowed. Source: change-requests/CR-2026-033-eventbus-removal.md; raid/decisions-log.md. Category: factual.
37. Q: What is the Kafka topic retention for GPL audit events? A: Not in the corpus. Expected: system states it cannot find this. Source: none. Category: negative/not-in-corpus.
38. Q: What is the GPL Gradle plugin's minimum supported Gradle version? A: Not in the corpus. Source: none. Category: negative/not-in-corpus.
39. Q: Who is the named person leading the Core Collections team? A: Not in corpus; only the role Core Collections Lead exists (fictional role-based). Source: none. Category: negative/not-in-corpus.
40. Q: What was the Q4 2026 release date of GPL 35.0? A: Not in the corpus. Source: none. Category: negative/not-in-corpus.
