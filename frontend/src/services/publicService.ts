import type { PublicNumber } from "../types";
import { apiFetch } from "./apiClient";

/** Pages that need no login: who a customer can phone. */
export const publicService = {
  listNumbers: () => apiFetch<PublicNumber[]>("/api/public/businesses"),
  getNumber: (id: string) => apiFetch<PublicNumber>(`/api/public/businesses/${encodeURIComponent(id)}`),
};
