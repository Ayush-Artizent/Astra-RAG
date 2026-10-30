# Retrieval test cases - ecommerce-checkout-revamp golden repo

Repo: `https://github.com/manojb-nous/ecommerce-example-repo`
Slug: `github.com__manojb-nous__ecommerce-example-repo` (confirm with `GET /api/repos`)
Server: `http://127.0.0.1:5000` (Swagger: `/docs`). Expected results are in `retrieval-expected.md`, same IDs.

## 0. Setup (run once)

| ID | API call | Body | Pass when |
|----|----------|------|-----------|
| SETUP-1 | `GET /api/repos` | - | slug is listed, `index_state: ready`, `needs_rebuild: false` |
| SETUP-2 | `GET /api/ingestion-status/github.com__manojb-nous__ecommerce-example-repo` | - | latest run `done` |
| SETUP-3 | `PUT /api/projects/proj-1/binding` (not needed if you passed `project_id` when connecting) | `{"repo_slug":"github.com__manojb-nous__ecommerce-example-repo"}` | 200 |
| SETUP-4 | `GET /api/projects/proj-1/catalog` | - | 6 doc types (BRD, SPEC, TESTCASES, USER-STORIES, TEST-PLAN, CHANGE-REQUEST), few or no warnings |

## 1. Raw search - `POST /api/search` (knowledge retrieval only, no project binding needed)

| ID | Test question | API call | Body |
|----|---------------|----------|------|
| S01 | When does traffic switch from Razorpay to PayU? | `POST /api/search` | `{"slug":"github.com__manojb-nous__ecommerce-example-repo","query":"when do we switch from Razorpay to PayU fallback gateway","limit":8}` |
| S02 | What is the COD limit for new customers? | `POST /api/search` | `{"slug":"github.com__manojb-nous__ecommerce-example-repo","query":"what is the COD limit for new customers","limit":8}` |
| S03 | How and when are failed-but-debited payments refunded? | `POST /api/search` | `{"slug":"github.com__manojb-nous__ecommerce-example-repo","query":"failed but debited payment refund timing","limit":8}` |
| S04 | Have the PayU production keys arrived? | `POST /api/search` | `{"slug":"github.com__manojb-nous__ecommerce-example-repo","query":"PayU production keys status","limit":5}` |
| S05 | Where is the biggest drop-off in the funnel? (CSV row) | `POST /api/search` | `{"slug":"github.com__manojb-nous__ecommerce-example-repo","query":"funnel drop off at address step","limit":5}` |
| S06 | What is the UPI success rate? (CSV row) | `POST /api/search` | `{"slug":"github.com__manojb-nous__ecommerce-example-repo","query":"UPI share and success rate","limit":5}` |
| S07 | Was the EMI request approved? | `POST /api/search` | `{"slug":"github.com__manojb-nous__ecommerce-example-repo","query":"EMI instalment options change request decision","limit":5}` |
| S08 | Same topic, emails only (folder filter) | `POST /api/search` | `{"slug":"github.com__manojb-nous__ecommerce-example-repo","query":"payment gateway","limit":10,"folder":"emails"}` |
| S09 | Same topic, CSV only (file_type filter) | `POST /api/search` | `{"slug":"github.com__manojb-nous__ecommerce-example-repo","query":"COD new customer limit","limit":10,"file_type":"csv"}` |
| S10 | Out-of-scope question (nothing in the data) | `POST /api/search` | `{"slug":"github.com__manojb-nous__ecommerce-example-repo","query":"SSO single sign-on identity provider decision","limit":5}` |
| S11 | Unknown repo slug | `POST /api/search` | `{"slug":"github.com__nobody__nothing","query":"anything"}` |

## 2. Full context - `POST /api/context` (rules + template + knowledge)

All use `project_id: proj-1` (bound in SETUP-3). Allowed stages: discovery, requirements, design, build, test, release.

| ID | Test question | API call | Body |
|----|---------------|----------|------|
| C01 | Payments BRD: rules + payments template + gateway facts | `POST /api/context` | `{"project_id":"proj-1","doc_type":"BRD","text":"payment gateway failover thresholds Razorpay PayU; automatic refund of failed but debited payments","stage":"requirements","tags":["payments"],"budget":12000}` |
| C02 | Your original example (SSO / onboarding portal is NOT in this repo) | `POST /api/context` | `{"project_id":"proj-1","doc_type":"BRD","text":"SSO single sign-on decision customer onboarding portal","stage":"draft","tags":["security"],"budget":12000}` |
| C03 | Test cases for coupons (boundary values, worked examples) | `POST /api/context` | `{"project_id":"proj-1","doc_type":"TESTCASES","text":"coupon validation percentage cap flat coupon expired coupon one coupon per order","stage":"test","tags":["coupons"]}` |
| C04 | User stories for COD (open decision must surface) | `POST /api/context` | `{"project_id":"proj-1","doc_type":"USER-STORIES","text":"cash on delivery COD eligibility exclusions fee limit for new customers","stage":"requirements","tags":["cod"]}` |
| C05 | Change request via ALIAS "change request" | `POST /api/context` | `{"project_id":"proj-1","doc_type":"change request","text":"EMI instalment options change request decision","stage":"requirements","tags":["governance"]}` |
| C06 | API spec: variant switch to api-spec-template | `POST /api/context` | `{"project_id":"proj-1","doc_type":"SPEC","text":"payment events idempotent payment attempts order_id attempt_no gateway_txn_id","stage":"design","tags":["api","payments"]}` |
| C07 | Same as C01 but NO stage (stage-scoped rule drops out) | `POST /api/context` | `{"project_id":"proj-1","doc_type":"BRD","text":"payment gateway failover thresholds Razorpay PayU; automatic refund of failed but debited payments","tags":["payments"]}` |
| C08 | Test plan, performance focus | `POST /api/context` | `{"project_id":"proj-1","doc_type":"TEST-PLAN","text":"checkout performance targets p95 latency gateway failover testing","stage":"test","tags":["performance","payments"]}` |
| C09 | Tiny budget forces truncation | `POST /api/context` | `{"project_id":"proj-1","doc_type":"BRD","text":"payment gateway failover thresholds Razorpay PayU; automatic refund of failed but debited payments","stage":"requirements","tags":["payments"],"budget":500}` |
| C10 | Unknown doc type | `POST /api/context` | `{"project_id":"proj-1","doc_type":"PRD","text":"anything"}` |
| C11 | Unbound project | `POST /api/context` | `{"project_id":"not-bound","doc_type":"BRD","text":"anything"}` |
| C12 | Blank text | `POST /api/context` | `{"project_id":"proj-1","doc_type":"BRD","text":"   "}` |
| C13 | Budget below minimum (500) | `POST /api/context` | `{"project_id":"proj-1","doc_type":"BRD","text":"anything","budget":100}` |
| C14 | Selection only, no knowledge search | `POST /api/context/preview` | `{"project_id":"proj-1","doc_type":"BRD","stage":"requirements","tags":["payments"]}` |

> **`text` must be a clean request.** `/api/context` searches and reranks with `text` exactly as sent, and no LLM rewrites it. Send a short
> topic phrase (the subject and key terms), not an instruction like "Write a BRD for ...": long instruction wording made the reranker bury key
> chunks (see CHANGELOG 2026-10-30, clean request text). `search_project_data` (T02) requires `project_id` in `arguments`.

## 3. Tool form (what the LLM calls)

| ID | Test question | API call | Body |
|----|---------------|----------|------|
| T01 | What tools exist, with doc_type enum from the catalog? | `GET /api/tools?project_id=proj-1` | - |
| T02 | search_project_data tool | `POST /api/tools/invoke` | `{"name":"search_project_data","arguments":{"project_id":"proj-1","query":"gateway failover thresholds","limit":5}}` |
| T03 | get_document_context tool | `POST /api/tools/invoke` | `{"name":"get_document_context","arguments":{"project_id":"proj-1","doc_type":"BRD","text":"payment gateway failover thresholds Razorpay PayU","stage":"requirements","tags":["payments"]}}` |
| T04 | Bad arguments (missing query) | `POST /api/tools/invoke` | `{"name":"search_project_data","arguments":{"limit":5}}` |
| T05 | Unknown tool | `POST /api/tools/invoke` | `{"name":"no_such_tool","arguments":{}}` |

## PowerShell one-liners

```powershell
$base = "http://127.0.0.1:5000"
# POST helper: Post "/api/search" '<json body>'
function Post($path, $json) { Invoke-RestMethod -Method Post -Uri "$base$path" -ContentType "application/json" -Body $json | ConvertTo-Json -Depth 12 }

Post "/api/search" '{"slug":"github.com__manojb-nous__ecommerce-example-repo","query":"what is the COD limit for new customers","limit":8}'
Post "/api/context" '{"project_id":"proj-1","doc_type":"BRD","text":"payment gateway failover thresholds Razorpay PayU; automatic refund of failed but debited payments","stage":"requirements","tags":["payments"]}'
```
