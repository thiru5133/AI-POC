import type { RequestStatus } from "../types";

export function StatusBadge({ status }: { status: RequestStatus }) {
  return <span className={`status-badge ${status}`}>{status}</span>;
}
