// Running one tool: a form built from its schema, then the answer in two parts.
// Loaded after app.js, which owns the status line, the tool list and getJSON.

const runSection = document.getElementById("run-section");
const toolPick = document.getElementById("tool-pick");
const toolAbout = document.getElementById("tool-about");
const fieldsBox = document.getElementById("fields");
const runButton = document.getElementById("run");
const answerBox = document.getElementById("answer");

let known = [];    // the tools as listed
let readers = [];  // one per field: () => [name, value], value undefined to omit

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function control(spec) {
  if (Array.isArray(spec.enum)) {
    const select = el("select");
    select.append(el("option", ""));
    spec.enum.forEach((v) => select.append(el("option", String(v))));
    return [select, () => select.value || undefined];
  }
  if (spec.type === "boolean") {
    const box = el("input");
    box.type = "checkbox";
    if (spec.default) box.checked = true;
    return [box, () => box.checked];
  }
  if (spec.type === "integer" || spec.type === "number") {
    const input = el("input");
    input.type = "number";
    if (spec.minimum !== undefined) input.min = spec.minimum;
    if (spec.maximum !== undefined) input.max = spec.maximum;
    if (spec.default !== undefined) input.placeholder = "default " + spec.default;
    return [input, () => (input.value === "" ? undefined : Number(input.value))];
  }
  if (spec.type === "array") {
    const input = el("input");
    input.type = "text";
    input.placeholder = "separate with commas";
    return [input, () => {
      const parts = input.value.split(",").map((s) => s.trim()).filter(Boolean);
      return parts.length ? parts : undefined;
    }];
  }
  const long = (spec.maxLength || 0) > 200;
  const input = el(long ? "textarea" : "input");
  if (!long) input.type = "text";
  return [input, () => input.value.trim() || undefined];
}

function buildForm(tool) {
  fieldsBox.replaceChildren();
  readers = [];
  const schema = tool.inputSchema || {};
  const required = schema.required || [];
  const properties = schema.properties || {};
  const names = Object.keys(properties);
  if (names.length === 0) {
    fieldsBox.append(el("p", "This tool takes no arguments.", "hint"));
    return;
  }
  // Required first: it is the order someone filling the form in wants them.
  names.sort((a, b) => (required.includes(b) ? 1 : 0) - (required.includes(a) ? 1 : 0));
  names.forEach((name) => {
    const spec = properties[name] || {};
    const label = el("label");
    label.append(document.createTextNode(name));
    if (required.includes(name)) label.append(el("span", " *", "req"));
    const [input, read] = control(spec);
    label.append(input);
    if (spec.description) label.append(el("span", spec.description, "about"));
    fieldsBox.append(label);
    readers.push(() => [name, read()]);
  });
}

function chosen() {
  return known.find((t) => t.name === toolPick.value);
}

function showTool() {
  const tool = chosen();
  if (!tool) return;
  toolAbout.textContent = tool.description || "";
  buildForm(tool);
  answerBox.hidden = true;
}

// Called by app.js once the tool list is in.
function fillRunner(tools) {
  known = tools;
  runSection.hidden = tools.length === 0;
  const previous = toolPick.value;
  toolPick.replaceChildren();
  tools.forEach((t) => toolPick.append(el("option", t.name)));
  if (tools.some((t) => t.name === previous)) toolPick.value = previous;
  showTool();
}

function args() {
  const out = {};
  readers.forEach((read) => {
    const [name, value] = read();
    if (value !== undefined) out[name] = value;
  });
  return out;
}

// ---- the answer -----------------------------------------------------

function where(hit) {
  const p = hit.provenance || {};
  const lines = p.line_start ? ":" + p.line_start + (p.line_end ? "-" + p.line_end : "") : "";
  return (p.file_path || hit.file || "?") + lines;
}

function hitBox(title, meta) {
  const box = el("div", undefined, "hit");
  box.append(el("div", title, "where"));
  if (meta) box.append(el("div", meta, "meta"));
  return box;
}

function sourceLink(url) {
  if (!url) return null;
  const link = el("a", "source", "meta");
  link.href = url;
  link.target = "_blank";
  link.rel = "noreferrer";
  return link;
}

function renderCode(payload, into) {
  const results = payload.results || [];
  const flow = payload.flow || [];
  if (flow.length) {
    into.append(el("h3", "Path"));
    flow.forEach((hop) => into.append(hitBox(hop.from + " → " + hop.to, hop.via ? "via " + hop.via : "")));
  }
  if (!results.length && !flow.length) {
    into.append(el("p", "No results.", "none"));
    return;
  }
  if (results.length) into.append(el("h3", "Results (" + results.length + ")"));
  results.forEach((hit) => {
    const p = hit.provenance || {};
    const meta = [hit.kind, hit.relation, hit.depth ? "depth " + hit.depth : ""].filter(Boolean).join(" · ");
    const box = hitBox(((p.qualified_name || p.symbol || "") + "  " + where(hit)).trim(), meta);
    if (hit.text) box.append(el("pre", hit.text));
    into.append(box);
  });
}

function renderStatus(payload, into) {
  const facts = el("dl", undefined, "facts");
  const snapshot = payload.snapshot || {};
  const rows = [
    ["state", payload.state], ["files", payload.files], ["symbols", payload.symbols],
    ["edges", payload.edges], ["indexed commit", snapshot.commit_sha],
    ["behind by (s)", payload.index_lag_seconds], ["active job", payload.active_job],
    ["error", payload.error],
  ];
  rows.forEach(([name, value]) => {
    if (value === undefined || value === null) return;
    facts.append(el("dt", name), el("dd", String(value)));
  });
  into.append(facts);
}

function renderDocument(payload, into) {
  const data = payload.data || payload;
  const rules = data.rules || [];
  const template = data.template;
  const items = (data.knowledge && data.knowledge.items) || data.items || [];

  if (rules.length) {
    into.append(el("h3", "Rules (" + rules.length + ")"));
    rules.forEach((rule) => {
      const box = hitBox(rule.section || rule.file, [rule.file, rule.matched_on].filter(Boolean).join(" · "));
      box.append(el("p", rule.text || "", "body"));
      const link = sourceLink(rule.source_url);
      if (link) box.append(link);
      into.append(box);
    });
  }
  if (template) {
    const meta = [template.variant, template.truncated ? "truncated" : ""].filter(Boolean).join(" · ");
    into.append(el("h3", "Template"));
    const box = hitBox(template.path || "", meta);
    box.append(el("p", template.text || "", "body"));
    const link = sourceLink(template.source_url);
    if (link) box.append(link);
    into.append(box);
  }
  if (items.length) {
    into.append(el("h3", "Evidence (" + items.length + ")"));
    items.forEach((item) => {
      const meta = [(item.heading_path || []).join(" > "), item.doc_type, item.doc_date]
        .filter(Boolean).join(" · ");
      const box = hitBox(item.file || "", meta);
      box.append(el("p", item.text || "", "body"));
      const link = sourceLink(item.source_url);
      if (link) box.append(link);
      into.append(box);
    });
  }
  if (!rules.length && !template && !items.length) into.append(el("p", "Nothing came back.", "none"));
}

function renderAnswer(data) {
  answerBox.replaceChildren();
  answerBox.className = "answer";
  answerBox.hidden = false;

  if (!data.ok) {
    answerBox.append(el("div", data.error, "error"));
    return;
  }
  // The note first, exactly as the server puts it in front of the payload.
  if (data.note) answerBox.append(el("div", data.note, "note"));
  if (data.is_error) {
    answerBox.append(el("div", data.text || "The call was refused.", "error"));
    return;
  }
  const payload = data.payload;
  if (payload === null) {
    answerBox.append(el("pre", data.text));
  } else if (data.kind === "code") {
    renderCode(payload, answerBox);
  } else if (data.kind === "status") {
    renderStatus(payload, answerBox);
  } else {
    renderDocument(payload, answerBox);
  }
  const raw = el("details");
  raw.append(el("summary", "Raw JSON"), el("pre", JSON.stringify(payload === null ? data.text : payload, null, 2)));
  answerBox.append(raw);
}

toolPick.addEventListener("change", showTool);

runButton.addEventListener("click", async () => {
  const tool = chosen();
  if (!tool) return;
  runButton.disabled = true;
  runButton.textContent = "Running…";
  try {
    renderAnswer(await getJSON("/api/call", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: tool.name, arguments: args() }),
    }));
  } catch {
    renderAnswer({ ok: false, error: "The demo server is not answering." });
  } finally {
    runButton.disabled = false;
    runButton.textContent = "Run";
  }
});
