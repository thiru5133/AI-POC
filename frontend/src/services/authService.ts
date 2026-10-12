import type { AuthUser, LoginResponse, LoginResult } from "../types";
import { apiFetch, session } from "./apiClient";

export const authService = {
  register: (name: string, email: string, password: string) =>
    apiFetch<AuthUser>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ name, email, password }),
    }),

  /** On a first login there is no session yet: a code is emailed and `verifyOtp` completes the login. */
  async login(identifier: string, password: string): Promise<LoginResult> {
    const data = await apiFetch<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ identifier, password }),
    });
    if (data.otpRequired || !data.user) return { otpRequired: true, email: data.email ?? identifier };
    session.setToken(data.accessToken);
    return { user: data.user };
  },

  async verifyOtp(email: string, code: string): Promise<AuthUser> {
    const data = await apiFetch<LoginResponse>("/api/auth/verify-otp", {
      method: "POST",
      body: JSON.stringify({ email, code }),
    });
    session.setToken(data.accessToken);
    return data.user as AuthUser;
  },

  resendOtp: (email: string) =>
    apiFetch<{ status: string }>("/api/auth/resend-otp", { method: "POST", body: JSON.stringify({ email }) }),

  async logout(): Promise<void> {
    try {
      await apiFetch<void>("/api/auth/logout", { method: "POST" });
    } finally {
      session.setToken(null);
    }
  },

  me: () => apiFetch<AuthUser>("/api/auth/me"),
};
