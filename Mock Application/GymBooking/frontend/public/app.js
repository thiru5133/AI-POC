// Member page: find a class by location, type and dates, book a spot, and manage bookings by email.
let selected = null; // a session from /api/sessions

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const when = (startsAt) => startsAt.replace("T", " ").slice(0, 16) + " UTC";

async function loadFilters() {
  try {
    const gyms = await api("/api/gyms");
    const places = [...new Set(gyms.map((g) => `${g.city}|${g.country}`))].sort();
    for (const place of places) {
      const [city, country] = place.split("|");
      const option = el("option", "", `${city}, ${country}`);
      option.value = city;
      $("where").append(option);
    }
    const classes = new Map();
    for (const gym of gyms) {
      for (const t of (await api(`/api/gyms/${gym.code}`)).class_types) classes.set(t.code, t.name);
    }
    for (const [code, name] of [...classes].sort((a, b) => a[1].localeCompare(b[1]))) {
      const option = el("option", "", name);
      option.value = code;
      $("category").append(option);
    }
  } catch (err) {
    show($("searchError"), err.message);
  }
}

function renderResults(result) {
  const box = $("results");
  box.replaceChildren();
  if (!result.sessions.length) {
    box.append(el("p", "muted empty", "No classes match that search."));
    return;
  }
  let day = "";
  for (const s of result.sessions) {
    if (s.starts_at.slice(0, 10) !== day) {
      day = s.starts_at.slice(0, 10);
      box.append(el("h3", "day", new Date(`${day}T00:00:00Z`).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" })));
    }
    const row = el("div", "slot");
    const info = el("div");
    info.append(
      el("strong", "", `${s.starts_at.slice(11, 16)} · ${s.class.name} (${s.class.duration_min} min)`),
      el("p", "muted", `${s.gym.name}, ${s.gym.city} · trainer ${s.trainer || "TBA"}`),
    );
    const price = el("div", "price-col");
    price.append(
      el("span", "price", money(s.class.price)),
      el("span", s.spots_left ? "ok" : "error", s.spots_left ? `${s.spots_left} of ${s.capacity} spots left` : "Full"),
    );
    const button = el("button", "primary", "Book");
    button.disabled = s.spots_left === 0;
    button.onclick = () => startBooking(s);
    row.append(info, price, button);
    box.append(row);
  }
}

function startBooking(session) {
  selected = session;
  $("bookingTitle").textContent = `${session.class.name} at ${session.gym.name}`;
  $("bookingSummary").textContent = `${session.gym.city} · ${when(session.starts_at)} · ${session.class.duration_min} min · ${money(session.class.price)}`;
  show($("bookError"), "");
  show($("bookOk"), "");
  $("book").hidden = false;
  $("bookingCard").hidden = false;
  $("bookingCard").scrollIntoView({ behavior: "smooth" });
}

async function search(event) {
  event?.preventDefault();
  show($("searchError"), "");
  try {
    const params = new URLSearchParams({ date_from: $("dateFrom").value, date_to: $("dateTo").value });
    if ($("where").value) params.set("city", $("where").value);
    if ($("category").value) params.set("category", $("category").value);
    renderResults(await api(`/api/sessions?${params}`));
  } catch (err) {
    $("results").replaceChildren();
    show($("searchError"), err.message);
  }
}

async function book(event) {
  event.preventDefault();
  show($("bookError"), "");
  try {
    const booking = await post("/api/bookings", {
      session_id: selected.session_id,
      member_name: $("memberName").value,
      member_email: $("memberEmail").value,
    });
    $("book").hidden = true;
    show($("bookOk"), `Booked! Reference ${booking.reference} · ${booking.class_name} at ${booking.gym_name}, ${when(booking.starts_at)} · ${money(booking.price)}`);
    $("lookupEmail").value = booking.member_email;
    search();
    lookup();
  } catch (err) {
    show($("bookError"), err.message);
    search(); // spots may have changed
  }
}

function renderBookings(list) {
  const box = $("bookings");
  box.replaceChildren();
  if (!list.length) {
    box.append(el("p", "muted", "No bookings found for that email."));
    return;
  }
  for (const b of list) {
    const row = el("div", `booking ${b.status}`);
    const info = el("div");
    info.append(
      el("strong", "", `${b.reference} · ${b.class_name} · ${b.gym_name} (${b.gym_city})`),
      el("p", "muted", `${b.member_name} · ${when(b.starts_at)} · ${money(b.price)} · ${b.status}`),
    );
    row.append(info);
    if (b.status === "confirmed" && b.starts_at > new Date().toISOString()) {
      const cancel = el("button", "danger", "Cancel booking");
      cancel.onclick = async () => {
        if (!confirm(`Cancel booking ${b.reference}?`)) return;
        try {
          await post(`/api/bookings/${b.reference}/cancel`);
        } catch (err) {
          show($("lookupError"), err.message);
          return;
        }
        lookup();
        search();
      };
      row.append(cancel);
    }
    box.append(row);
  }
}

async function lookup(event) {
  event?.preventDefault();
  show($("lookupError"), "");
  try {
    renderBookings(await api(`/api/bookings?${new URLSearchParams({ email: $("lookupEmail").value })}`));
  } catch (err) {
    show($("lookupError"), err.message);
  }
}

const today = new Date();
$("dateFrom").min = $("dateTo").min = iso(today);
$("dateFrom").value = iso(today);
$("dateTo").value = iso(new Date(today.getTime() + 6 * 86400000));
$("search").addEventListener("submit", search);
$("book").addEventListener("submit", book);
$("lookup").addEventListener("submit", lookup);
$("cancelBook").onclick = () => ($("bookingCard").hidden = true);
loadFilters().then(search);
