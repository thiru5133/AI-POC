import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { session } from "../../services/apiClient";
import { BusinessesPage } from "./BusinessesPage";

const business = (id: string, name: string, isActive = true) => ({
  id,
  name,
  isActive,
  createdAt: "2026-10-10T10:00:00",
  domainId: "d1",
  domainName: "Hotels",
  adminName: "Owner",
  adminEmail: `owner@${id}.com`,
});

const DOMAINS = [{ id: "d1", key: "hotel", name: "Hotels", description: "" }, { id: "d2", key: "school", name: "Schools", description: "" }];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("BusinessesPage", () => {
  let fetchMock: MockInstance<typeof fetch>;

  beforeEach(() => {
    session.setToken("tok");
    fetchMock = vi.spyOn(globalThis, "fetch");
  });
  afterEach(() => vi.restoreAllMocks());

  it("creates a business with its admin and refreshes the list", async () => {
    fetchMock
      .mockResolvedValueOnce(json([business("a", "Alpha")]))
      .mockResolvedValueOnce(json(DOMAINS))
      .mockResolvedValueOnce(json(business("b", "Beta"), 201))
      .mockResolvedValueOnce(json([business("b", "Beta"), business("a", "Alpha")]));

    render(<BusinessesPage />);
    expect(await screen.findByText("Alpha")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/Business name/), "Beta");
    await userEvent.selectOptions(screen.getByLabelText(/Domain/), "d1");
    await userEvent.type(screen.getByLabelText("Admin name"), "Owner");
    await userEvent.type(screen.getByLabelText("Admin email"), "owner@b.com");
    await userEvent.click(screen.getByRole("button", { name: "Create business" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Beta was created");
    expect(await screen.findByText("Beta", { selector: "td" })).toBeInTheDocument();
    const [, init] = fetchMock.mock.calls[2];
    expect(JSON.parse(String(init?.body))).toEqual({ name: "Beta", domainId: "d1", adminName: "Owner", adminEmail: "owner@b.com" });
  });

  it("disables a business", async () => {
    fetchMock
      .mockResolvedValueOnce(json([business("a", "Alpha")]))
      .mockResolvedValueOnce(json(DOMAINS))
      .mockResolvedValueOnce(json(business("a", "Alpha", false)));

    render(<BusinessesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Disable" }));

    expect(await screen.findByRole("button", { name: "Enable" })).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls[2][0]).toBe("/api/superadmin/businesses/a"));
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({ isActive: false });
  });

  it("shows the server's error when creation fails", async () => {
    fetchMock
      .mockResolvedValueOnce(json([]))
      .mockResolvedValueOnce(json(DOMAINS))
      .mockResolvedValueOnce(json({ error: { code: "conflict", message: "A business with this name already exists", requestId: "r" } }, 409));

    render(<BusinessesPage />);
    await userEvent.type(await screen.findByLabelText(/Business name/), "Alpha");
    await userEvent.selectOptions(screen.getByLabelText(/Domain/), "d1");
    await userEvent.type(screen.getByLabelText("Admin name"), "Owner");
    await userEvent.type(screen.getByLabelText("Admin email"), "o@a.com");
    await userEvent.click(screen.getByRole("button", { name: "Create business" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
  });
});
