import type { AuthUser, LoginResponse } from "../types";
import { apiFetch, session } from "./apiClient";

export const authService = {
  register: (name: string, email: string, organizationName: string) =>
    apiFetch<{ status: string }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ name, email, organizationName }),
    }),

  async login(identifier: string, password: string): Promise<AuthUser> {
    const data = await apiFetch<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ identifier, password }),
    });
    session.setToken(data.accessToken);
    return data.user;
  },

  async logout(): Promise<void> {
    try {
      await apiFetch<void>("/api/auth/logout", { method: "POST" });
    } finally {
      session.setToken(null);
    }
  },

  me: () => apiFetch<AuthUser>("/api/auth/me"),
};
