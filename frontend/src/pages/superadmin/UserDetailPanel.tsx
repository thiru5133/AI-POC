import { type FormEvent, useEffect, useState } from "react";
import { StatusBadge } from "../../components/StatusBadge";
import { adminService } from "../../services/adminService";
import { ApiError } from "../../services/apiClient";
import type { UserDetail } from "../../types";
import { formatDateTime } from "../../utils/date";

export function UserDetailPanel({
  userId,
  onClose,
  onSaved,
}: {
  userId: string;
  onClose: () => void;
  onSaved?: (user: UserDetail) => void;
}) {
  const [user, setUser] = useState<UserDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", businessName: "" });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setUser(null);
    setError(null);
    setEditing(false);
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

  const startEdit = () => {
    if (!user) return;
    setForm({ name: user.name, email: user.email, businessName: user.tenantName ?? "" });
    setError(null);
    setEditing(true);
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!user) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await adminService.updateUser(user.id, {
        name: form.name,
        email: form.email,
        ...(user.tenantName !== null ? { businessName: form.businessName } : {}),
      });
      setUser(updated);
      setEditing(false);
      onSaved?.(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save changes");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <button type="button" className="scrim panel-scrim" aria-label="Close details" onClick={onClose} />
      <aside className="detail-panel" role="dialog" aria-label="User details">
        <div className="detail-header">
          <h2>{user?.name ?? "User details"}</h2>
          {user && !editing && (
            <button type="button" className="secondary small" onClick={startEdit}>
              Edit
            </button>
          )}
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
        {user && editing && (
          <form className="form" onSubmit={save}>
            <label>
              Name
              <input required maxLength={200} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label>
              Email
              <input
                type="email"
                required
                autoComplete="off"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </label>
            {user.tenantName !== null && (
              <label>
                Business
                <input
                  required
                  maxLength={200}
                  value={form.businessName}
                  onChange={(e) => setForm({ ...form, businessName: e.target.value })}
                />
              </label>
            )}
            <div className="actions">
              <button type="submit" className="primary" disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </button>
              <button type="button" className="secondary" disabled={saving} onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
          </form>
        )}
        {user && !editing && (
          <dl className="detail-list">
            <dt>Status</dt>
            <dd>
              <StatusBadge status={user.status} />
            </dd>
            <dt>Email</dt>
            <dd>{user.email}</dd>
            <dt>Role</dt>
            <dd>{{ superadmin: "Super admin", admin: "Business admin", user: "User" }[user.role]}</dd>
            <dt>Business</dt>
            <dd>{user.tenantName ?? "—"}</dd>
            <dt>Joined</dt>
            <dd>{formatDateTime(user.createdAt)}</dd>
            <dt>User ID</dt>
            <dd className="mono">{user.id}</dd>
          </dl>
        )}
      </aside>
    </>
  );
}
