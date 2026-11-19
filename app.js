// Smart Campus front end: plain JavaScript that talks only to the REST API under /api.
const state = { token: sessionStorage.getItem("campusToken") || "", me: null, facilities: [], tickets: [], bookingKey: null, ticketKey: null };
const $ = (sel) => document.querySelector(sel);

function say(text, kind = "") {
  const el = $("#message");
  el.textContent = text;
  el.className = "message " + kind;
}

async function api(method, path, body, key) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  if (key) headers["Idempotency-Key"] = key;
  let response;
  try {
    response = await fetch("/api" + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch (err) {
    // Network failure: the request may or may not have been applied, so the caller keeps its Idempotency-Key.
    throw Object.assign(new Error("Network error: the request may or may not have been applied. Submit again to retry safely."), { network: true });
  }
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const err = data && data.error ? data.error : { code: "HTTP_" + response.status, message: response.statusText };
    throw Object.assign(new Error(`${err.code}: ${err.message}`), { status: response.status, code: err.code });
  }
  return { status: response.status, data, replayed: response.headers.get("Idempotent-Replayed") === "true", served: response.headers.get("X-Served-By") };
}

function newKey() {
  return (crypto.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(16).slice(2)).replace(/-/g, "").slice(0, 32);
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmt(iso) {
  return iso ? new Date(iso).toLocaleString() : "";
}

function isManager() { return state.me && ["admin", "facility_manager"].includes(state.me.role); }

async function signIn(token) {
  state.token = token.trim();
  sessionStorage.setItem("campusToken", state.token);
  try {
    const { data } = await api("GET", "/me");
    state.me = data;
    $("#who").textContent = `${data.full_name} (${data.role})`;
    document.querySelectorAll(".manager-only").forEach((el) => el.classList.toggle("hidden", !isManager()));
    await loadFacilities();
    await Promise.all([loadDashboard(), loadBookings(), loadTickets()]);
    say("Signed in.", "ok");
  } catch (err) {
    state.me = null;
    $("#who").textContent = "Not signed in";
    say(err.message, "err");
  }
}

// ---------- Tabs ----------
document.querySelectorAll("#tabs button").forEach((btn) => btn.addEventListener("click", () => {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b === btn));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + btn.dataset.tab));
  if (btn.dataset.tab === "audit") loadAudit();
  if (btn.dataset.tab === "dashboard") loadDashboard();
}));

$("#login-btn").addEventListener("click", () => signIn($("#token").value));
$("#demo-user").addEventListener("change", (e) => { $("#token").value = e.target.value; if (e.target.value) signIn(e.target.value); });

// ---------- Dashboard ----------
async function loadDashboard() {
  if (!state.token) return;
  try {
    const { data } = await api("GET", "/dashboard");
    const tk = data.tickets_by_status || {};
    const bk = data.bookings_by_status || {};
    const openTickets = Object.entries(tk).filter(([s]) => s !== "CLOSED").reduce((a, [, n]) => a + n, 0);
    $("#cards").innerHTML = [
      ["Open tickets", openTickets, false],
      ["Open tickets past SLA", data.open_tickets_past_sla, data.open_tickets_past_sla > 0],
      ["Bookings awaiting approval", bk.REQUESTED || 0, false],
      ["Confirmed bookings", bk.CONFIRMED || 0, false],
    ].map(([label, n, alert]) => `<div class="card ${alert ? "alert" : ""}"><div class="muted">${label}</div><div class="n">${n}</div></div>`).join("");
    $("#dash-bookings").innerHTML = table(["Status", "Count"], Object.entries(bk));
    $("#dash-tickets").innerHTML = table(["Status", "Count"], Object.entries(tk));
    $("#dash-meta").textContent = `Served by ${data.instance} at ${fmt(data.generated_at)}`;
  } catch (err) { say(err.message, "err"); }
}

function table(headers, rows) {
  return `<table><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${
    rows.length ? rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${headers.length}" class="muted">No records</td></tr>`
  }</tbody></table>`;
}

// ---------- Facilities ----------
async function loadFacilities() {
  const { data } = await api("GET", "/facilities");
  state.facilities = data.items;
  $("#facility-table tbody").innerHTML = data.items.map((f) => `
    <tr><td>${esc(f.code)}</td><td>${esc(f.name)}</td><td>${esc(f.location)}</td><td>${f.capacity}</td>
    <td>${f.restricted ? "Approval required" : "Automatic"}</td>
    <td><button class="secondary" data-cal="${f.id}" data-code="${esc(f.code)}">Calendar</button></td></tr>`).join("");
  const options = data.items.map((f) => `<option value="${f.id}">${esc(f.code)} - ${esc(f.name)}</option>`).join("");
  $("#bk-facility").innerHTML = options;
  $("#tk-facility").innerHTML = `<option value="">Not specified</option>` + options;
  if (!$("#cal-date").value) $("#cal-date").value = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
}

$("#facility-table").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-cal]");
  if (btn) { $("#cal-facility").textContent = btn.dataset.code; loadCalendar(btn.dataset.cal); }
});
$("#cal-date").addEventListener("change", () => {
  if (state.calFacility) loadCalendar(state.calFacility);
});

async function loadCalendar(facilityId) {
  state.calFacility = facilityId;
  const date = $("#cal-date").value;
  try {
    const { data } = await api("GET", `/facilities/${facilityId}/calendar?date=${date}`);
    $("#calendar").innerHTML = table(["Start (UTC)", "End (UTC)", "Status", "Purpose", "Requester"],
      data.items.map((b) => [fmt(b.start_time), fmt(b.end_time), b.status, b.purpose, b.requester_username]));
  } catch (err) { say(err.message, "err"); }
}

// ---------- Booking form ----------
$("#booking-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.bookingKey) state.bookingKey = newKey();   // the same key is reused on retry
  const body = {
    facility_id: Number($("#bk-facility").value),
    start_time: new Date($("#bk-start").value).toISOString(),
    end_time: new Date($("#bk-end").value).toISOString(),
    purpose: $("#bk-purpose").value,
    attendees: Number($("#bk-attendees").value),
  };
  try {
    const { status, data, replayed } = await api("POST", "/bookings", body, state.bookingKey);
    state.bookingKey = null;
    $("#bk-key-note").textContent = "";
    say(`Booking ${data.id} ${status === 201 ? "created" : "returned"} with status ${data.status}${replayed ? " (replayed: this was a retry)" : ""}.`, "ok");
    await Promise.all([loadBookings(), loadDashboard()]);
  } catch (err) {
    if (err.network || err.code === "IDEMPOTENT_REQUEST_IN_PROGRESS") {
      $("#bk-key-note").textContent = "Submit again: the same key is kept, so the booking will not be duplicated.";
    } else {
      state.bookingKey = null;
    }
    say(err.message, "err");
  }
});

// ---------- Bookings and approvals ----------
async function loadBookings() {
  if (!state.token) return;
  const filter = $("#bk-filter").value;
  try {
    const { data } = await api("GET", "/bookings" + (filter ? `?status=${filter}` : ""));
    $("#booking-table tbody").innerHTML = data.items.map((b) => `
      <tr><td>${b.id}</td><td>${esc(b.facility_code)}</td><td>${esc(b.requester_username)}</td>
      <td>${fmt(b.start_time)}</td><td>${fmt(b.end_time)}</td><td><span class="pill">${esc(b.status)}</span></td><td>${b.version}</td>
      <td>${bookingActions(b)}</td></tr>`).join("") || `<tr><td colspan="8" class="muted">No bookings</td></tr>`;
  } catch (err) { say(err.message, "err"); }
}

// Buttons are offered for every action the state allows; the server still decides who may press them.
function bookingActions(b) {
  const map = {
    REQUESTED: ["approve", "reject", "cancel"],
    APPROVED: ["confirm", "cancel"],
    CONFIRMED: ["start", "cancel"],
    IN_USE: ["complete"],
  };
  return (map[b.status] || []).map((a) => `<button class="secondary small" data-bk="${b.id}" data-version="${b.version}" data-action="${a}">${a}</button>`).join(" ");
}

$("#booking-table").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-bk]");
  if (!btn) return;
  const key = newKey();
  try {
    const { data } = await api("POST", `/bookings/${btn.dataset.bk}/transition`,
      { action: btn.dataset.action, version: Number(btn.dataset.version) }, key);
    say(`Booking ${data.id} is now ${data.status}.`, "ok");
  } catch (err) { say(err.message, "err"); }
  await Promise.all([loadBookings(), loadDashboard()]);
});
$("#bk-refresh").addEventListener("click", loadBookings);
$("#bk-filter").addEventListener("change", loadBookings);

// ---------- Tickets ----------
$("#ticket-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.ticketKey) state.ticketKey = newKey();
  const body = { title: $("#tk-title").value, description: $("#tk-desc").value };
  if ($("#tk-facility").value) body.facility_id = Number($("#tk-facility").value);
  if ($("#tk-priority").value && isManager()) body.priority = $("#tk-priority").value;
  try {
    const { data, replayed } = await api("POST", "/tickets", body, state.ticketKey);
    state.ticketKey = null;
    $("#tk-key-note").textContent = "";
    say(`Ticket ${data.id} created: ${data.category}, ${data.priority}. Triage: ${data.triage_rules.join("; ")}${replayed ? " (replayed)" : ""}`, "ok");
    e.target.reset();
    await Promise.all([loadTickets(), loadDashboard()]);
  } catch (err) {
    if (err.network) $("#tk-key-note").textContent = "Submit again: the same key is kept.";
    else state.ticketKey = null;
    say(err.message, "err");
  }
});

async function loadTickets() {
  if (!state.token) return;
  const filter = $("#tk-filter").value;
  try {
    const { data } = await api("GET", "/tickets" + (filter ? `?status=${filter}` : ""));
    state.tickets = data.items;
    $("#ticket-table tbody").innerHTML = data.items.map((t) => `
      <tr data-id="${t.id}" class="clickable"><td>${t.id}</td><td>${esc(t.title)}</td><td>${esc(t.facility_code || "")}</td>
      <td>${esc(t.category)}</td><td>${esc(t.priority)}</td><td><span class="pill">${esc(t.status)}</span></td>
      <td>${esc(t.assignee_username || "unassigned")}</td><td>${fmt(t.sla_due_at)}${t.sla_breached ? " (breached)" : ""}</td></tr>`).join("")
      || `<tr><td colspan="8" class="muted">No tickets</td></tr>`;
  } catch (err) { say(err.message, "err"); }
}

$("#ticket-table").addEventListener("click", async (e) => {
  const row = e.target.closest("tr[data-id]");
  if (row) await showTicket(row.dataset.id);
});
$("#tk-refresh")?.addEventListener("click", loadTickets);
$("#tk-filter").addEventListener("change", loadTickets);

async function showTicket(id) {
  try {
    const { data: t } = await api("GET", `/tickets/${id}`);
    let techs = [];
    if (isManager()) techs = (await api("GET", "/users?role=technician")).data.items;
    const assignSelect = isManager()
      ? `<select id="assign-to">${techs.map((u) => `<option value="${u.id}" ${u.id === t.assignee_id ? "selected" : ""}>${esc(u.username)}</option>`).join("")}</select>`
      : "";
    const actions = [];
    if (["INTAKE", "ASSIGNED"].includes(t.status) && isManager()) actions.push(`<button data-tk-act="assign">Assign</button>`);
    if (t.status === "ASSIGNED") actions.push(`<button data-tk-act="start_inspection">Start inspection</button>`);
    if (t.status === "INSPECTION") actions.push(`<button data-tk-act="pending_work">Mark pending work</button>`, `<button data-tk-act="resolve">Resolve</button>`);
    if (t.status === "PENDING_WORK") actions.push(`<button data-tk-act="resolve">Resolve</button>`);
    if (t.status === "RESOLVED" && isManager()) actions.push(`<button data-tk-act="close">Close (authorise)</button>`, `<button data-tk-act="reopen" class="secondary">Reopen</button>`);
    if (isManager() && t.status !== "CLOSED") actions.push(`<button class="secondary" data-tk-prio="${t.priority}">Change priority</button>`);
    actions.push(`<button class="secondary" data-tk-link="1">Link DevOps issue</button>`);
    $("#ticket-detail").innerHTML = `
      <h3>Ticket ${t.id}: ${esc(t.title)}</h3>
      <p>${esc(t.description)}</p>
      <p class="small muted">Source ${esc(t.source)} | Category ${esc(t.category)} | Priority ${esc(t.priority)} | Status ${esc(t.status)} | Version ${t.version}</p>
      <p class="small muted">Triage rules: ${esc(t.triage_rules.join("; "))}</p>
      <p class="small">Inspection notes: ${esc(t.inspection_notes || "none")}<br>Resolution notes: ${esc(t.resolution_notes || "none")}</p>
      <div class="row">${assignSelect}</div>
      <div class="row"><label>Notes <input id="tk-notes" type="text" maxlength="2000"></label></div>
      <div class="row">${actions.join(" ")}</div>
      <div id="links"></div>`;
    $("#ticket-detail").dataset.ticket = JSON.stringify({ id: t.id, version: t.version });
    await loadLinks(t.id);
  } catch (err) { say(err.message, "err"); }
}

$("#ticket-detail").addEventListener("click", async (e) => {
  const info = JSON.parse($("#ticket-detail").dataset.ticket || "{}");
  if (!info.id) return;
  const btn = e.target.closest("button");
  if (!btn) return;
  try {
    if (btn.dataset.tkAct) {
      const body = { action: btn.dataset.tkAct, version: info.version, notes: $("#tk-notes").value || undefined };
      if (btn.dataset.tkAct === "assign") body.assignee_id = Number($("#assign-to").value);
      const { data } = await api("POST", `/tickets/${info.id}/transition`, body, newKey());
      say(`Ticket ${data.id} is now ${data.status}.`, "ok");
    } else if (btn.dataset.tkPrio !== undefined) {
      const priority = prompt("New priority: CRITICAL, HIGH, MEDIUM or LOW", btn.dataset.tkPrio);
      if (!priority) return;
      const { data } = await api("PATCH", `/tickets/${info.id}`, { priority, version: info.version });
      say(`Priority changed to ${data.priority}.`, "ok");
    } else if (btn.dataset.tkLink) {
      const title = prompt("Title for the linked DevOps issue", "Follow-up: " + info.id);
      if (!title) return;
      const { data } = await api("POST", `/tickets/${info.id}/links`, { provider: "devops-issue", title }, newKey());
      say(`Link ${data.id} status ${data.status} (mode ${data.mode}).`, data.status === "SYNCED" ? "ok" : "err");
    }
    await Promise.all([loadTickets(), loadDashboard()]);
    await showTicket(info.id);
  } catch (err) {
    say(err.message, "err");
    if (err.status === 409) await showTicket(info.id);
  }
});

async function loadLinks(ticketId) {
  try {
    const { data } = await api("GET", `/tickets/${ticketId}/links`);
    const rows = data.items.map((l) => `
      <tr><td>${l.id}</td><td>${esc(l.title)}</td><td>${esc(l.external_ref || "none yet")}</td>
      <td>${esc(l.mode)}</td><td><span class="pill">${esc(l.status)}</span></td><td>${l.attempts}</td>
      <td class="small">${esc(l.last_error || "")}</td>
      <td>${l.status === "PENDING" ? `<button class="secondary small" data-retry="${l.id}">Retry</button>` : ""}</td></tr>`).join("");
    $("#links").innerHTML = data.items.length
      ? `<h3>Linked integration records</h3>` + `<table><thead><tr><th>ID</th><th>Title</th><th>External ref</th><th>Mode</th><th>Status</th><th>Attempts</th><th>Last error</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
      : `<p class="small muted">No linked integration records.</p>`;
  } catch (err) { say(err.message, "err"); }
}

$("#links").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-retry]");
  if (!btn) return;
  try {
    const { data } = await api("POST", `/integrations/${btn.dataset.retry}/retry`, {}, newKey());
    say(`Link ${data.id} is now ${data.status}.`, data.status === "SYNCED" ? "ok" : "err");
  } catch (err) { say(err.message, "err"); }
  const info = JSON.parse($("#ticket-detail").dataset.ticket || "{}");
  if (info.id) await loadLinks(info.id);
});

// ---------- Audit ----------
async function loadAudit() {
  if (!state.token) return;
  try {
    const { data } = await api("GET", "/audit");
    $("#audit-table tbody").innerHTML = data.items.map((a) => `
      <tr><td>${a.id}</td><td>${fmt(a.created_at)}</td><td>${esc(a.entity_type)} ${a.entity_id}</td>
      <td>${esc(a.action)}</td><td>${esc(a.actor_username || "")}</td><td class="small">${esc(JSON.stringify(a.detail))}</td></tr>`).join("");
  } catch (err) { say(err.message, "err"); }
}

// Initial state
if (state.token) { $("#token").value = state.token; signIn(state.token); }
