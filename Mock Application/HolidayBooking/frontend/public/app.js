// Guest page: find a hotel by location and dates, book, and manage bookings by email.
let selected = null; // { hotel, type, checkIn, checkOut, nights }

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function loadLocations() {
  try {
    const hotels = await api("/api/hotels");
    const places = [...new Set(hotels.map((h) => `${h.city}|${h.country}`))].sort();
    for (const place of places) {
      const [city, country] = place.split("|");
      const option = el("option", "", `${city}, ${country}`);
      option.value = city;
      $("where").append(option);
    }
  } catch (err) {
    show($("searchError"), err.message);
  }
}

function renderResults(result) {
  const box = $("results");
  box.replaceChildren();
  if (!result.results.length) {
    box.append(el("p", "muted empty", "No hotels match that search."));
    return;
  }
  for (const { hotel, room_types: types } of result.results) {
    const card = el("div", "hotel");
    const head = el("div", "hotel-head");
    head.append(el("h3", "", hotel.name), el("span", "stars", stars(hotel.stars)));
    card.append(head, el("p", "muted", `${hotel.city}, ${hotel.country}`));
    for (const t of types) {
      const row = el("div", "room");
      const info = el("div");
      info.append(el("strong", "", t.name), el("p", "muted", `${t.description} · sleeps ${t.max_guests}`));
      const price = el("div", "price-col");
      price.append(
        el("span", "price", `${money(t.price_per_night)} / night`),
        el("span", "muted", `${money(t.total_for_stay)} for ${result.nights} night(s)`),
        el("span", t.available_rooms ? "ok" : "error", t.available_rooms ? `${t.available_rooms} of ${t.total_rooms} left` : "Sold out"),
      );
      const button = el("button", "primary", "Book");
      button.disabled = t.available_rooms === 0;
      button.onclick = () => startBooking(hotel, t, result);
      row.append(info, price, button);
      card.append(row);
    }
    box.append(card);
  }
}

function startBooking(hotel, type, result) {
  selected = { hotel, type, checkIn: result.check_in, checkOut: result.check_out, nights: result.nights };
  $("bookingTitle").textContent = `${type.name} room at ${hotel.name}`;
  $("guests").max = type.max_guests;
  $("bookingSummary").textContent =
    `${hotel.city} · ${result.check_in} → ${result.check_out} (${result.nights} night(s)) · total ${money(type.total_for_stay)}`;
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
    const params = new URLSearchParams({ check_in: $("checkIn").value, check_out: $("checkOut").value });
    if ($("where").value) params.set("city", $("where").value);
    renderResults(await api(`/api/availability?${params}`));
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
      hotel: selected.hotel.code,
      category: selected.type.code,
      guest_name: $("guestName").value,
      guest_email: $("guestEmail").value,
      check_in: selected.checkIn,
      check_out: selected.checkOut,
      guests: Number($("guests").value),
    });
    $("book").hidden = true;
    show($("bookOk"), `Booked! Reference ${booking.reference} · ${booking.hotel_name}, room ${booking.room_number} · ${money(booking.total_price)}`);
    $("lookupEmail").value = booking.guest_email;
    search();
    lookup();
  } catch (err) {
    show($("bookError"), err.message);
    search(); // availability may have changed
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
      el("strong", "", `${b.reference} · ${b.hotel_name} (${b.hotel_city}) · ${b.category_code} room ${b.room_number}`),
      el("p", "muted", `${b.guest_name} · ${b.check_in} → ${b.check_out} · ${money(b.total_price)} · ${b.status}`),
    );
    row.append(info);
    if (b.status === "confirmed") {
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
$("checkIn").min = $("checkOut").min = iso(today);
$("checkIn").value = iso(new Date(today.getTime() + 86400000));
$("checkOut").value = iso(new Date(today.getTime() + 3 * 86400000));
$("search").addEventListener("submit", search);
$("book").addEventListener("submit", book);
$("lookup").addEventListener("submit", lookup);
$("cancelBook").onclick = () => ($("bookingCard").hidden = true);
loadLocations().then(search);
