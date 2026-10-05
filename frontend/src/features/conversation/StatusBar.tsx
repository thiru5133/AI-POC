import type { CallStatus } from "../../types";

const LABELS: Record<CallStatus, string> = {
  idle: "Ready",
  connecting: "Connecting…",
  listening: "Listening",
  thinking: "Thinking…",
  speaking: "Speaking",
  error: "Error",
};

export function StatusBar({ status, error }: { status: CallStatus; error: string | null }) {
  return (
    <div className="status-bar">
      <span className={`dot ${status}`} aria-hidden />
      <span role="status">{LABELS[status]}</span>
      {error && (
        <span role="alert" className="error">
          {error}
        </span>
      )}
    </div>
  );
}
