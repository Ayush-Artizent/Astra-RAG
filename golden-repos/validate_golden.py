#!/usr/bin/env python3
"""Validate golden repos against GOLDEN_RULES.md. Usage: python -I validate_golden.py <repo_dir> [...]"""
import csv
import os
import re
import sys

INDEXED = {".md", ".markdown", ".txt", ".csv", ".docx"}
FOLDER_TYPES = {"emails", "meeting-notes", "change-requests", "requirements", "stakeholders", "contracts",
                "charter", "architecture", "compliance", "legacy", "ux", "raid", "jira-export", "analytics"}
SECRET_RE = re.compile(r"(ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|password\s*[:=]\s*\S+|api[_-]?key\s*[:=]\s*\S+)", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@(?!example\.(com|org)|.*\.example|.*\.invalid)[\w-]+\.[\w.]+")
PROMPT_RE = re.compile(r"(ignore (all )?previous instructions|you are an? (ai|assistant)|system prompt)", re.I)


def tokens(s):
    return int(len(s.split()) * 1.3)


def sections(text):
    """Split markdown into (heading, body) ignoring fences and front-matter."""
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    out, cur, body, fence = [], None, [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            if cur is not None:
                out.append((cur, "\n".join(body).strip()))
            cur, body = m.group(2), []
        else:
            body.append(line)
    if cur is not None:
        out.append((cur, "\n".join(body).strip()))
    return out


def validate(root):
    err, warn, stats = [], [], {"files": 0, "chunks": 0, "skipped": 0}
    for req, kind in [("policies.md", "f"), ("nomenclature.md", "f"), ("project-data", "d"), ("templates", "d")]:
        p = os.path.join(root, req)
        if not (os.path.isfile(p) if kind == "f" else os.path.isdir(p)):
            err.append(f"422 missing required {req}")
    if err:
        return err, warn, stats

    if not os.path.isfile(os.path.join(root, "golden.yaml")):
        warn.append("no golden.yaml: rules will be empty for requests")
    else:
        try:
            import yaml
            y = yaml.safe_load(open(os.path.join(root, "golden.yaml"), encoding="utf-8"))
            for k in y or {}:
                if k not in {"version", "doc_types", "stages", "tags", "rules", "templates", "project_data"}:
                    warn.append(f"golden.yaml unknown key {k}")
            for i, r in enumerate((y or {}).get("rules") or []):
                if "file" not in r:
                    warn.append(f"golden.yaml rules[{i}] missing file")
                elif not os.path.isfile(os.path.join(root, r["file"])):
                    warn.append(f"golden.yaml rules[{i}] file not found: {r['file']}")
        except ImportError:
            warn.append("pyyaml not installed; golden.yaml not parsed")
        except Exception as e:
            warn.append(f"golden.yaml bad YAML: {e}")

    # rule files
    rule_files = ["policies.md", "nomenclature.md"]
    for d, _, fs in os.walk(os.path.join(root, "rules")):
        rule_files += [os.path.relpath(os.path.join(d, f), root).replace("\\", "/") for f in fs if f.endswith(".md")]
    for rf in rule_files:
        p = os.path.join(root, rf)
        if os.path.getsize(p) >= 1_000_000:
            err.append(f"{rf} >= 1MB")
        secs = sections(open(p, encoding="utf-8").read())
        if not secs:
            warn.append(f"{rf} has no headings")
        for h, b in secs:
            if not b:
                warn.append(f"{rf}#{h}: empty body (dropped)")

    # templates
    tpl = os.path.join(root, "templates")
    entries = os.listdir(tpl)
    if not entries:
        warn.append("no_templates")
    for e in entries:
        p = os.path.join(tpl, e)
        if os.path.isdir(p) and len(os.listdir(p)) > 1:
            warn.append(f"template type {e.upper()} has {len(os.listdir(p))} variants: confirm default in golden.yaml")

    # project-data
    pd = os.path.join(root, "project-data")
    for d, dirs, fs in os.walk(pd):
        dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(d, x))]
        for f in fs:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, root).replace("\\", "/")
            if os.path.islink(p):
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext not in INDEXED:
                stats["skipped"] += 1
                warn.append(f"skipped (unsupported): {rel}")
                continue
            stats["files"] += 1
            if os.path.getsize(p) > 25 * 1024 * 1024:
                err.append(f"{rel} > 25MB")
            if ext == ".docx":
                continue
            text = open(p, encoding="utf-8", errors="replace").read()
            top = os.path.relpath(d, pd).split(os.sep)[0]
            if top not in FOLDER_TYPES and top != ".":
                warn.append(f"unknown folder type kept as-is: {top}")
            if SECRET_RE.search(text):
                err.append(f"possible secret in {rel}")
            if EMAIL_RE.search(text):
                warn.append(f"possible real email/PII in {rel}")
            if PROMPT_RE.search(text):
                warn.append(f"prompt-like text in {rel}")
            if ext == ".csv":
                rows = list(csv.reader(text.splitlines()))
                stats["chunks"] += len(rows)
                if len(rows) < 2:
                    warn.append(f"{rel}: csv has no data rows")
                continue
            if re.search(r"^---\s*$", text, re.M) and not text.startswith("---"):
                warn.append(f"{rel}: '---' divider lines are dropped")
            if not re.search(r"(Date:\s*\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2})", text[:600] + f):
                warn.append(f"{rel}: no date in header or filename")
            secs = sections(text) if ext in (".md", ".markdown") else [("", text)]
            if ext in (".md", ".markdown") and not secs:
                warn.append(f"{rel}: no headings (single chunk)")
            for h, b in secs:
                stats["chunks"] += 1
                t = tokens(b)
                if t > 480:
                    warn.append(f"{rel}#{h}: ~{t} tokens > 480 (will split)")
                elif t > 380:
                    warn.append(f"{rel}#{h}: ~{t} tokens > 380 (chunks less well)")
                if not b:
                    warn.append(f"{rel}#{h}: empty body")
    return err, warn, stats


if __name__ == "__main__":
    bad = 0
    for r in sys.argv[1:]:
        e, w, s = validate(r)
        print(f"== {r}\n   errors={len(e)} warnings={len(w)} files={s['files']} approx_chunks={s['chunks']} skipped={s['skipped']}")
        for x in e:
            print("   ERROR", x)
        for x in w[:60]:
            print("   warn ", x)
        if len(w) > 60:
            print(f"   ... {len(w) - 60} more warnings")
        bad += bool(e)
    sys.exit(1 if bad else 0)
