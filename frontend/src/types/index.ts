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

export type UserRole = "superadmin" | "admin" | "user";

export interface AuthUser {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  status: string;
  tenantId: string | null;
}

/** `accessToken`/`user` are null on a first login: a code was emailed and must be verified first. */
export interface LoginResponse {
  accessToken: string | null;
  user: AuthUser | null;
  otpRequired: boolean;
  email: string | null;
}

export type LoginResult = { user: AuthUser } | { otpRequired: true; email: string };

export interface Domain {
  id: string;
  key: string;
  name: string;
  description: string;
}

export type RequestStatus = "pending" | "active" | "rejected" | "disabled";

export interface Business {
  id: string;
  name: string;
  isActive: boolean;
  createdAt: string;
  domainId: string | null;
  domainName: string | null;
  adminName: string | null;
  adminEmail: string | null;
}

export interface BusinessPublic {
  id: string;
  name: string;
  domainName: string | null;
  /** The domain's shared assistant that compares all of its partners. */
  isMarketplace: boolean;
  /** The number customers dial to reach it; null when none is set. */
  phone: string | null;
}

/** What the no-login page shows. */
export interface PublicNumber {
  id: string;
  name: string;
  domainName: string | null;
  isMarketplace: boolean;
  phone: string;
}

/** A domain and the number of its shared (compare-all) line. */
export interface DomainNumber {
  id: string;
  key: string;
  name: string;
  number: string | null;
  transferNumber: string | null;
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
}

export type McpTransport = "streamable_http" | "sse";

export interface McpHeader {
  name: string;
  secret: boolean;
  /** null for secret headers: the server never sends them back. */
  value: string | null;
  hasValue: boolean;
}

export interface McpServer {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  headers: McpHeader[];
  transport: McpTransport;
  timeoutSeconds: number;
  createdAt: string;
}

export interface McpTestResult {
  ok: boolean;
  error: string | null;
  tools: { name: string; description: string }[];
}

export interface ConversationSummary {
  id: string;
  startedAt: string;
  status: string;
  /** normal | frustrated | urgent | emergency, as flagged by the assistant. */
  urgency?: "normal" | "frustrated" | "urgent" | "emergency";
  /** The caller asked for a person (or was flagged urgent). */
  handoffRequested?: boolean;
  messageCount: number;
  lastMessageAt: string | null;
  /** The caller's first message. */
  preview: string;
}

export interface PhoneSettings {
  number: string | null;
  transferNumber: string | null;
  /** Which service connects the number to this server. */
  provider: "vapi" | "twilio";
  /** The URL to paste into that service (Vapi's server URL, or Twilio's "A call comes in" webhook); null until the server knows its public URL. */
  webhookUrl: string | null;
  /** The business's domain and the number of that domain's shared line (set by a superadmin); null when there is none. */
  domainName: string | null;
  domainNumber: string | null;
  /** The no-login page that shows this business's number, for sharing; null while no number is set. */
  publicUrl: string | null;
  /** The server has a public URL and the provider's credentials, so calls can actually reach it. */
  ready: boolean;
}

export interface Usage {
  periodDays: number;
  conversations: number;
  messages: number;
  voiceMinutes: number;
  toolCalls: number;
  /** Estimated from tool names, so a differently named booking tool is under-counted. */
  bookings: number;
  confirmations: number;
}

export interface ConversationList {
  items: ConversationSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ConversationMessage {
  role: "user" | "assistant";
  text: string;
  intent: string | null;
  createdAt: string;
}

export interface ConversationDetail {
  id: string;
  status: string;
  startedAt: string;
  messages: ConversationMessage[];
}
