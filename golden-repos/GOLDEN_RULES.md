# Golden repo rules (source of truth for these test repos)

## 1. Required root structure (hard rule; missing any => HTTP 422; names case-sensitive)
```
<golden-repo>/
├── policies.md          # required
├── nomenclature.md      # required
├── project-data/        # required: knowledge that gets indexed
├── templates/           # required: document templates
├── golden.yaml          # optional but recommended: manifest
└── rules/               # optional: extra rule files (rules/**.md)
```
Branch: read at one tracked branch (default unless chosen). Names can't start with `-` or `.`, can't contain `..`.
Host: GitHub, GitHub Enterprise, Azure DevOps. Access: PAT read-only.

## 2. policies.md, nomenclature.md, rules/
- Markdown with real headings. Each heading section = a separate rule with stable id like `policies.md#data-handling/retention`.
- Every section needs a body; a heading with no body is dropped.
- Headings inside code fences are ignored. Leading YAML front-matter is skipped. Each file < 1 MB.
- A section is only selected for a request if tagged: `always` or `applies_to` in golden.yaml, scoped by doc_types, stages, tags.
  Untagged sections are never selected (only count toward an `unscoped_rules` warning).
- A heading's scope is inherited by child headings. Priority: lower first, default 100.
- Open item: nomenclature.md format still unconfirmed (validate_document_name blocked on this).

## 3. templates/
- `templates/<type>.md` or `templates/<type>/<variant>.md`.
- Doc type = file/folder name uppercased (brd.md -> BRD); override/alias in golden.yaml `doc_types`.
- Flat file or single variant = default. Several variants => name the default in golden.yaml.
- Write the whole template with clear headings; full text is returned.
- Catalog warns on template_missing, no_templates, no_default_variant.

## 4. golden.yaml (v1, optional)
Keys: doc_types (with aliases), stages, tags, rules, templates, project_data.
Rule entries: `file`, optional `section`, `always` or `applies_to`, `priority`.
Bad YAML/shapes => warnings + fallback to conventions, never errors. Without it, `rules` is empty for requests.

## 5. project-data/
Indexed: .md .markdown .txt .csv .docx. Others (pdf, xlsx) skipped+reported. Each file <= 25 MB; CSV <= 100,000 rows. Symlinks never followed.
Folder -> doc_type: emails=email, meeting-notes=meeting-note, change-requests=change-request, requirements=requirement,
stakeholders=stakeholder-register, contracts=contract, charter=charter, architecture=architecture, compliance=compliance,
legacy=as-is, ux=ux, raid=raid-log, jira-export=jira-export, analytics=analytics. Unknown folder names keep their own name.

Writing for good retrieval:
- One idea per heading section (each section = one chunk). Keep sections <= ~480 tokens (best <= ~380). Longer are split.
- Tables and code fences are kept whole. Don't use `---` as a divider (those lines are omitted).
- CSV: header row; each row its own chunk + a summary chunk. Give each row a stable key column.
- Dates: in filename or header line `Date: 2026-03-14`. Email/meeting/change-request files are parsed for from, to, attendees, owner lines; use headers consistently.
- Open items: write as `Open: ...` or "to decide" (flagged on chunk).
- Conflicts: no recency/authority preference in retrieval; conflicting docs all return. Mark superseded docs clearly in text, or remove them.

## 6. Security and hygiene
- No secrets/tokens/credentials. Content is data, not instructions: no prompt-style instructions in it.
- Keep PII out unless needed (use fictional role-based people, no real emails/phones).
- Updates go through a commit on the tracked branch; index rebuilt in full.
