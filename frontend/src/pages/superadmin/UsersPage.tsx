import { useEffect, useState } from "react";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { adminService } from "../../services/adminService";
import { ApiError } from "../../services/apiClient";
import type { RequestStatus, UserList, UserRole } from "../../types";
import { formatDateTime } from "../../utils/date";
import { UserDetailPanel } from "./UserDetailPanel";

const PAGE_SIZE = 20;
const roleLabel = (role: UserRole) => ({ superadmin: "Super admin", admin: "Business admin", user: "User" })[role];
const TABS: { value: RequestStatus | "all"; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "pending", label: "Pending" },
  { value: "rejected", label: "Rejected" },
  { value: "disabled", label: "Disabled" },
  { value: "all", label: "All" },
];

export function UsersPage() {
  const [status, setStatus] = useState<RequestStatus | "all">("active");
  const [role, setRole] = useState<UserRole | "all">("all");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState(""); // debounced copy of `search`
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<UserList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(search.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    let cancelled = false; // ignore out-of-order responses while filters change quickly
    setError(null);
    adminService
      .listUsers({
        status: status === "all" ? undefined : status,
        role: role === "all" ? undefined : role,
        q,
        limit: PAGE_SIZE,
        offset,
      })
      .then((result) => !cancelled && setData(result))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not load users"));
    return () => {
      cancelled = true;
    };
  }, [status, role, q, offset]);

  const counts = data?.counts ?? {};
  const countFor = (tab: RequestStatus | "all") =>
    tab === "all" ? Object.values(counts).reduce((a, b) => a + (b ?? 0), 0) : (counts[tab] ?? 0);
  const total = data?.total ?? 0;
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + PAGE_SIZE, total);

  return (
    <>
      <PageHeader title="Users" subtitle="Business admins and users on the platform" />

      <div className="card table-card">
        <div className="filters">
          <div className="tabs" role="tablist" aria-label="Filter by status">
            {TABS.map((tab) => (
              <button
                key={tab.value}
                type="button"
                role="tab"
                aria-selected={status === tab.value}
                className={`tab${status === tab.value ? " active" : ""}`}
                onClick={() => {
                  setStatus(tab.value);
                  setOffset(0);
                }}
              >
                {tab.label}
                <span className="tab-count">{countFor(tab.value)}</span>
              </button>
            ))}
          </div>
          <div className="filter-inputs">
            <input
              type="search"
              aria-label="Search users"
              placeholder="Search name or email…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select
              aria-label="Filter by role"
              value={role}
              onChange={(e) => {
                setRole(e.target.value as UserRole | "all");
                setOffset(0);
              }}
            >
              <option value="all">All roles</option>
              <option value="admin">Business admin</option>
              <option value="user">User</option>
              <option value="superadmin">Super admin</option>
            </select>
          </div>
        </div>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!data && !error && <p className="muted">Loading…</p>}
        {data && data.items.length === 0 && <p className="muted empty">No users match these filters.</p>}
        {data && data.items.length > 0 && (
          <div className="table-scroll">
            <table className="table clickable">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Joined</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((u) => (
                  <tr key={u.id} onClick={() => setSelectedId(u.id)}>
                    <td>
                      <button type="button" className="link-button" onClick={() => setSelectedId(u.id)}>
                        {u.name}
                      </button>
                    </td>
                    <td>{u.email}</td>
                    <td>{roleLabel(u.role)}</td>
                    <td>
                      <StatusBadge status={u.status} />
                    </td>
                    <td>{formatDateTime(u.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data && total > 0 && (
          <div className="pager">
            <span className="muted">
              {first}–{last} of {total}
            </span>
            <div className="pager-buttons">
              <button
                type="button"
                className="secondary small"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </button>
              <button
                type="button"
                className="secondary small"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {selectedId && (
        <UserDetailPanel
          userId={selectedId}
          onClose={() => setSelectedId(null)}
          onSaved={(updated) =>
            setData((d) =>
              d && { ...d, items: d.items.map((u) => (u.id === updated.id ? { ...u, name: updated.name, email: updated.email } : u)) }
            )
          }
        />
      )}
    </>
  );
}
