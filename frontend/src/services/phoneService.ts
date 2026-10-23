import type { PhoneSettings } from "../types";
import { apiFetch } from "./apiClient";

export const phoneService = {
  get: () => apiFetch<PhoneSettings>("/api/org/phone"),

  /** An empty `number` removes the business's phone number. */
  save: (number: string, transferNumber: string) =>
    apiFetch<PhoneSettings>("/api/org/phone", {
      method: "PUT",
      body: JSON.stringify({ number: number.trim() || null, transferNumber: transferNumber.trim() || null }),
    }),
};
