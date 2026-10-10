import { useEffect, useState } from "react";
import { StatusBadge } from "../../components/StatusBadge";
import { adminService } from "../../services/adminService";
import { ApiError } from "../../services/apiClient";
import type { UserDetail } from "../../types";
import { formatDateTime } from "../../utils/date";

export function UserDetailPanel({ userId, onClose }: { userId: string; onClose: () => void }) {
  const [user, setUser] = useState<UserDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setUser(null);
    setError(null);
    adminService
      .getUser(userId)
      .then((data) => !cancelled && setUser(data))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not load user"));
    return () => {
      cancelled = true;
    };
  }, [userId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <button type="button" className="scrim panel-scrim" aria-label="Close details" onClick={onClose} />
      <aside className="detail-panel" role="dialog" aria-label="User details">
        <div className="detail-header">
          <h2>{user?.name ?? "User details"}</h2>
          <button type="button" className="icon-button" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!user && !error && <p className="muted">Loading…</p>}
        {user && (
          <dl className="detail-list">
            <dt>Status</dt>
            <dd>
              <StatusBadge status={user.status} />
            </dd>
            <dt>Email</dt>
            <dd>{user.email}</dd>
            <dt>Role</dt>
            <dd>{user.role === "superadmin" ? "Super admin" : "Admin"}</dd>
            <dt>Tenant</dt>
            <dd>{user.tenantName ?? "—"}</dd>
            <dt>Requested</dt>
            <dd>{formatDateTime(user.createdAt)}</dd>
            <dt>Reviewed by</dt>
            <dd>{user.reviewedByName ?? "—"}</dd>
            <dt>Reviewed at</dt>
            <dd>{formatDateTime(user.reviewedAt)}</dd>
            {user.rejectionReason && (
              <>
                <dt>Rejection reason</dt>
                <dd>{user.rejectionReason}</dd>
              </>
            )}
            <dt>User ID</dt>
            <dd className="mono">{user.id}</dd>
          </dl>
        )}
      </aside>
    </>
  );
}
