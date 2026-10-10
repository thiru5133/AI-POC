import { useState, type FormEvent } from "react";
import { useVoiceSession, type UseVoiceSessionOptions } from "../../voice/useVoiceSession";
import { MicButton } from "./MicButton";
import { StatusBar } from "./StatusBar";
import { Transcript } from "./Transcript";

export function VoiceConsole(props: UseVoiceSessionOptions) {
  const { status, error, transcript, sending, start, stop, sendText } = useVoiceSession(props);
  const [draft, setDraft] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void sendText(draft);
    setDraft("");
  };

  return (
    <section className="console card">
      <div className="console-controls">
        <StatusBar status={status} error={error} />
        <MicButton status={status} onStart={() => void start()} onStop={stop} />
      </div>
      <Transcript entries={transcript} />
      <form className="text-fallback" onSubmit={submit}>
        <input
          aria-label="Type a message"
          placeholder="Or type a message…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={sending}
        />
        <button type="submit" className="primary" disabled={sending || !draft.trim()}>
          {sending ? "Sending…" : "Send"}
        </button>
      </form>
    </section>
  );
}
