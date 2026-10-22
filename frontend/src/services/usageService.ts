import type { Usage } from "../types";
import { apiFetch } from "./apiClient";

export const usageService = {
  /** This business's metered usage over the last `days` days. */
  get: (days = 30) => apiFetch<Usage>(`/api/org/usage?days=${days}`),
};
