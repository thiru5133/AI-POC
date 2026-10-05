import { useEffect, useRef } from "react";
import type { TranscriptEntry } from "../../types";

export function Transcript({ entries }: { entries: TranscriptEntry[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [entries]);

  if (entries.length === 0) {
    return <p className="transcript-empty">Press “Start call” and say hello — your conversation appears here.</p>;
  }
  return (
    <ul className="transcript" aria-label="Conversation transcript">
      {entries.map((e) => (
        <li key={e.id} className={`bubble ${e.role}${e.partial ? " partial" : ""}`}>
          <span className="who">{e.role === "user" ? "You" : "Receptionist"}</span>
          <span>{e.text}</span>
        </li>
      ))}
      <div ref={endRef} />
    </ul>
  );
}
