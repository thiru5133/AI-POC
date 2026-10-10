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

export type UserRole = "superadmin" | "admin";

export interface AuthUser {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  status: string;
  tenantId: string | null;
}

export interface LoginResponse {
  accessToken: string;
  user: AuthUser;
}

export type RequestStatus = "pending" | "active" | "rejected" | "disabled";

export interface OnboardingRequest {
  id: string;
  name: string;
  email: string;
  status: RequestStatus;
  rejectionReason: string | null;
  createdAt: string;
  reviewedAt: string | null;
}

export interface UserSummary {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  status: RequestStatus;
  tenantId: string | null;
  createdAt: string;
}

export interface UserList {
  items: UserSummary[];
  total: number;
  limit: number;
  offset: number;
  counts: Partial<Record<RequestStatus, number>>;
}

export interface UserDetail extends UserSummary {
  tenantName: string | null;
  rejectionReason: string | null;
  reviewedByName: string | null;
  reviewedAt: string | null;
}
