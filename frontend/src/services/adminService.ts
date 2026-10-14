import type { Business, Domain, RequestStatus, UserDetail, UserList, UserRole } from "../types";
import { apiFetch } from "./apiClient";

export interface UserQuery {
  status?: RequestStatus;
  role?: UserRole;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface NewBusiness {
  name: string;
  domainId: string;
  adminName: string;
  adminEmail: string;
}

export const adminService = {
  listDomains: () => apiFetch<Domain[]>("/api/businesses/domains"),

  listBusinesses: (q = "") => apiFetch<Business[]>(`/api/superadmin/businesses${q ? `?q=${encodeURIComponent(q)}` : ""}`),

  createBusiness: (business: NewBusiness) =>
    apiFetch<Business>("/api/superadmin/businesses", { method: "POST", body: JSON.stringify(business) }),

  setBusinessActive: (id: string, isActive: boolean) =>
    apiFetch<Business>(`/api/superadmin/businesses/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ isActive }),
    }),

  listUsers(query: UserQuery = {}) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== "") params.set(key, String(value));
    }
    const qs = params.toString();
    return apiFetch<UserList>(`/api/superadmin/users${qs ? `?${qs}` : ""}`);
  },

  getUser: (id: string) => apiFetch<UserDetail>(`/api/superadmin/users/${encodeURIComponent(id)}`),
};
