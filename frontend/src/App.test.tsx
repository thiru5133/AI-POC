import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { session } from "./services/apiClient";

type Role = "admin" | "superadmin" | "user" | null;

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

  it("keeps the chat off the landing page: /chat needs a login", async () => {
    mockBackend(null);
    mountAt("/chat");
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("shows business admins their dashboard, MCP, conversations and chat", async () => {
    mockBackend("admin");
    mountAt("/admin");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    const nav = screen.getByRole("complementary", { name: "Main navigation" });
    expect(nav).toHaveTextContent("Dashboard");
    expect(nav).toHaveTextContent("Chat & voice");
    expect(nav).toHaveTextContent("MCP integration");
    expect(nav).toHaveTextContent("Conversations");
    expect(nav).not.toHaveTextContent("Businesses");
    expect(nav).toHaveTextContent("Asha Rao");
  });

  it("blocks admins from superadmin pages", async () => {
    mockBackend("admin");
    mountAt("/superadmin/businesses");
    expect(await screen.findByText("Access denied")).toBeInTheDocument();
  });

  it("lands superadmins on the businesses page from /", async () => {
    mockBackend("superadmin");
    mountAt("/");
    expect(await screen.findByRole("heading", { name: "Businesses" })).toBeInTheDocument();
    const nav = screen.getByRole("complementary", { name: "Main navigation" });
    expect(nav).toHaveTextContent("Users");
    expect(nav).not.toHaveTextContent("Chat & voice"); // superadmins have no business to talk to
    expect(nav).not.toHaveTextContent("Dashboard");
  });

  it("lands customers on the chat and keeps them out of admin pages", async () => {
    mockBackend("user");
    mountAt("/");
    expect(await screen.findByRole("heading", { name: "Chat with a business" })).toBeInTheDocument();
    const nav = screen.getByRole("complementary", { name: "Main navigation" });
    expect(nav).toHaveTextContent("Chat & voice");
    expect(nav).toHaveTextContent("My conversations");
    expect(nav).not.toHaveTextContent("MCP integration");
    expect(nav).not.toHaveTextContent("Businesses");
  });

  it("blocks customers from the admin dashboard", async () => {
    mockBackend("user");
    mountAt("/admin");
    expect(await screen.findByText("Access denied")).toBeInTheDocument();
  });
});
