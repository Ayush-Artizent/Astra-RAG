# ASTRA MCP demo page: plan

> **Status: draft (2026-10-31).** Branch `orch`.
> **For a demo, not for production.** It exists so people can watch the connector work. It is not an operator
> tool, it is not deployed anywhere, and it has no bearing on M0-M4, which are complete without it.

## 1. What a demo has to do

Show someone, in about two minutes, that one MCP connection reaches a project's documents *and* its code, and
that what comes back is usable. Everything else is cut.

That reorders the panels I first drafted. **The playground is the demo**; status is a green dot beside it. The
client-configuration snippet, the contract-drift panel, write actions, multiple projects and authentication are
all out — they serve operators and setup, and there are no operators here.

## 2. The data is a schedule dependency

A demo page in front of an empty index is a worse demo than no page. **Both plane teams are preparing real data
for demo time (confirmed 2026-10-31)**, so the content is no longer an unknown — it is something to land on time
and rehearse against.

What that means for building this:

- **Build against stand-ins now, do not wait.** The code side already works end to end: a `file://` repo indexed
  into the real adapter with `ASTRA_ALLOW_FILE_REPOS=1`, no host or PAT needed, rebuildable in a minute. The
  document side will answer *"This project is not bound to a repository."* until its data lands, which is a
  perfectly good thing to build the error path against.
- **Rehearse as soon as *either* team's data is ready, not when both are.** The expensive surprises are in the
  shape of real payloads — a full-size document context against the per-kind rendering, a real index against the
  ambiguous-symbol note — and each can be found independently.
- **The page must survive missing data.** If either side is not ready on the day, it should say so in a sentence
  and keep working for the other. That is the same rule the connector already follows, and it is the difference
  between a short explanation and a broken demo.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| 1 | Its own small FastAPI app, `astra-mcp-demo`, port 5050. | The MCP server is stdio and spawned per client; there is nothing to attach a page to. |
| 2 | **The page is a real MCP client**: it spawns `astra-mcp` and speaks the protocol. | It is the whole point. "What you are looking at is what DevX's agent sees" is the demo, and calling the planes directly would show the planes working and prove nothing about the connector. |
| 3 | One project, from the same environment variables the server uses. | A demo shows one project. Nothing to choose, nothing to get wrong on stage. |
| 4 | Vanilla Jinja2 + one `app.js` + one `style.css`, reusing the document plane's stylesheet. **Confirmed 2026-10-31: build it the same way as that UI.** | Matches the other page, no build step, and the idiom is already in the repo. |
| 5 | **Render results for people, not as raw JSON.** | A wall of JSON demos badly. See §4. |
| 6 | No repository management, no sync buttons, no auth. | Out of scope for watching it work; the document plane's own UI already does the first two. |

## 4. The page

One screen, top to bottom.

1. **A line of status** — two dots: document plane, code plane, each with a word. Enough to show the stack is up,
   and to explain immediately if something is down mid-demo.
2. **The tools, as the client sees them** — the merged list from a real `tools/list`, each expandable to its
   schema. Worth a beat on stage: `project_id` is not there, and the `doc_type` enum came from the golden repo.
3. **Run one** — pick a tool, a form built from its JSON schema, a Run button.
4. **The answer, in two parts** — the note (when there is one) shown as a sentence above the result, then the
   payload rendered by kind:
   - code results as `file:line` with the symbol and its snippet, not a JSON blob;
   - document results as the rules, then the template, then the evidence, each with its source link;
   - a raw-JSON toggle underneath, because someone always asks.

The note is the part most worth demonstrating: ask for a bare symbol that matches several definitions and the
page says so in a sentence, rather than showing an empty result the audience has to interpret.

## 5. The story to tell

**Proposed 2026-10-31, pending both teams' agreement.** The page should make one narrative easy, because it is
the reason a connector exists at all: **an agent can go from a requirement to the code that implements it, over
one connection.**

The domain is **ecommerce checkout**, because the document plane already has a rich example repo for it with a
`golden.yaml`, templates and 34 project-data files, and a question list checked against the actual files
(`plan/eval-questions-ecommerce.md`). *Assumption to confirm:* that repo, or something like it, is what the
document plane team will demo with — today it lives only in a local `temp_storage/` clone, so it has to be
pushed to a host before the catalog can read it.

| Beat | Call | Should show | What the data must contain |
|---|---|---|---|
| 1 | `tools/list` | One connection, both planes. `project_id` is absent — the agent cannot ask about another project — and `doc_type` is an enum that came from the golden repo. | Both planes reachable; the project bound on one and bootstrapped on the other. |
| 2 | `get_document_context`, doc type `BRD`, text *"payment gateway failover and the events the payment service publishes"* | Rules that apply, the whole template, and evidence with source links: Razorpay primary and PayU fallback, the 5% / 4 s / 15 minute thresholds, `order.created` and `order.failed`. | **At least one `always: true` rule in `golden.yaml`**, or `rules` comes back empty and the plane warns `no_always_rules`. A template for the doc type. The gateway-failover and payment-integration evidence (list questions E07, E08, E17). |
| 3 | `find_symbol`, then `find_callers` on a symbol named in beat 2 | The hop: from what the requirement says to where the code does it — file, lines and the callers. | **The indexed repo must implement this domain.** Something recognisably `PaymentService` / `CheckoutController`, publishing those events or handling failover. **Confirmed 2026-10-31: same domain.** |
| 4 | `find_callers` with a bare name such as `validate` | An empty result with a sentence saying it matched several definitions, naming them, and what to ask instead. The part that reads as a product rather than a demo. | **Two or more symbols sharing a bare name** — say `CouponValidator.validate` and `AddressValidator.validate`. |

**Beat 3 is the one at risk**, and the only one needing both teams to coordinate. If the document plane demos
ecommerce and the code plane indexes something unrelated, there is no hop and the demo becomes two separate
stories — still worth showing, but it stops being an argument for a connector. Settle the code repo's domain
first; everything else is independent.

**A guaranteed fallback for beat 4:** call `get_document_context` with `budget: 500`, the minimum. The plane cuts
content, warns `budget_truncated`, and the note says what was left out. It needs no coordination and works with
any document data, so it is worth having in reserve if the ambiguous symbol cannot be arranged.

## 6. Build order

Two pieces, not five phases. Roughly a day each, and the first is useful alone.

| Step | Delivers |
|---|---|
| D1 | The app, the shell, a real MCP session to a spawned server, the status line and the tool list with schemas |
| D2 | The run form built from a schema, the two-part answer, the per-kind rendering and the raw toggle |

Prepare separately, and before D2 is finished: a sample repo worth searching, and a decision on the document side
(§2). A dry run on the actual demo machine is worth more than any extra feature.

## 7. Open questions

1. ~~**Is the document side in the demo?**~~ **Closed 2026-10-31: both planes are in.** Both teams are
   working to have real data ready by demo time.
2. ~~**Who is watching?**~~ **Closed 2026-10-31:** build it the same way as the document plane's UI — plain
   and functional, the answer rendered for reading, the raw JSON behind a toggle for anyone who asks.
3. ~~**Do both teams accept the four queries in §5?**~~ **Beat 3 confirmed 2026-10-31:** the indexed code repo
   will implement the same domain the golden repo documents, so the hop is on.
4. ~~**Does it need to survive without the planes?**~~ **Closed 2026-10-31: yes.** If either plane is missing
   the page says so in a sentence and keeps working for the other, which is what the connector already does.

**Still to confirm, and it is an action rather than a question:** the ecommerce golden repo currently exists
only as a local `temp_storage/` clone. The catalog reads from the host, not the clone, so until it is pushed and
the project bound, nothing on the document side can answer. Owner: the document plane team.

## 8. What this is not

Not deployed, not authenticated, not multi-project, not an operator console, and not a dependency of anything.
If it is ever wanted for real use, `plan/console-plan.md`'s earlier draft had the operator features — bring them
back deliberately rather than letting the demo grow into them.
