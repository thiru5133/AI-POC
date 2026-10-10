import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { session } from "./services/apiClient";

type Role = "admin" | "superadmin" | null;

function mockBackend(role: Role) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/auth/refresh") {
      if (!role) return new Response("{}", { status: 401 });
      const user = { id: "u1", name: "Asha Rao", email: "a@x.com", role, status: "active", tenantId: null };
      return new Response(JSON.stringify({ accessToken: "t", user }), { status: 200 });
    }
    return new Response("[]", { status: 200 });
  });
}

function mountAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("routing and sidebar", () => {
  beforeEach(() => session.setToken(null));
  afterEach(() => vi.restoreAllMocks());

  it("sends anonymous visitors from / to the login screen, without a sidebar", async () => {
    mockBackend(null);
    mountAt("/");
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main navigation" })).not.toBeInTheDocument();
  });

  it("keeps the call console off the landing page: /call needs a login", async () => {
    mockBackend(null);
    mountAt("/call");
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("shows admins the dashboard and live call links only", async () => {
    mockBackend("admin");
    mountAt("/admin");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    const nav = screen.getByRole("complementary", { name: "Main navigation" });
    expect(nav).toHaveTextContent("Dashboard");
    expect(nav).toHaveTextContent("Live call");
    expect(nav).not.toHaveTextContent("Onboarding requests");
    expect(nav).toHaveTextContent("Asha Rao");
  });

  it("blocks admins from superadmin pages", async () => {
    mockBackend("admin");
    mountAt("/superadmin/requests");
    expect(await screen.findByText("Access denied")).toBeInTheDocument();
  });

  it("lands superadmins on the requests page from /", async () => {
    mockBackend("superadmin");
    mountAt("/");
    expect(await screen.findByRole("heading", { name: "Onboarding requests" })).toBeInTheDocument();
    const nav = screen.getByRole("complementary", { name: "Main navigation" });
    expect(nav).toHaveTextContent("Onboarding requests");
    expect(nav).toHaveTextContent("Live call");
    expect(nav).not.toHaveTextContent("Dashboard");
  });
});
