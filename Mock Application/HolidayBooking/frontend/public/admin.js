// Staff area. Sections: Hotels (with room types and rooms), Bookings, Users (superadmin only).
const state = { user: null, tab: "hotels", hotel: null };

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
  const tabs = [["hotels", "Hotels"], ["bookings", "Bookings"]];
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
    if (state.tab === "hotels") await (state.hotel ? renderHotel() : renderHotels());
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

// ---------- hotels ----------
const hotelFields = (h = {}) => [
  { name: "name", label: "Name", value: h.name, required: true },
  { name: "city", label: "City", value: h.city, required: true },
  { name: "country", label: "Country", value: h.country, required: true },
  { name: "address", label: "Address", value: h.address },
  { name: "description", label: "Description", value: h.description },
  { name: "stars", label: "Stars (1-5)", type: "number", value: h.stars ?? 3, min: 1, max: 5, required: true },
];

async function renderHotels() {
  const hotels = await api("/api/admin/hotels");
  $("view").innerHTML = `
    <div class="card">
      <div class="section-head"><h2>Hotels</h2><button type="button" class="primary small" data-action="add-hotel">Add hotel</button></div>
      <div class="table-scroll"><table class="table">
        <thead><tr><th>Hotel</th><th>Location</th><th>Rooms</th><th>From</th><th>Status</th><th></th></tr></thead>
        <tbody>${hotels
          .map(
            (h) => `<tr class="${h.active ? "" : "inactive"}">
              <td><a href="#" data-action="manage" data-code="${esc(h.code)}"><strong>${esc(h.name)}</strong></a><div class="muted">${esc(h.code)} · ${stars(h.stars)}</div></td>
              <td>${esc(h.city)}, ${esc(h.country)}</td>
              <td>${h.room_count}</td>
              <td>${h.from_price ? money(h.from_price) : "-"}</td>
              <td><span class="badge ${h.active ? "ok" : "off"}">${h.active ? "Open" : "Closed"}</span></td>
              <td class="actions">
                <button type="button" class="small primary" data-action="manage" data-code="${esc(h.code)}">Manage rooms</button>
                <button type="button" class="small" data-action="edit-hotel" data-code="${esc(h.code)}">Edit</button>
                <button type="button" class="small" data-action="toggle-hotel" data-code="${esc(h.code)}" data-active="${h.active}">${h.active ? "Close" : "Reopen"}</button>
                <button type="button" class="small danger" data-action="delete-hotel" data-code="${esc(h.code)}">Delete</button>
              </td></tr>`,
          )
          .join("")}</tbody>
      </table></div>
    </div>`;
  state.hotels = hotels;
}

function hotelActions(action, code, dataset) {
  const hotel = (state.hotels || []).find((h) => h.code === code);
  switch (action) {
    case "add-hotel":
      return openForm({
        title: "Add a hotel",
        help: "Optionally set up the first room type and its rooms now; you can add more later under Manage rooms.",
        fields: [
          ...hotelFields(),
          { name: "code", label: "Code (optional)", help: "Short URL-safe id; generated from the name when blank." },
          { name: "type_name", label: "First room type (optional)", placeholder: "e.g. Deluxe" },
          { name: "type_description", label: "Room type description" },
          { name: "type_price", label: "Price per night (USD)", type: "number", min: 1 },
          { name: "type_guests", label: "Maximum guests", type: "number", value: 2, min: 1, max: 20 },
          { name: "room_start", label: "First room number", type: "number", min: 0, placeholder: "e.g. 101" },
          { name: "room_count", label: "Number of rooms", type: "number", min: 1, max: 200, placeholder: "e.g. 10" },
        ],
        onSubmit: async (v) => {
          const typeName = v.type_name.trim();
          if (typeName && (!v.type_price || !v.room_start || !v.room_count)) {
            throw new Error("For the room type, give a price, a first room number and a number of rooms.");
          }
          const hotel = await post("/api/admin/hotels", {
            name: v.name, city: v.city, country: v.country, address: v.address, description: v.description,
            stars: Number(v.stars), code: v.code || null,
          });
          if (typeName) {
            const type = await post(`/api/admin/hotels/${hotel.code}/room-types`, {
              name: typeName, description: v.type_description, price_per_night: Number(v.type_price), max_guests: Number(v.type_guests),
            });
            await post(`/api/admin/hotels/${hotel.code}/rooms`, {
              room_type_id: type.id, start: Number(v.room_start), count: Number(v.room_count),
            });
          }
          state.hotel = hotel.code; // straight to the room management page
          render();
        },
      });
    case "edit-hotel":
      return openForm({
        title: `Edit ${hotel.name}`,
        fields: hotelFields(hotel),
        onSubmit: async (v) => {
          await patch(`/api/admin/hotels/${code}`, { ...v, stars: Number(v.stars) });
          render();
        },
      });
    case "toggle-hotel":
      return guarded(async () => {
        await patch(`/api/admin/hotels/${code}`, { active: dataset.active !== "true" });
        render();
      });
    case "delete-hotel":
      if (!confirm(`Delete ${hotel.name}? Its room types and rooms are removed too. Hotels with booking history cannot be deleted.`)) return;
      return guarded(async () => {
        await del(`/api/admin/hotels/${code}`);
        render();
      });
    case "manage":
      state.hotel = code;
      return render();
  }
}

// ---------- one hotel: room types and rooms ----------
async function renderHotel() {
  const code = state.hotel;
  const [hotels, types, rooms] = await Promise.all([
    api("/api/admin/hotels"),
    api(`/api/admin/hotels/${code}/room-types`),
    api(`/api/admin/hotels/${code}/rooms`),
  ]);
  const hotel = hotels.find((h) => h.code === code);
  state.types = types;
  state.rooms = rooms;
  $("view").innerHTML = `
    <p><button type="button" class="small" data-action="back">← All hotels</button></p>
    <div class="card">
      <h2>${esc(hotel.name)} <span class="muted">${esc(hotel.city)}, ${esc(hotel.country)}</span></h2>
      <div class="section-head"><h3>Room types &amp; prices</h3><button type="button" class="primary small" data-action="add-type">Add room type</button></div>
      <div class="table-scroll"><table class="table">
        <thead><tr><th>Type</th><th>Price / night</th><th>Sleeps</th><th>Rooms</th><th>Status</th><th></th></tr></thead>
        <tbody>${types
          .map(
            (t) => `<tr class="${t.active ? "" : "inactive"}">
              <td><strong>${esc(t.name)}</strong><div class="muted">${esc(t.code)} · ${esc(t.description)}</div></td>
              <td>${money(t.price_per_night)}</td><td>${t.max_guests}</td><td>${t.total_rooms}</td>
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
      <div class="section-head"><h3>Rooms (${rooms.length})</h3><button type="button" class="primary small" data-action="add-rooms" ${types.length ? "" : "disabled"}>Add rooms</button></div>
      <div class="table-scroll"><table class="table">
        <thead><tr><th>Number</th><th>Type</th><th>Status</th><th></th></tr></thead>
        <tbody>${rooms
          .map(
            (r) => `<tr class="${r.active ? "" : "inactive"}">
              <td><strong>${esc(r.number)}</strong></td><td>${esc(r.room_type_name)}</td>
              <td><span class="badge ${r.active ? "ok" : "off"}">${r.active ? "In service" : "Out of service"}</span></td>
              <td class="actions">
                <button type="button" class="small" data-action="move-room" data-id="${r.id}">Change type</button>
                <button type="button" class="small" data-action="toggle-room" data-id="${r.id}" data-active="${r.active}">${r.active ? "Take out of service" : "Return to service"}</button>
                <button type="button" class="small danger" data-action="delete-room" data-id="${r.id}">Delete</button>
              </td></tr>`,
          )
          .join("")}</tbody>
      </table></div>
    </div>`;
}

const typeFields = (t = {}) => [
  { name: "name", label: "Name", value: t.name, required: true },
  { name: "description", label: "Description", value: t.description },
  { name: "price_per_night", label: "Price per night (USD)", type: "number", value: t.price_per_night, min: 1, required: true },
  { name: "max_guests", label: "Maximum guests", type: "number", value: t.max_guests ?? 2, min: 1, max: 20, required: true },
];

function hotelDetailActions(action, dataset) {
  const code = state.hotel;
  const type = (state.types || []).find((t) => String(t.id) === dataset.id);
  const room = (state.rooms || []).find((r) => String(r.id) === dataset.id);
  const typeOptions = (state.types || []).map((t) => [t.id, t.name]);
  switch (action) {
    case "back":
      state.hotel = null;
      return render();
    case "add-type":
      return openForm({
        title: "Add a room type",
        fields: typeFields(),
        onSubmit: async (v) => {
          await post(`/api/admin/hotels/${code}/room-types`, { ...v, price_per_night: Number(v.price_per_night), max_guests: Number(v.max_guests) });
          render();
        },
      });
    case "edit-type":
      return openForm({
        title: `Edit ${type.name}`,
        help: "A new price applies to future bookings only; existing bookings keep the price they were made at.",
        fields: typeFields(type),
        onSubmit: async (v) => {
          await patch(`/api/admin/room-types/${type.id}`, { ...v, price_per_night: Number(v.price_per_night), max_guests: Number(v.max_guests) });
          render();
        },
      });
    case "toggle-type":
      return guarded(async () => {
        await patch(`/api/admin/room-types/${type.id}`, { active: dataset.active !== "true" });
        render();
      });
    case "delete-type":
      if (!confirm(`Delete the ${type.name} room type?`)) return;
      return guarded(async () => {
        await del(`/api/admin/room-types/${type.id}`);
        render();
      });
    case "add-rooms":
      return openForm({
        title: "Add rooms",
        help: "Give a starting number and how many, or list room numbers separated by commas.",
        fields: [
          { name: "room_type_id", label: "Room type", options: typeOptions, required: true },
          { name: "start", label: "Starting number", type: "number", min: 0, placeholder: "e.g. 201" },
          { name: "count", label: "How many", type: "number", min: 1, max: 200, placeholder: "e.g. 10" },
          { name: "numbers", label: "Or room numbers", placeholder: "e.g. 301, 302, S1" },
        ],
        onSubmit: async (v) => {
          const body = { room_type_id: Number(v.room_type_id) };
          if (v.numbers.trim()) body.numbers = v.numbers.split(",").map((n) => n.trim()).filter(Boolean);
          else {
            body.start = Number(v.start);
            body.count = Number(v.count);
          }
          await post(`/api/admin/hotels/${code}/rooms`, body);
          render();
        },
      });
    case "move-room":
      return openForm({
        title: `Room ${room.number}: change type`,
        fields: [{ name: "room_type_id", label: "Room type", options: typeOptions, value: room.room_type_id, required: true }],
        onSubmit: async (v) => {
          await patch(`/api/admin/rooms/${room.id}`, { room_type_id: Number(v.room_type_id) });
          render();
        },
      });
    case "toggle-room":
      return guarded(async () => {
        await patch(`/api/admin/rooms/${room.id}`, { active: dataset.active !== "true" });
        render();
      });
    case "delete-room":
      if (!confirm(`Delete room ${room.number}? Rooms with booking history cannot be deleted.`)) return;
      return guarded(async () => {
        await del(`/api/admin/rooms/${room.id}`);
        render();
      });
  }
}

// ---------- bookings ----------
const bookingFilters = { hotel: "", status: "", email: "" };

async function renderBookings() {
  const [hotels, bookings] = await Promise.all([
    api("/api/admin/hotels"),
    api(`/api/admin/bookings?${new URLSearchParams(Object.entries(bookingFilters).filter(([, v]) => v))}`),
  ]);
  $("view").innerHTML = `
    <div class="card">
      <h2>Bookings</h2>
      <form id="bookingFilter" class="row">
        <label>Hotel <select id="fHotel"><option value="">All hotels</option>${hotels
          .map((h) => `<option value="${esc(h.code)}" ${bookingFilters.hotel === h.code ? "selected" : ""}>${esc(h.name)}</option>`)
          .join("")}</select></label>
        <label>Status <select id="fStatus">${[["", "Any"], ["confirmed", "Confirmed"], ["cancelled", "Cancelled"]]
          .map(([v, l]) => `<option value="${v}" ${bookingFilters.status === v ? "selected" : ""}>${l}</option>`)
          .join("")}</select></label>
        <label>Guest email <input id="fEmail" type="email" value="${esc(bookingFilters.email)}" /></label>
        <button type="submit">Filter</button>
      </form>
      <div class="table-scroll"><table class="table">
        <thead><tr><th>Reference</th><th>Hotel</th><th>Guest</th><th>Stay</th><th>Room</th><th>Total</th><th>Status</th><th></th></tr></thead>
        <tbody>${bookings
          .map(
            (b) => `<tr class="${b.status === "cancelled" ? "inactive" : ""}">
              <td><strong>${esc(b.reference)}</strong></td>
              <td>${esc(b.hotel_name)}<div class="muted">${esc(b.hotel_city)}</div></td>
              <td>${esc(b.guest_name)}<div class="muted">${esc(b.guest_email)}</div></td>
              <td>${esc(b.check_in)} → ${esc(b.check_out)}<div class="muted">${b.nights} night(s)</div></td>
              <td>${esc(b.room_number)} <span class="muted">${esc(b.category_code)}</span></td>
              <td>${money(b.total_price)}</td>
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
    Object.assign(bookingFilters, { hotel: $("fHotel").value, status: $("fStatus").value, email: $("fEmail").value.trim() });
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

const ROLE_OPTIONS = [["admin", "Admin: manages hotels, rooms and bookings"], ["superadmin", "Superadmin: also manages users"]];

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
    state.hotel = null;
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
  if (["add-hotel", "edit-hotel", "toggle-hotel", "delete-hotel", "manage"].includes(action)) return hotelActions(action, button.dataset.code, button.dataset);
  if (["add-user", "edit-user", "toggle-user", "reset-password"].includes(action)) return userActions(action, button.dataset);
  return hotelDetailActions(action, button.dataset);
});

$("login").addEventListener("submit", async (event) => {
  event.preventDefault();
  show($("loginError"), "");
  try {
    const { user } = await post("/api/auth/login", { email: $("loginEmail").value, password: $("loginPassword").value });
    $("loginPassword").value = "";
    state.user = user;
    state.tab = "hotels";
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
