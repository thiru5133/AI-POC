import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { session } from "../../services/apiClient";
import { UsersPage } from "./UsersPage";

const user = (id: string, name: string, status = "active", role = "admin") => ({
  id,
  name,
  email: `${name.split(" ")[0].toLowerCase()}@x.com`,
  role,
  status,
  tenantId: "t1",
  createdAt: "2026-10-10T10:00:00",
});

const COUNTS = { active: 2, pending: 1, rejected: 0, disabled: 0 };

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("UsersPage", () => {
  let fetchMock: MockInstance<typeof fetch>;
  const urls = () => fetchMock.mock.calls.map(([u]) => String(u));

  beforeEach(() => {
    session.setToken("tok");
    fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input), "http://x");
      if (url.pathname === "/api/admin/users") {
        const status = url.searchParams.get("status");
        const q = url.searchParams.get("q")?.toLowerCase();
        const all = [user("1", "Asha Rao"), user("2", "Bala Kumar"), user("3", "Chitra Devi", "pending")];
        const items = all.filter((u) => (!status || u.status === status) && (!q || u.name.toLowerCase().includes(q)));
        return json({ items, total: items.length, limit: 20, offset: 0, counts: COUNTS });
      }
      if (url.pathname === "/api/admin/users/3") {
        return json({
          ...user("3", "Chitra Devi", "rejected"),
          tenantName: null,
          rejectionReason: "Not a customer",
          reviewedByName: "Root",
          reviewedAt: "2026-10-11T08:00:00",
        });
      }
      return json({}, 404);
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows active users by default with a count on every tab", async () => {
    render(<UsersPage />);
    expect(await screen.findByText("Asha Rao")).toBeInTheDocument();
    expect(screen.getByText("Bala Kumar")).toBeInTheDocument();
    expect(screen.queryByText("Chitra Devi")).not.toBeInTheDocument();
    expect(urls()[0]).toContain("status=active");

    const tabs = within(screen.getByRole("tablist", { name: "Filter by status" }));
    expect(tabs.getByRole("tab", { name: /Active/ })).toHaveAttribute("aria-selected", "true");
    expect(tabs.getByRole("tab", { name: /Pending/ })).toHaveTextContent("1");
    expect(tabs.getByRole("tab", { name: /All/ })).toHaveTextContent("3");
  });

  it("filters by status tab", async () => {
    render(<UsersPage />);
    await screen.findByText("Asha Rao");
    await userEvent.click(screen.getByRole("tab", { name: /Pending/ }));

    expect(await screen.findByText("Chitra Devi")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Asha Rao")).not.toBeInTheDocument());
    expect(urls().at(-1)).toContain("status=pending");
  });

  it("passes the role filter and drops the status filter on All", async () => {
    render(<UsersPage />);
    await screen.findByText("Asha Rao");
    await userEvent.click(screen.getByRole("tab", { name: /All/ }));
    await userEvent.selectOptions(screen.getByLabelText("Filter by role"), "superadmin");

    await waitFor(() => expect(urls().at(-1)).toContain("role=superadmin"));
    expect(urls().at(-1)).not.toContain("status=");
  });

  it("searches after a short pause", async () => {
    render(<UsersPage />);
    await screen.findByText("Asha Rao");
    await userEvent.type(screen.getByLabelText("Search users"), "bala");

    await waitFor(() => expect(screen.queryByText("Asha Rao")).not.toBeInTheDocument());
    expect(screen.getByText("Bala Kumar")).toBeInTheDocument();
    expect(urls().at(-1)).toContain("q=bala");
  });

  it("shows an empty state", async () => {
    render(<UsersPage />);
    await screen.findByText("Asha Rao");
    await userEvent.type(screen.getByLabelText("Search users"), "zzz");
    expect(await screen.findByText("No users match these filters.")).toBeInTheDocument();
  });

  it("opens a details panel and closes it", async () => {
    render(<UsersPage />);
    await userEvent.click(await screen.findByRole("tab", { name: /All/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Chitra Devi" }));

    const panel = await screen.findByRole("dialog", { name: "User details" });
    expect(await within(panel).findByText("Not a customer")).toBeInTheDocument();
    expect(within(panel).getByText("Root")).toBeInTheDocument();
    expect(urls().at(-1)).toBe("/api/admin/users/3");

    await userEvent.click(within(panel).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the API error", async () => {
    fetchMock.mockImplementation(async () =>
      json({ error: { code: "forbidden", message: "You do not have access to this resource", requestId: "r" } }, 403),
    );
    render(<UsersPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("You do not have access");
  });
});
