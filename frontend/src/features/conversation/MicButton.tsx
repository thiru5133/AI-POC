import type { CallStatus } from "../../types";

export function MicButton({ status, onStart, onStop }: { status: CallStatus; onStart(): void; onStop(): void }) {
  const active = status !== "idle" && status !== "error";
  const connecting = status === "connecting";
  return (
    <button
      type="button"
      className={`mic-button ${active ? "active" : ""}`}
      onClick={active ? onStop : onStart}
      disabled={connecting}
    >
      {connecting ? "Connecting…" : active ? "End call" : "Start call"}
    </button>
  );
}
