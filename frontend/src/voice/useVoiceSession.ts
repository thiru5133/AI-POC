import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, session as authSession } from "../services/apiClient";
import { conversationService } from "../services/conversationService";
import type { CallStatus, ServerEvent, TranscriptEntry } from "../types";
import { BrowserDeepgramClient } from "./BrowserDeepgramClient";
import type { VoiceClient } from "./VoiceClient";

export interface UseVoiceSessionOptions {
  createClient?: () => VoiceClient;
  toWsUrl?: (path: string) => string;
}

/** The server derives an admin's organization from this token; a customer also names the business they chose. */
const defaultWsUrl = (path: string) => {
  const token = authSession.getToken();
  const params = new URLSearchParams();
  if (token) params.set("token", token);
  const business = authSession.getBusiness();
  if (business) params.set("business", business);
  const query = params.size ? `?${params}` : "";
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}${query}`;
};

let counter = 0;
const nextId = () => `e${++counter}`;

export function useVoiceSession({ createClient, toWsUrl = defaultWsUrl }: UseVoiceSessionOptions = {}) {
  const [status, setStatus] = useState<CallStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [sending, setSending] = useState(false);
  const clientRef = useRef<VoiceClient | null>(null);
  const conversationRef = useRef<string | null>(null);
  const assistantEntryRef = useRef<string | null>(null);

  const addEntry = useCallback((entry: Omit<TranscriptEntry, "id">) => {
    const id = nextId();
    setTranscript((t) => [...t, { ...entry, id }]);
    return id;
  }, []);

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      switch (event.type) {
        case "transcript.partial":
          setStatus("listening");
          setTranscript((t) => {
            const last = t[t.length - 1];
            if (last?.partial) return [...t.slice(0, -1), { ...last, text: event.text }];
            return [...t, { id: nextId(), role: "user", text: event.text, partial: true }];
          });
          break;
        case "transcript.final":
          assistantEntryRef.current = null;
          setStatus("thinking");
          setTranscript((t) => {
            const last = t[t.length - 1];
            if (last?.partial) return [...t.slice(0, -1), { ...last, text: event.text, partial: false }];
            return [...t, { id: nextId(), role: "user", text: event.text }];
          });
          break;
        case "assistant.text": {
          setStatus("speaking");
          const existing = assistantEntryRef.current;
          if (existing) {
            setTranscript((t) =>
              t.map((e) => (e.id === existing ? { ...e, text: `${e.text} ${event.text}` } : e)),
            );
          } else {
            assistantEntryRef.current = addEntry({ role: "assistant", text: event.text });
          }
          break;
        }
        case "assistant.interrupt":
          assistantEntryRef.current = null;
          break;
        case "assistant.audio_end":
          assistantEntryRef.current = null;
          break;
        case "error":
          setError(event.message);
          break;
      }
    },
    [addEntry],
  );

  const stop = useCallback(() => {
    clientRef.current?.stop();
    clientRef.current = null;
    setStatus("idle");
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setStatus("connecting");
    try {
      const created = await conversationService.create();
      conversationRef.current = created.id;
      setTranscript([]);
      assistantEntryRef.current = null;
      const session = await conversationService.createVoiceSession(created.id);
      if (!session.wsPath) throw new Error("Voice provider did not return a WebSocket path.");
      const client = createClient?.() ?? new BrowserDeepgramClient(session.audio.mimeType);
      clientRef.current = client;
      await client.start(
        { wsUrl: toWsUrl(session.wsPath) },
        {
          onEvent: handleEvent,
          onPlaybackIdle: () => setStatus((s) => (s === "speaking" ? "listening" : s)),
          onClose: () => {
            clientRef.current = null;
            setStatus((s) => (s === "error" ? s : "idle"));
          },
          onError: (message) => {
            setError(message);
            setStatus("error");
          },
        },
      );
      setStatus("listening");
    } catch (err) {
      clientRef.current?.stop();
      clientRef.current = null;
      setError(err instanceof ApiError || err instanceof Error ? err.message : "Could not start the call.");
      setStatus("error");
    }
  }, [createClient, handleEvent, toWsUrl]);

  /** Text fallback over the REST path (same engine, no audio). */
  const sendText = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setError(null);
      setSending(true);
      try {
        let conversationId = conversationRef.current;
        if (!conversationId) {
          const created = await conversationService.create();
          conversationId = conversationRef.current = created.id;
          addEntry({ role: "assistant", text: created.greeting });
        }
        addEntry({ role: "user", text: trimmed });
        const { reply } = await conversationService.sendMessage(conversationId, trimmed);
        addEntry({ role: "assistant", text: reply });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Message failed.");
      } finally {
        setSending(false);
      }
    },
    [addEntry],
  );

  useEffect(() => () => clientRef.current?.stop(), []);

  return { status, error, transcript, sending, start, stop, sendText };
}
