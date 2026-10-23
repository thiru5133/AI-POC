import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { session } from "../services/apiClient";
import { CallPage } from "./CallPage";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const item = (id: string, name: string, phone: string, domainName = "Hotels", isMarketplace = false) => ({
  id,
  name,
  phone,
  domainName,
  isMarketplace,
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/call" element={<CallPage />} />
        <Route path="/call/:id" element={<CallPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CallPage", () => {
  let fetchMock: MockInstance<typeof fetch>;
  beforeEach(() => {
    session.setToken(null); // a visitor is not logged in
    fetchMock = vi.spyOn(globalThis, "fetch");
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists the numbers by domain with a tap-to-call link, without any login", async () => {
    fetchMock.mockResolvedValueOnce(
      json([item("a", "Alpha Hotel", "+914412345678"), item("m", "All Hotels (compare)", "+17692630020", "Hotels", true), item("g", "FitZone", "+17372508034", "Fitness")]),
    );
    renderAt("/call");
    expect(await screen.findByText("Alpha Hotel")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "+17692630020" })).toHaveAttribute("href", "tel:+17692630020");
    expect(screen.getByText("Fitness")).toBeInTheDocument();
    expect(screen.getByText(/one line for every hotels/i)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/public/businesses");
    expect((init as RequestInit | undefined)?.headers).not.toHaveProperty("Authorization");
  });

  it("shows one business's number on its own page", async () => {
    fetchMock.mockResolvedValueOnce(json(item("a", "Alpha Hotel", "+914412345678")));
    renderAt("/call/a");
    expect(await screen.findByRole("link", { name: "+914412345678" })).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/public/businesses/a");
  });

  it("says so when there is no number to show", async () => {
    fetchMock.mockResolvedValueOnce(json({ error: { code: "not_found", message: "No phone number for that business" } }, 404));
    renderAt("/call/unknown");
    expect(await screen.findByText(/no phone number to show/i)).toBeInTheDocument();
  });
});
