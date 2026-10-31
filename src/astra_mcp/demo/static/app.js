const docCell = document.getElementById("doc");
const codeCell = document.getElementById("code");
const sessionCell = document.getElementById("session");
const restart = document.getElementById("restart");
const toolsBox = document.getElementById("tools");
const toolCount = document.getElementById("tool-count");
const toolsNote = document.getElementById("tools-note");

// Named from the tool list, so the page does not keep its own copy of which plane owns what.
const CODE_TOOLS = ["find_symbol", "find_callers", "analyze_impact", "trace_flow", "code_index_status"];

function dot(el, up, text) {
  el.replaceChildren();
  const mark = document.createElement("span");
  mark.className = `dot ${up ? "up" : "down"}`;
  el.append(mark, document.createTextNode(text));
}

async function getJSON(url, options) {
  const reply = await fetch(url, options);
  return reply.json();
}

async function loadStatus() {
  let data;
  try {
    data = await getJSON("/api/status");
  } catch {
    dot(docCell, false, "the demo server is not answering");
    return;
  }
  dot(docCell, data.document.ok, data.document.detail);
  dot(codeCell, data.code.ok, data.code.detail);
  const s = data.session;
  const name = s.server && s.server.name ? `${s.server.name} ${s.server.version || ""}`.trim() : "";
  dot(sessionCell, s.running, s.running ? `connected to ${name}` : (s.error || "not started"));
}

function schemaBlock(tool) {
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "Input schema";
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(tool.inputSchema || {}, null, 2);
  details.append(summary, pre);
  return details;
}

function toolCard(tool) {
  const box = document.createElement("div");
  box.className = "tool";
  const plane = document.createElement("span");
  plane.className = "plane";
  plane.textContent = CODE_TOOLS.includes(tool.name) ? "code" : "documents";
  const title = document.createElement("h3");
  title.textContent = tool.name;
  const description = document.createElement("p");
  description.textContent = tool.description || "";
  box.append(plane, title, description, schemaBlock(tool));
  return box;
}

async function loadTools() {
  toolsNote.hidden = true;
  let data;
  try {
    data = await getJSON("/api/tools");
  } catch {
    return;
  }
  toolsBox.replaceChildren();
  if (!data.ok) {
    toolsNote.hidden = false;
    toolsNote.textContent = data.error;
    toolCount.textContent = "";
    fillRunner([]);
    return;
  }
  const tools = data.tools || [];
  toolCount.textContent = `— ${tools.length} offered over one connection`;
  tools.forEach((t) => toolsBox.append(toolCard(t)));
  fillRunner(tools);
  // A plane that is down means fewer tools, not an error: say so rather than leaving a short list.
  if (!tools.some((t) => CODE_TOOLS.includes(t.name))) {
    toolsNote.hidden = false;
    toolsNote.textContent = "No code tools — the code plane is not answering.";
  } else if (tools.every((t) => CODE_TOOLS.includes(t.name))) {
    toolsNote.hidden = false;
    toolsNote.textContent = "No document tools — the document plane is not answering.";
  }
}

restart.addEventListener("click", async () => {
  restart.disabled = true;
  try {
    await getJSON("/api/session/restart", { method: "POST" });
    await Promise.all([loadStatus(), loadTools()]);
  } finally {
    restart.disabled = false;
  }
});

// Tools first: asking for them is what starts the session, so the status line is then accurate
// rather than reporting "not started" for the first few seconds.
(async () => {
  await loadTools();
  await loadStatus();
})();
setInterval(loadStatus, 10000);
