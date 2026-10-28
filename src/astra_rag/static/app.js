const form = document.getElementById("form");
const submit = document.getElementById("submit");
const result = document.getElementById("result");
const ingestion = document.getElementById("ingestion");
const reposSection = document.getElementById("repos");
const repoRows = document.getElementById("repo-rows");

const STATE_LABELS = {
  ready: "ready", rebuilding: "rebuilding…", none: "not indexed",
  incomplete: "last rebuild failed: index may be incomplete",
};

function cell(row, text, cls) {
  const td = document.createElement("td");
  if (cls) td.className = cls;
  td.textContent = text;
  row.append(td);
  return td;
}

async function loadRepos() {
  let data;
  try {
    data = await (await fetch("/api/repos")).json();
  } catch {
    return;  // the list is a convenience; connecting still works without it
  }
  if (!data.ok) return;
  repoRows.replaceChildren();
  data.repos.forEach((r) => {
    const tr = document.createElement("tr");
    cell(tr, r.slug, "repo");
    cell(tr, r.tracked_branch);
    cell(tr, r.indexed ? `${r.indexed.branch} @ ${r.indexed.commit_sha.slice(0, 7)}` : "—");
    const state = cell(tr, STATE_LABELS[r.index_state] || r.index_state);
    if (r.last_run && r.last_run.state === "failed" && r.last_run.error) state.title = r.last_run.error;
    if (r.needs_rebuild && r.index_state !== "rebuilding") {
      const badge = document.createElement("div");
      badge.className = "badge";
      badge.textContent = "rebuild pending: reconnect";
      state.append(badge);
    }
    repoRows.append(tr);
  });
  reposSection.hidden = data.repos.length === 0;
}

function render(el, kind, text, items = []) {
  el.hidden = false;
  el.className = kind;
  el.textContent = text;
  if (items.length) {
    const ul = document.createElement("ul");
    items.forEach((i) => { const li = document.createElement("li"); li.textContent = i; ul.append(li); });
    el.append(ul);
  }
}

const show = (kind, text, items) => render(result, kind, text, items);

function describeIngestion(s) {
  const skipped = (s.files_skipped || []).map((f) => `skipped ${f.path}: ${f.reason}`);
  const extras = [...skipped, ...(s.warnings || [])];
  if (s.state === "failed") return ["error", `Ingestion failed: ${s.error}`, extras];
  if (s.state === "done") {
    return ["ok", `Ingestion done: ${s.files_loaded} files, ${s.chunks_stored} chunks stored.`, extras];
  }
  const detail = s.state === "running" ? `${s.chunks_stored}/${s.chunks_total} chunks` : "queued";
  return ["", `Ingesting project-data… ${detail}`, extras];
}

async function pollIngestion({ slug }) {
  for (;;) {
    let s;
    try {
      s = await (await fetch(`/api/ingestion-status/${encodeURIComponent(slug)}`)).json();
    } catch {
      render(ingestion, "error", "Lost contact with the server while ingesting.");
      return;
    }
    if (!s.ok) { render(ingestion, "error", s.error); return; }
    render(ingestion, ...describeIngestion(s));
    if (s.state === "done" || s.state === "failed") { loadRepos(); return; }
    await new Promise((r) => setTimeout(r, 1500));
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  submit.disabled = true;
  ingestion.hidden = true;
  show("", "Checking repository…");
  try {
    const res = await fetch("/api/validate-and-clone", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: form.url.value, token: form.token.value, branch: form.branch.value }),
    });
    const data = await res.json();
    if (data.ok) {
      form.token.value = "";  // the PAT is not kept in the page once the server has it
      const note = data.token_saved ? " Token saved for this repository." : data.token_reused ? " Used the saved token." : "";
      show("ok", `${data.message} (${data.branch}) → ${data.path}.${note}`);
      loadRepos();
      await pollIngestion(data.ingestion);
    } else if (data.missing) {
      if (data.token_saved) form.token.value = "";  // the server has it now; leave the field blank to reuse it
      show("error", "Missing required items:" + (data.token_saved ? " (token saved for this repository)" : ""), data.missing);
    } else {
      show("error", data.error);
      loadRepos();  // a failed clone is recorded as a failed run
    }
  } catch {
    show("error", "Could not reach the server.");
  } finally {
    submit.disabled = false;
  }
});

loadRepos();
