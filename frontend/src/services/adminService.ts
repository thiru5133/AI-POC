import type { OnboardingRequest, RequestStatus, UserDetail, UserList, UserRole } from "../types";
import { apiFetch } from "./apiClient";

export interface UserQuery {
  status?: RequestStatus;
  role?: UserRole;
  q?: string;
  limit?: number;
  offset?: number;
}

export const adminService = {
  listRequests: (status: RequestStatus = "pending") =>
    apiFetch<OnboardingRequest[]>(`/api/admin/onboarding-requests?status=${status}`),

  approve: (id: string) =>
    apiFetch<OnboardingRequest>(`/api/admin/onboarding-requests/${id}/approve`, { method: "POST" }),

  reject: (id: string, reason?: string) =>
    apiFetch<OnboardingRequest>(`/api/admin/onboarding-requests/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason: reason || null }),
    }),

  listUsers(query: UserQuery = {}) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== "") params.set(key, String(value));
    }
    const qs = params.toString();
    return apiFetch<UserList>(`/api/admin/users${qs ? `?${qs}` : ""}`);
  },

  getUser: (id: string) => apiFetch<UserDetail>(`/api/admin/users/${encodeURIComponent(id)}`),
};
