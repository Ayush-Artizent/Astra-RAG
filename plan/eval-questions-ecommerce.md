# Retrieval question list: ecommerce example repo

> **Status: starter list (2026-10-28).** Seeds the evaluation set planned in P11 of [phases.md](phases.md).
> The expected sources were taken from reading the actual repo files, not from search output, so the list is independent of the retriever.

Paths are relative to `project-data/` of the ecommerce example repo. A question marked **all** passes only if every listed source
is returned, because nothing prefers newer or authoritative sources: the LLM, not retrieval, resolves conflicts.

## Questions

| # | Question | Type / difficulty | Expected source(s) | Facts the chunks should contain |
|---|---|---|---|---|
| E01 | What does CHK-104 cover? | exact ID / easy | `stories.csv` row CHK-104 | 10000, COD-enabled |
| E02 | Who owns RSK-002 and what is its impact? | exact ID / easy | `raid-log.csv` row RSK-002 | Logistics Integration Manager, Medium |
| E03 | What is out of scope for the checkout epic? | tie case / easy | `checkout-epic.md` > Not in scope | Buy-now-pay-later, International shipping |
| E04 | What are the SOW exclusions? | lookup / easy | `sow-summary.md` | loyalty-points redemption, BNPL |
| E05 | What are the project KPIs and their targets? | table / medium | `project-charter.md` (KPI table) | 41%, 52%, 94%, 2.5 s |
| E06 | When is design freeze and when does 100% rollout happen? | lookup / easy | `project-charter.md` > Timeline | 2026-11-15, 2027-03 |
| E07 | What are the gateway failover thresholds? | multi-source / medium | gateway-failover email; payments-sync (any) | 5%, 4 s, 15 minutes |
| E08 | Which gateway is primary and which is the fallback? | lookup / easy | gateway-failover email | Razorpay, PayU |
| **E09** | **What is the COD limit for new customers?** | **conflict + diluted chunk / hard** | `coupon-and-cod-rules.md` > COD, finance-sync, payments-sync, `raid-log.csv` ISS-001, `checkout-epic.md` > Scope, `stories.csv` CHK-104 (**all**) | 7,500, 10,000, steering 2026-10-28 |
| E10 | What is the COD fee, and what can't be COD? | lookup / medium | `coupon-and-cod-rules.md` > COD | 49, gift cards, 5,000 |
| E11 | Which reasons does the user see for an invalid coupon? | multi-source / medium | `coupon-and-cod-rules.md` > Coupons; CHK-105 (any) | expired, minimum order value, category |
| E12 | Which PCI/compliance constraints apply to card data? | table / medium | `pci-and-consumer-rules.md` (table); payments-sync (any) | CMP-01, SAQ A |
| **E13** | **How fast must failed-but-debited payments be refunded?** | **multi-source / hard** | compliance CMP-05, payments-sync, finance-sync (**all**) | T+1, 24 h, 23:00 |
| E14 | What are the steps of the new checkout versus the old one? | multi-source / medium | ux-review, `screen-inventory.md`, `current-checkout-flow.md` (all) | 3 steps, 6 steps |
| E15 | Where do customers drop off most in the funnel? | lookup / medium | `funnel-aug-2026.csv`; legacy flow (any) | address 27, payment 23, login 19 |
| E16 | Who approves the BRD and who is responsible? | table / medium | `stakeholder-register.md` (table) | Chief Digital Officer, Product Owner |
| E17 | Which events does the payment service publish? | multi-source / medium | `payment-integration.md`; CHK-107 (any) | order.created, order.failed |
| E18 | What is the status of CR-003? | lookup / easy | `CR-003-save-for-later.md` | Deferred, 7 person-days |
| E19 | Which risks and dependencies are still open? | multi-source / medium | `raid-log.csv` (RSK-001, RSK-002, DEP-001) | Spring sale, PayU |
| **E20** | **Which decisions are still open?** | **open item / hard** | payments-sync, finance-sync, COD rules, ISS-001 (**all**) | COD, steering |
| E21 | How many WCAG failures did the accessibility audit find? | multi-source / easy | ux-review; CHK-110 (any) | 14 |
| E22 | What is the data retention period for customer addresses? | no answer / hard | none; nothing in the repo says this | not applicable |

Short names used above: *gateway-failover email* = `emails/2026-10-02-gateway-failover.md`; *payments-sync* =
`meeting-notes/2026-09-05-payments-sync.md`; *finance-sync* = `meeting-notes/2026-10-10-finance-sync.md`; *ux-review* =
`meeting-notes/2026-09-19-ux-review.md`; *compliance* = `compliance/pci-and-consumer-rules.md`; *legacy flow* =
`legacy/current-checkout-flow.md`; *CHK-xxx* = row in `jira-export/stories.csv`; *ISS-001* / *RSK-xxx* / *DEP-001* = rows in `raid/raid-log.csv`.

## What the tricky cases test
- **Tie (E03):** the Not in scope and Scope chunks scored equally (0.833). The question passes if Not in scope is in the top 2 and its facts are present.
- **Diluted chunk (E09):** the epic's COD limit sits in a long Scope list and was missed in the first run. Passing means the epic's Scope chunk is also returned.
- **Conflicts and open items (E09, E13, E20):** these pass only if all sources are returned, because nothing prefers newer or authoritative ones.
- **No answer (E22):** nothing should look like a confident answer. The top results are just the nearest unrelated chunks.

## How to score it
Take the top 8 results per question. Check whether each expected source appears and where its first hit ranks. Then check that every
listed fact appears in the returned text. Report results by type and difficulty. The first run is a baseline, so set no pass
thresholds until it has been seen.

## How to run a search
Start the app (`uv run python -m astra_rag`), then in PowerShell (the Qdrant container must be up):

```powershell
$q = "What is the COD limit for new customers?"
$body = @{ slug = "github.com__manojb-nous__ecommerce-example-repo"; query = $q; limit = 8 } | ConvertTo-Json
(Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/api/search -ContentType "application/json" -Body $body) | Select-Object score, path, heading_path, row_key | Format-Table -AutoSize
```

Optional body fields: `folder` (e.g. `emails`) and `file_type` (`md`, `csv`, `txt`, `docx`). In PowerShell use `Invoke-RestMethod`
or `curl.exe`; the bare `curl` alias does not accept `-H` / `-d`.
