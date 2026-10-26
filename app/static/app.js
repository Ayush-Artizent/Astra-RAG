const form = document.getElementById("form");
const submit = document.getElementById("submit");
const result = document.getElementById("result");

function show(kind, text, items = []) {
  result.hidden = false;
  result.className = kind;
  result.textContent = text;
  if (items.length) {
    const ul = document.createElement("ul");
    items.forEach((i) => { const li = document.createElement("li"); li.textContent = i; ul.append(li); });
    result.append(ul);
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  submit.disabled = true;
  show("", "Checking repository…");
  try {
    const res = await fetch("/api/validate-and-clone", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: form.url.value, token: form.token.value }),
    });
    const data = await res.json();
    if (data.ok) show("ok", `${data.message} → ${data.path}`);
    else if (data.missing) show("error", "Missing required items:", data.missing);
    else show("error", data.error);
  } catch {
    show("error", "Could not reach the server.");
  } finally {
    submit.disabled = false;
  }
});
