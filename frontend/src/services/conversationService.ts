import type { ConversationCreated, ConversationDetail, ConversationList, VoiceSessionDescriptor } from "../types";
import { apiFetch } from "./apiClient";

export const conversationService = {
  /** This organization's saved conversations (calls and chats), newest first. */
  list: (offset = 0, limit = 30) => apiFetch<ConversationList>(`/api/conversations?limit=${limit}&offset=${offset}`),

  get: (id: string) => apiFetch<ConversationDetail>(`/api/conversations/${id}`),

  create: () => apiFetch<ConversationCreated>("/api/conversations", { method: "POST" }),

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
