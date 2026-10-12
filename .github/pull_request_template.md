## What & why

<!-- Link the ticket. Reference the design doc section (e.g. §7.1) if relevant. -->

## Checklist

- [ ] Tests added/updated; `uv run poe check` passes locally
- [ ] **Tenancy:** no new code path accepts `tenant_id` from a caller; new stores read it from `rag_core.tenancy`
- [ ] **Redaction:** nothing logs raw chunk text, query text, or secret values
- [ ] **Provenance:** new results carry citations / `trace_id` / snapshot
- [ ] **Eval:** if this touches chunking, embeddings, ranking or prompts: eval report attached and `INDEX_VERSION` bumped if stored shape/semantics changed
- [ ] Decision changed? Updated `docs/decisions.md` or added an ADR
