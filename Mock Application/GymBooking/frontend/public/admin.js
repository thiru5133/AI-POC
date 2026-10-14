// Staff area. Sections: Gyms (with class types and sessions), Bookings, Users (superadmin only).
const state = { user: null, tab: "gyms", gym: null };

// ---------- generic form dialog ----------
// fields: [{ name, label, type?, value?, required?, options?: [[value, label]], help?, placeholder?, min?, max? }]
function openForm({ title, fields, submitLabel = "Save", help = "", onSubmit }) {
  const dialog = $("dialog");
  $("dialogTitle").textContent = title;
  $("dialogHelp").textContent = help;
  $("dialogHelp").hidden = !help;
  $("dialogSubmit").textContent = submitLabel;
  show($("dialogError"), "");
  $("dialogFields").innerHTML = fields
    .map((f) => {
      const id = `f_${f.name}`;
      const common = `id="${id}" name="${esc(f.name)}" ${f.required ? "required" : ""}`;
      let control;
      if (f.options) {
        control = `<select ${common}>${f.options
          .map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(f.value) ? "selected" : ""}>${esc(l)}</option>`)
          .join("")}</select>`;
      } else if (f.type === "checkbox") {
        return `<label class="inline"><input type="checkbox" ${common} ${f.value ? "checked" : ""} /> ${esc(f.label)}</label>`;
      } else {
        control = `<input ${common} type="${f.type || "text"}" value="${esc(f.value ?? "")}" placeholder="${esc(f.placeholder || "")}"
          ${f.min !== undefined ? `min="${f.min}"` : ""} ${f.max !== undefined ? `max="${f.max}"` : ""} autocomplete="off" />`;
      }
      return `<label>${esc(f.label)}${control}${f.help ? `<span class="muted">${esc(f.help)}</span>` : ""}</label>`;
    })
    .join("");
  $("dialogForm").onsubmit = async (event) => {
    event.preventDefault();
    const values = {};
    for (const f of fields) {
      const input = $(`f_${f.name}`);
      values[f.name] = f.type === "checkbox" ? input.checked : input.value;
    }
    try {
      await onSubmit(values);
      dialog.close();
    } catch (err) {
      show($("dialogError"), err.message);
    }
  };
  $("dialogCancel").onclick = () => dialog.close();
  dialog.showModal();
}

// ---------- shell ----------
function tabsFor(user) {
  const tabs = [["gyms", "Gyms"], ["bookings", "Bookings"]];
  if (user.role === "superadmin") tabs.push(["users", "Users"]);
  return tabs;
}

function renderTabs() {
  $("tabs").innerHTML = tabsFor(state.user)
    .map(([key, label]) => `<button type="button" class="tab ${state.tab === key ? "active" : ""}" data-tab="${key}">${label}</button>`)
    .join("");
}

async function render() {
  show($("appError"), "");
  renderTabs();
  try {
    if (state.tab === "gyms") await (state.gym ? renderGym() : renderGyms());
    else if (state.tab === "bookings") await renderBookings();
    else if (state.tab === "users") await renderUsers();
  } catch (err) {
    if (err.status === 401) return showLogin();
    show($("appError"), err.message);
  }
}

function showLogin() {
  state.user = null;
  $("app").hidden = true;
  $("userBar").hidden = true;
  $("guestLink").hidden = false;
  $("loginCard").hidden = false;
}

function showApp() {
  $("loginCard").hidden = true;
  $("app").hidden = false;
  $("userBar").hidden = false;
  $("guestLink").hidden = true;
  $("whoami").textContent = `${state.user.name} · ${state.user.role}`;
  render();
}

async function guarded(action) {
  try {
    await action();
  } catch (err) {
    if (err.status === 401) return showLogin();
    show($("appError"), err.message);
  }
}


// ---------- gyms ----------
const gymFields = (g = {}) => [
  { name: "name", label: "Name", value: g.name, required: true },
  { name: "city", label: "City", value: g.city, required: true },
  { name: "country", label: "Country", value: g.country, required: true },
  { name: "address", label: "Address", value: g.address },
  { name: "description", label: "Description", value: g.description },
];

async function renderGyms() {
  const gyms = await api("/api/admin/gyms");
  $("view").innerHTML = `
    <div class="card">
      <div class="section-head"><h2>Gyms</h2><button type="button" class="primary small" data-action="add-gym">Add gym</button></div>
      <div class="table-scroll"><table class="table">
        <thead><tr><th>Gym</th><th>Location</th><th>Class types</th><th>From</th><th>Status</th><th></th></tr></thead>
        <tbody>${gyms
          .map(
            (g) => `<tr class="${g.active ? "" : "inactive"}">
              <td><a href="#" data-action="manage" data-code="${esc(g.code)}"><strong>${esc(g.name)}</strong></a><div class="muted">${esc(g.code)}</div></td>
              <td>${esc(g.city)}, ${esc(g.country)}</td>
              <td>${g.class_type_count}</td>
              <td>${g.from_price ? money(g.from_price) : "-"}</td>
              <td><span class="badge ${g.active ? "ok" : "off"}">${g.active ? "Open" : "Closed"}</span></td>
              <td class="actions">
                <button type="button" class="small primary" data-action="manage" data-code="${esc(g.code)}">Manage classes</button>
                <button type="button" class="small" data-action="edit-gym" data-code="${esc(g.code)}">Edit</button>
                <button type="button" class="small" data-action="toggle-gym" data-code="${esc(g.code)}" data-active="${g.active}">${g.active ? "Close" : "Reopen"}</button>
                <button type="button" class="small danger" data-action="delete-gym" data-code="${esc(g.code)}">Delete</button>
              </td></tr>`,
          )
          .join("")}</tbody>
      </table></div>
    </div>`;
  state.gyms = gyms;
}

function gymActions(action, code, dataset) {
  const gym = (state.gyms || []).find((g) => g.code === code);
  switch (action) {
    case "add-gym":
      return openForm({
        title: "Add a gym",
        help: "Add its class types and timetable afterwards under Manage classes.",
        fields: [...gymFields(), { name: "code", label: "Code (optional)", help: "Short URL-safe id; generated from the name when blank." }],
        onSubmit: async (v) => {
          const gym = await post("/api/admin/gyms", { ...v, code: v.code || null });
          state.gym = gym.code; // straight to the class management page
          render();
        },
      });
    case "edit-gym":
      return openForm({
        title: `Edit ${gym.name}`,
        fields: gymFields(gym),
        onSubmit: async (v) => {
          await patch(`/api/admin/gyms/${code}`, v);
          render();
        },
      });
    case "toggle-gym":
      return guarded(async () => {
        await patch(`/api/admin/gyms/${code}`, { active: dataset.active !== "true" });
        render();
      });
    case "delete-gym":
      if (!confirm(`Delete ${gym.name}? Its class types and sessions are removed too. Gyms with booking history cannot be deleted.`)) return;
      return guarded(async () => {
        await del(`/api/admin/gyms/${code}`);
        render();
      });
    case "manage":
      state.gym = code;
      return render();
  }
}

// ---------- one gym: class types and sessions ----------
const utc = (startsAt) => startsAt.replace("T", " ").slice(0, 16);

async function renderGym() {
  const code = state.gym;
  const [gyms, types, sessions] = await Promise.all([
    api("/api/admin/gyms"),
    api(`/api/admin/gyms/${code}/class-types`),
    api(`/api/admin/gyms/${code}/sessions`),
  ]);
  const gym = gyms.find((g) => g.code === code);
  state.types = types;
  state.sessions = sessions;
  $("view").innerHTML = `
    <p><button type="button" class="small" data-action="back">← All gyms</button></p>
    <div class="card">
      <h2>${esc(gym.name)} <span class="muted">${esc(gym.city)}, ${esc(gym.country)}</span></h2>
      <div class="section-head"><h3>Class types &amp; prices</h3><button type="button" class="primary small" data-action="add-type">Add class type</button></div>
      <div class="table-scroll"><table class="table">
        <thead><tr><th>Class</th><th>Price</th><th>Duration</th><th>Status</th><th></th></tr></thead>
        <tbody>${types
          .map(
            (t) => `<tr class="${t.active ? "" : "inactive"}">
              <td><strong>${esc(t.name)}</strong><div class="muted">${esc(t.code)} · ${esc(t.description)}</div></td>
              <td>${money(t.price)}</td><td>${t.duration_min} min</td>
              <td><span class="badge ${t.active ? "ok" : "off"}">${t.active ? "Active" : "Off"}</span></td>
              <td class="actions">
                <button type="button" class="small" data-action="edit-type" data-id="${t.id}">Edit</button>
                <button type="button" class="small" data-action="toggle-type" data-id="${t.id}" data-active="${t.active}">${t.active ? "Turn off" : "Turn on"}</button>
                <button type="button" class="small danger" data-action="delete-type" data-id="${t.id}">Delete</button>
              </td></tr>`,
          )
          .join("")}</tbody>
      </table></div>
    </div>
    <div class="card">
      <div class="section-head"><h3>Sessions (${sessions.length}) <span class="muted">times in UTC</span></h3><button type="button" class="primary small" data-action="add-session" ${types.length ? "" : "disabled"}>Add session</button></div>
      <div class="table-scroll"><table class="table">
        <thead><tr><th>Starts</th><th>Class</th><th>Trainer</th><th>Booked</th><th>Status</th><th></th></tr></thead>
        <tbody>${sessions
          .map(
            (s) => `<tr class="${s.active ? "" : "inactive"}">
              <td><strong>${esc(utc(s.starts_at))}</strong></td><td>${esc(s.class_name)}</td><td>${esc(s.trainer)}</td>
              <td>${s.booked} / ${s.capacity}</td>
              <td><span class="badge ${s.active ? "ok" : "off"}">${s.active ? "Open" : "Hidden"}</span></td>
              <td class="actions">
                <button type="button" class="small" data-action="edit-session" data-id="${s.id}">Edit</button>
                <button type="button" class="small" data-action="toggle-session" data-id="${s.id}" data-active="${s.active}">${s.active ? "Hide" : "Show"}</button>
                <button type="button" class="small danger" data-action="delete-session" data-id="${s.id}">Delete</button>
              </td></tr>`,
          )
          .join("")}</tbody>
      </table></div>
    </div>`;
}

const typeFields = (t = {}) => [
  { name: "name", label: "Name", value: t.name, required: true },
  { name: "description", label: "Description", value: t.description },
  { name: "duration_min", label: "Duration (minutes)", type: "number", value: t.duration_min ?? 60, min: 5, max: 480, required: true },
  { name: "price", label: "Price per class (USD)", type: "number", value: t.price, min: 0, required: true },
];

const toInput = (startsAt) => startsAt.slice(0, 16); // "2026-10-15T09:00" for <input type="datetime-local">

function gymDetailActions(action, dataset) {
  const code = state.gym;
  const type = (state.types || []).find((t) => String(t.id) === dataset.id);
  const session = (state.sessions || []).find((s) => String(s.id) === dataset.id);
  const typeOptions = (state.types || []).filter((t) => t.active).map((t) => [t.id, t.name]);
  switch (action) {
    case "back":
      state.gym = null;
      return render();
    case "add-type":
      return openForm({
        title: "Add a class type",
        fields: typeFields(),
        onSubmit: async (v) => {
          await post(`/api/admin/gyms/${code}/class-types`, { ...v, duration_min: Number(v.duration_min), price: Number(v.price) });
          render();
        },
      });
    case "edit-type":
      return openForm({
        title: `Edit ${type.name}`,
        help: "A new price applies to future bookings only; existing bookings keep the price they were made at.",
        fields: typeFields(type),
        onSubmit: async (v) => {
          await patch(`/api/admin/class-types/${type.id}`, { ...v, duration_min: Number(v.duration_min), price: Number(v.price) });
          render();
        },
      });
    case "toggle-type":
      return guarded(async () => {
        await patch(`/api/admin/class-types/${type.id}`, { active: dataset.active !== "true" });
        render();
      });
    case "delete-type":
      if (!confirm(`Delete the ${type.name} class type? Types that still have sessions cannot be deleted.`)) return;
      return guarded(async () => {
        await del(`/api/admin/class-types/${type.id}`);
        render();
      });
    case "add-session":
      return openForm({
        title: "Add a session",
        help: "Times are UTC.",
        fields: [
          { name: "class_type_id", label: "Class", options: typeOptions, required: true },
          { name: "starts_at", label: "Starts (UTC)", type: "datetime-local", required: true },
          { name: "capacity", label: "Capacity", type: "number", value: 15, min: 1, max: 500, required: true },
          { name: "trainer", label: "Trainer" },
        ],
        onSubmit: async (v) => {
          await post(`/api/admin/gyms/${code}/sessions`, { ...v, class_type_id: Number(v.class_type_id), capacity: Number(v.capacity) });
          render();
        },
      });
    case "edit-session":
      return openForm({
        title: `Edit ${session.class_name} · ${utc(session.starts_at)}`,
        help: session.booked ? "This session has bookings: it can be given more spots, but not moved or hidden until they are cancelled." : "",
        fields: [
          { name: "starts_at", label: "Starts (UTC)", type: "datetime-local", value: toInput(session.starts_at), required: true },
          { name: "capacity", label: "Capacity", type: "number", value: session.capacity, min: Math.max(session.booked, 1), max: 500, required: true },
          { name: "trainer", label: "Trainer", value: session.trainer },
        ],
        onSubmit: async (v) => {
          const body = { capacity: Number(v.capacity), trainer: v.trainer };
          if (v.starts_at !== toInput(session.starts_at)) body.starts_at = v.starts_at;
          await patch(`/api/admin/sessions/${session.id}`, body);
          render();
        },
      });
    case "toggle-session":
      return guarded(async () => {
        await patch(`/api/admin/sessions/${session.id}`, { active: dataset.active !== "true" });
        render();
      });
    case "delete-session":
      if (!confirm(`Delete the ${session.class_name} session at ${utc(session.starts_at)}? Sessions with booking history cannot be deleted.`)) return;
      return guarded(async () => {
        await del(`/api/admin/sessions/${session.id}`);
        render();
      });
  }
}

// ---------- bookings ----------
const bookingFilters = { gym: "", status: "", email: "" };

async function renderBookings() {
  const [gyms, bookings] = await Promise.all([
    api("/api/admin/gyms"),
    api(`/api/admin/bookings?${new URLSearchParams(Object.entries(bookingFilters).filter(([, v]) => v))}`),
  ]);
  $("view").innerHTML = `
    <div class="card">
      <h2>Bookings</h2>
      <form id="bookingFilter" class="row">
        <label>Gym <select id="fGym"><option value="">All gyms</option>${gyms
          .map((g) => `<option value="${esc(g.code)}" ${bookingFilters.gym === g.code ? "selected" : ""}>${esc(g.name)}</option>`)
          .join("")}</select></label>
        <label>Status <select id="fStatus">${[["", "Any"], ["confirmed", "Confirmed"], ["cancelled", "Cancelled"]]
          .map(([v, l]) => `<option value="${v}" ${bookingFilters.status === v ? "selected" : ""}>${l}</option>`)
          .join("")}</select></label>
        <label>Member email <input id="fEmail" type="email" value="${esc(bookingFilters.email)}" /></label>
        <button type="submit">Filter</button>
      </form>
      <div class="table-scroll"><table class="table">
        <thead><tr><th>Reference</th><th>Gym</th><th>Member</th><th>Class (UTC)</th><th>Price</th><th>Status</th><th></th></tr></thead>
        <tbody>${bookings
          .map(
            (b) => `<tr class="${b.status === "cancelled" ? "inactive" : ""}">
              <td><strong>${esc(b.reference)}</strong></td>
              <td>${esc(b.gym_name)}<div class="muted">${esc(b.gym_city)}</div></td>
              <td>${esc(b.member_name)}<div class="muted">${esc(b.member_email)}</div></td>
              <td>${esc(b.class_name)}<div class="muted">${esc(utc(b.starts_at))}</div></td>
              <td>${money(b.price)}</td>
              <td><span class="badge ${b.status === "confirmed" ? "ok" : "off"}">${esc(b.status)}</span></td>
              <td class="actions">${b.status === "confirmed" ? `<button type="button" class="small danger" data-action="cancel-booking" data-ref="${esc(b.reference)}">Cancel</button>` : ""}</td>
            </tr>`,
          )
          .join("")}</tbody>
      </table></div>
      ${bookings.length ? "" : '<p class="muted empty">No bookings match.</p>'}
    </div>`;
  $("bookingFilter").onsubmit = (event) => {
    event.preventDefault();
    Object.assign(bookingFilters, { gym: $("fGym").value, status: $("fStatus").value, email: $("fEmail").value.trim() });
    render();
  };
}

// ---------- users ----------
async function renderUsers() {
  const users = await api("/api/admin/users");
  state.users = users;
  $("view").innerHTML = `
    <div class="card">
      <div class="section-head"><h2>Users</h2><button type="button" class="primary small" data-action="add-user">Add user</button></div>
      <div class="table-scroll"><table class="table">
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Last login</th><th></th></tr></thead>
        <tbody>${users
          .map(
            (u) => `<tr class="${u.active ? "" : "inactive"}">
              <td><strong>${esc(u.name)}</strong>${u.id === state.user.id ? ' <span class="muted">(you)</span>' : ""}</td>
              <td>${esc(u.email)}</td><td>${esc(u.role)}</td>
              <td><span class="badge ${u.active ? "ok" : "off"}">${u.active ? "Active" : "Deactivated"}</span></td>
              <td class="muted">${u.last_login_at ? esc(u.last_login_at.replace("T", " ")) : "never"}</td>
              <td class="actions">
                <button type="button" class="small" data-action="edit-user" data-id="${u.id}">Edit</button>
                <button type="button" class="small" data-action="reset-password" data-id="${u.id}">Reset password</button>
                ${u.id === state.user.id ? "" : `<button type="button" class="small ${u.active ? "danger" : ""}" data-action="toggle-user" data-id="${u.id}" data-active="${u.active}">${u.active ? "Deactivate" : "Activate"}</button>`}
              </td></tr>`,
          )
          .join("")}</tbody>
      </table></div>
    </div>`;
}

const ROLE_OPTIONS = [["admin", "Admin: manages gyms, classes and bookings"], ["superadmin", "Superadmin: also manages users"]];

function userActions(action, dataset) {
  const user = (state.users || []).find((u) => String(u.id) === dataset.id);
  switch (action) {
    case "add-user":
      return openForm({
        title: "Add a user",
        fields: [
          { name: "name", label: "Name", required: true },
          { name: "email", label: "Email", type: "email", required: true },
          { name: "password", label: "Initial password", type: "password", required: true, help: "At least 8 characters. Share it securely; they can change it after logging in." },
          { name: "role", label: "Role", options: ROLE_OPTIONS, value: "admin" },
        ],
        onSubmit: async (v) => {
          await post("/api/admin/users", v);
          render();
        },
      });
    case "edit-user":
      return openForm({
        title: `Edit ${user.name}`,
        fields: [
          { name: "name", label: "Name", value: user.name, required: true },
          { name: "role", label: "Role", options: ROLE_OPTIONS, value: user.role },
        ],
        onSubmit: async (v) => {
          await patch(`/api/admin/users/${user.id}`, { name: v.name, ...(user.id === state.user.id ? {} : { role: v.role }) });
          render();
        },
      });
    case "toggle-user":
      return guarded(async () => {
        await patch(`/api/admin/users/${user.id}`, { active: dataset.active !== "true" });
        render();
      });
    case "reset-password":
      return openForm({
        title: `Reset password for ${user.name}`,
        help: "They are signed out everywhere and must log in with the new password.",
        fields: [{ name: "password", label: "New password", type: "password", required: true }],
        onSubmit: async (v) => {
          await post(`/api/admin/users/${user.id}/reset-password`, v);
          render();
        },
      });
  }
}

// ---------- events ----------
document.addEventListener("click", (event) => {
  const tab = event.target.closest("[data-tab]");
  if (tab) {
    state.tab = tab.dataset.tab;
    state.gym = null;
    return render();
  }
  const button = event.target.closest("[data-action]");
  if (!button) return;
  if (button.tagName === "A") event.preventDefault();
  const { action } = button.dataset;
  if (action === "cancel-booking") {
    if (!confirm(`Cancel booking ${button.dataset.ref}?`)) return;
    return guarded(async () => {
      await post(`/api/admin/bookings/${button.dataset.ref}/cancel`);
      render();
    });
  }
  if (["add-gym", "edit-gym", "toggle-gym", "delete-gym", "manage"].includes(action)) return gymActions(action, button.dataset.code, button.dataset);
  if (["add-user", "edit-user", "toggle-user", "reset-password"].includes(action)) return userActions(action, button.dataset);
  return gymDetailActions(action, button.dataset);
});

$("login").addEventListener("submit", async (event) => {
  event.preventDefault();
  show($("loginError"), "");
  try {
    const { user } = await post("/api/auth/login", { email: $("loginEmail").value, password: $("loginPassword").value });
    $("loginPassword").value = "";
    state.user = user;
    state.tab = "gyms";
    showApp();
  } catch (err) {
    show($("loginError"), err.message);
  }
});

$("logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
  showLogin();
});

$("changePassword").addEventListener("click", () =>
  openForm({
    title: "Change your password",
    help: "You will be signed out everywhere and asked to log in again.",
    fields: [
      { name: "current_password", label: "Current password", type: "password", required: true },
      { name: "new_password", label: "New password (min. 8 characters)", type: "password", required: true },
    ],
    onSubmit: async (v) => {
      await post("/api/auth/change-password", v);
      showLogin();
    },
  }),
);

(async () => {
  try {
    state.user = await api("/api/auth/me");
    showApp();
  } catch {
    showLogin();
  }
})();

