import type { ServerEvent } from "../types";

export interface VoiceClientHandlers {
  onEvent(event: ServerEvent): void;
  /** Audio finished playing / was stopped. */
  onPlaybackIdle(): void;
  onClose(): void;
  onError(message: string): void;
}

/**
 * Provider-neutral client contract used by the UI. BrowserDeepgramClient implements it today
 * (mic + WebSocket to our backend); a Vapi/Twilio web client can implement the same interface later.
 */
export interface VoiceClient {
  start(session: { wsUrl: string }, handlers: VoiceClientHandlers): Promise<void>;
  stop(): void;
}

export class MicrophoneError extends Error {
  constructor(
    message: string,
    public readonly reason: "denied" | "unsupported" | "unavailable",
  ) {
    super(message);
  }
}
