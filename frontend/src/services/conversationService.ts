import type { ConversationCreated, VoiceSessionDescriptor } from "../types";
import { apiFetch } from "./apiClient";

export const conversationService = {
  create: () =>
    apiFetch<ConversationCreated>("/api/conversations", { method: "POST", body: JSON.stringify({}) }),

  sendMessage: (conversationId: string, text: string) =>
    apiFetch<{ reply: string }>(`/api/conversations/${conversationId}/messages`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  createVoiceSession: (conversationId: string) =>
    apiFetch<VoiceSessionDescriptor>("/api/voice/session", {
      method: "POST",
      body: JSON.stringify({ conversationId }),
    }),
};
