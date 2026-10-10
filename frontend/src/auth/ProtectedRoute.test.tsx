import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { session } from "../services/apiClient";
import { AuthProvider } from "./AuthContext";
import { ProtectedRoute } from "./ProtectedRoute";

function user(role: "admin" | "superadmin") {
  return { id: "u1", name: "Asha", email: "a@x.com", role, status: "active", tenantId: null };
}

function mountAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<p>login page</p>} />
          <Route
            path="/superadmin"
            element={
              <ProtectedRoute roles={["superadmin"]}>
                <p>secret</p>
              </ProtectedRoute>
            }
          />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  beforeEach(() => session.setToken(null));
  afterEach(() => vi.restoreAllMocks());

  it("redirects anonymous visitors to /login", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 401 }));
    mountAt("/superadmin");
    expect(await screen.findByText("login page")).toBeInTheDocument();
  });

  it("shows access denied when the role does not match", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ accessToken: "t", user: user("admin") }), { status: 200 }),
    );
    mountAt("/superadmin");
    expect(await screen.findByText("Access denied")).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("renders the page for a permitted role restored from the refresh cookie", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ accessToken: "t", user: user("superadmin") }), { status: 200 }),
    );
    mountAt("/superadmin");
    await waitFor(() => expect(screen.getByText("secret")).toBeInTheDocument());
  });
});
