// Helpers shared by the member page and the admin area.
const $ = (id) => document.getElementById(id);
const money = (n) => `₹${Number(n).toLocaleString("en-IN")}`;
const iso = (d) => d.toISOString().slice(0, 10);

// Everything that comes from the server or a user is escaped before it is put into HTML.
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function api(path, options = {}) {
  const resp = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (resp.status === 204) return null;
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((e) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ") : null;
    throw new ApiError(data.error?.message || detail || `Request failed (${resp.status})`, resp.status, data.error?.code);
  }
  return data;
}

const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body ?? {}) });
const patch = (path, body) => api(path, { method: "PATCH", body: JSON.stringify(body) });
const del = (path) => api(path, { method: "DELETE" });

function show(el, message) {
  el.textContent = message || "";
  el.hidden = !message;
}
