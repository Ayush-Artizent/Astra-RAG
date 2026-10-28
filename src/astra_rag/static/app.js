const form = document.getElementById("form");
const submit = document.getElementById("submit");
const result = document.getElementById("result");
const ingestion = document.getElementById("ingestion");
const reposSection = document.getElementById("repos");
const repoRows = document.getElementById("repo-rows");
const scheduleLine = document.getElementById("schedule");

const SYNC_LABELS = {
  syncing: "syncing…", queued: "queued", pending: "another sync follows the current one",
  up_to_date: "up to date", out_of_date: "rebuild pending", never_indexed: "not indexed",
  source_error: "cannot reach the repository",
};

const when = (iso) => (iso ? new Date(iso).toLocaleString() : "never");

function sub(td, text) {
  const span = document.createElement("span");
  span.className = "sub";
  span.textContent = text;
  td.append(span);
}

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
    const indexed = cell(tr, r.indexed ? `${r.indexed.branch} @ ${r.indexed.commit_sha.slice(0, 7)}` : "—");
    if (r.indexed) {
      indexed.title = r.indexed.commit_sha;
      sub(indexed, `indexed ${when(r.indexed.at)}`);
    }
    const status = cell(tr, SYNC_LABELS[r.sync_status] || r.sync_status);
    sub(status, `checked ${when(r.sync.last_checked_at)}`);
    if (r.sync.source_error) {
      status.title = r.sync.source_error;
      addBadge(status, r.sync.source_error, "error");
    } else if (r.last_run && r.last_run.state === "failed" && r.last_run.error) {
      status.title = r.last_run.error;
      addBadge(status, "last sync failed; the previous index still serves");
    }
    if (r.index_state === "incomplete") addBadge(status, "index may be incomplete");
    const action = cell(tr, "");
    const button = document.createElement("button");
    button.className = "small";
    button.textContent = "Sync now";
    button.disabled = r.sync_status === "syncing" || r.sync_status === "queued";
    button.addEventListener("click", () => syncNow(r.slug, button));
    action.append(button);
    repoRows.append(tr);
  });
  reposSection.hidden = data.repos.length === 0;
  const s = data.schedule;
  scheduleLine.textContent = s && s.enabled
    ? `Checked automatically every night at ${s.daily_at_utc} UTC (next: ${when(s.next_check_at)}). ` +
      "Changes can take up to a day to appear; use Sync now to pick them up straight away."
    : "Automatic nightly checks are off on this server; use Sync now to pick up changes.";
}

function addBadge(td, text, kind) {
  const badge = document.createElement("div");
  badge.className = kind ? `badge ${kind}` : "badge";
  badge.textContent = text;
  td.append(badge);
}

async function syncNow(slug, button) {
  button.disabled = true;
  try {
    const data = await (await fetch(`/api/repos/${encodeURIComponent(slug)}/sync`, { method: "POST" })).json();
    if (!data.ok) {
      render(ingestion, "error", `Sync failed: ${data.error}`);
    } else if (data.state === "up_to_date") {
      render(ingestion, "ok", `${slug} is up to date (${data.commit_sha.slice(0, 7)}).`);
    } else if (data.state === "pending") {
      render(ingestion, "", `${slug}: a sync is already running; another one will follow it.`);
    } else {
      await pollIngestion({ slug });
    }
  } catch {
    render(ingestion, "error", "Could not reach the server.");
  }
  loadRepos();
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
  if (s.state === "failed") return ["error", `Sync failed: ${s.error} The previous index still serves.`, extras];
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
      show("ok", `${data.message} (${data.branch} @ ${data.commit_sha.slice(0, 7)})${note}`);
      loadRepos();
      if (data.ingestion.state === "queued") await pollIngestion(data.ingestion);
    } else if (data.missing) {
      if (data.token_saved) form.token.value = "";  // the server has it now; leave the field blank to reuse it
      show("error", "Missing required items:" + (data.token_saved ? " (token saved for this repository)" : ""), data.missing);
    } else {
      show("error", data.error);
      loadRepos();
    }
  } catch {
    show("error", "Could not reach the server.");
  } finally {
    submit.disabled = false;
  }
});

loadRepos();
