export interface TranscriptEntry {
  id: string;
  role: "user" | "assistant";
  text: string;
  partial?: boolean;
}

export interface ConversationCreated {
  id: string;
  greeting: string;
}

export interface VoiceSessionDescriptor {
  conversationId: string;
  transport: string;
  wsPath: string | null;
  audio: { mimeType: string };
}

export interface ApiErrorBody {
  error: { code: string; message: string; requestId: string };
}

/** Server -> client WebSocket events. */
export type ServerEvent =
  | { type: "transcript.partial"; text: string }
  | { type: "transcript.final"; text: string }
  | { type: "assistant.text"; text: string }
  | { type: "assistant.audio_end" }
  | { type: "assistant.interrupt" }
  | { type: "error"; code: string; message: string };

export type CallStatus =
  | "idle"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "error";
