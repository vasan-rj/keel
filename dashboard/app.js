const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

let eventsList = [];
let hasMoreEvents = false;

function restore() {
  $("url").value = localStorage.getItem("keel_url") || "http://localhost:8000";
  $("token").value = localStorage.getItem("keel_token") || "";
}

function base() { return ($("url").value || "").replace(/\/$/, ""); }

async function api(path) {
  const r = await fetch(base() + path, {
    headers: { "Authorization": "Bearer " + $("token").value, "X-Keel-Session": "dashboard" },
  });
  if (!r.ok) throw new Error(r.status === 401 ? "unauthorized (check token)" : "HTTP " + r.status);
  return r.json();
}

function rows(el, items, fn) {
  el.innerHTML = items.length ? items.map((x) => `<div class="row">${fn(x)}</div>`).join("")
                             : `<div class="row mut">none</div>`;
}

function renderEvents() {
  rows($("events"), eventsList, (e) =>
    `<span class="mut">${esc(e.created_at || "")}</span> <code>${esc(e.action)}</code> `
    + `<span class="mut">by ${esc(e.actor)}</span>`);

  const moreBtn = $("events-more");
  if (!moreBtn) return;
  if (!eventsList.length || !hasMoreEvents) {
    moreBtn.style.display = "none";
  } else {
    moreBtn.style.display = "inline-block";
    moreBtn.disabled = false;
    moreBtn.textContent = "Load more";
  }
}

function mergeEvents(incoming) {
  const map = new Map();
  for (const e of eventsList) map.set(e.id, e);
  for (const e of incoming) map.set(e.id, e);
  eventsList = Array.from(map.values()).sort((a, b) => b.id - a.id);
}

async function loadMore() {
  const moreBtn = $("events-more");
  if (!eventsList.length || !moreBtn) return;
  const oldestId = eventsList[eventsList.length - 1].id;
  moreBtn.disabled = true;
  moreBtn.textContent = "Loading...";
  try {
    const data = await api(`/api/events?limit=100&before_id=${oldestId}`);
    const items = data.events || [];
    if (!items.length) {
      hasMoreEvents = false;
      moreBtn.textContent = "No more events";
      moreBtn.disabled = true;
      return;
    }
    mergeEvents(items);
    if (items.length < 100 || data.next_cursor === null) {
      hasMoreEvents = false;
      moreBtn.textContent = "No more events";
      moreBtn.disabled = true;
    } else {
      hasMoreEvents = true;
      moreBtn.textContent = "Load more";
      moreBtn.disabled = false;
    }
    renderEvents();
  } catch (err) {
    moreBtn.disabled = false;
    moreBtn.textContent = "Load more";
    $("msg").textContent = "error loading more: " + err.message;
  }
}

async function post(path) {
  const r = await fetch(base() + path, {
    method: "POST",
    headers: { "Authorization": "Bearer " + $("token").value, "X-Keel-Session": "dashboard" },
  });
  if (!r.ok) throw new Error(r.status === 401 ? "unauthorized (check token)" : "HTTP " + r.status);
  return r.json();
}

async function renderTokens() {
  const el = $("tokens");
  if (!el) return;
  try {
    const data = await api("/api/tokens");
    rows(el, data.tokens || [], (t) =>
      `<span class="pill">${esc(t.kind)}/${esc(t.scope)}</span> ${esc(t.label || "")} `
      + (t.revoked_at ? `<span class="mut">revoked</span>`
                      : `<button data-revoke="${esc(t.id)}" style="padding:2px 8px;">revoke</button>`));
  } catch (err) {
    el.innerHTML = `<div class="row mut">${esc(err.message)}</div>`;
  }
}

async function refresh(reset = false) {
  try {
    localStorage.setItem("keel_url", $("url").value);
    localStorage.setItem("keel_token", $("token").value);
    const state = await api("/api/state");
    const ev = await api("/api/events?limit=100");
    rows($("decisions"), state.active_decisions, (d) =>
      `${esc(d.statement)} <span class="tag">[${esc((d.scope_tags || []).join(", "))}]</span>`);
    rows($("conflicts"), state.open_conflicts, (c) =>
      `<span class="pill">${esc(c.severity)}/${esc(c.relation)}</span> ${esc(c.explanation)}`);
    rows($("alerts"), state.pending_alerts, (a) =>
      `<span class="pill">${esc(a.kind)}</span> ${esc(a.ref_id)}`);
    rows($("handoffs"), state.pending_handoffs, (h) =>
      `→ ${esc(h.note || "")} <span class="tag">[${esc((h.scope_tags || []).join(", "))}]</span>`);

    if (reset || eventsList.length === 0) {
      eventsList = ev.events || [];
      hasMoreEvents = Boolean(ev.events && ev.events.length >= 100);
    } else {
      mergeEvents(ev.events || []);
    }
    renderEvents();
    await renderTokens();
    $("msg").textContent = "updated " + new Date().toLocaleTimeString();
  } catch (err) {
    $("msg").textContent = "error: " + err.message;
  }
}

let timer = null;
$("go").onclick = () => {
  eventsList = [];
  refresh(true);
};
if ($("events-more")) $("events-more").onclick = loadMore;

if ($("tokens")) $("tokens").addEventListener("click", async (e) => {
  const id = e.target && e.target.getAttribute && e.target.getAttribute("data-revoke");
  if (!id) return;
  e.target.disabled = true;
  try {
    await post(`/api/tokens/${id}/revoke`);
    await renderTokens();
  } catch (err) {
    $("msg").textContent = "revoke failed: " + err.message;
    e.target.disabled = false;
  }
});

$("auto").onchange = (e) => {
  clearInterval(timer);
  if (e.target.checked) timer = setInterval(refresh, 5000);
};

restore();
if ($("token").value) refresh(true);
