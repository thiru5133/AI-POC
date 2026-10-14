import type { BusinessPublic } from "../types";
import { apiFetch } from "./apiClient";

export const businessService = {
  /** The businesses a customer can talk to. */
  listActive: () => apiFetch<BusinessPublic[]>("/api/businesses"),
};
