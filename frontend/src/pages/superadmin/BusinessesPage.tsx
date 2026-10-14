import { useCallback, useEffect, useState, type FormEvent } from "react";
import { PageHeader } from "../../components/PageHeader";
import { adminService } from "../../services/adminService";
import { ApiError } from "../../services/apiClient";
import type { Business, Domain } from "../../types";
import { formatDateTime } from "../../utils/date";

const EMPTY = { name: "", domainId: "", adminName: "", adminEmail: "" };

/** Superadmin: onboard the businesses (tenants) that use the platform, and switch them on or off. */
export function BusinessesPage() {
  const [businesses, setBusinesses] = useState<Business[] | null>(null);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setBusinesses(await adminService.listBusinesses());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load businesses");
    }
  }, []);

  useEffect(() => {
    void load();
    adminService
      .listDomains()
      .then(setDomains)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load domains"));
  }, [load]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setCreating(true);
    try {
      const created = await adminService.createBusiness(form);
      setNotice(`${created.name} was created. Login details were emailed to ${created.adminEmail}.`);
      setForm(EMPTY);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the business");
    } finally {
      setCreating(false);
    }
  }

  async function toggle(business: Business) {
    setBusyId(business.id);
    setError(null);
    try {
      const updated = await adminService.setBusinessActive(business.id, !business.isActive);
      setBusinesses((current) => current?.map((b) => (b.id === updated.id ? updated : b)) ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  const set = (key: "name" | "adminName" | "adminEmail") => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: e.target.value });

  return (
    <>
      <PageHeader
        title="Businesses"
        subtitle="Onboard the businesses that use the AI assistant for enquiries and bookings"
        actions={businesses ? <span className="badge">{businesses.length} total</span> : undefined}
      />

      <form className="card form" onSubmit={create}>
        <h2>Add a business</h2>
        <p className="muted">
          We create the business and its admin account, and email the admin a password to log in with.
        </p>
        <label>
          Business name (shown to customers)
          <input required maxLength={200} value={form.name} onChange={set("name")} />
        </label>
        <label>
          Domain (each business belongs to exactly one)
          <select
            required
            value={form.domainId}
            onChange={(e) => setForm({ ...form, domainId: e.target.value })}
          >
            <option value="">Select a domain…</option>
            {domains.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Admin name
          <input required maxLength={200} value={form.adminName} onChange={set("adminName")} />
        </label>
        <label>
          Admin email
          <input type="email" required autoComplete="off" value={form.adminEmail} onChange={set("adminEmail")} />
        </label>
        <button type="submit" className="primary" disabled={creating}>
          {creating ? "Creating…" : "Create business"}
        </button>
      </form>

      {notice && (
        <p className="success" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <div className="card table-card">
        {businesses === null && !error && <p className="muted">Loading…</p>}
        {businesses?.length === 0 && <p className="muted empty">No businesses yet.</p>}
        {businesses && businesses.length > 0 && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Business</th>
                  <th>Domain</th>
                  <th>Admin</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {businesses.map((b) => (
                  <tr key={b.id}>
                    <td>{b.name}</td>
                    <td>{b.domainName ?? "—"}</td>
                    <td>{b.adminEmail ? `${b.adminName} (${b.adminEmail})` : "—"}</td>
                    <td>
                      <span className={`status-badge ${b.isActive ? "active" : "disabled"}`}>
                        {b.isActive ? "active" : "disabled"}
                      </span>
                    </td>
                    <td>{formatDateTime(b.createdAt)}</td>
                    <td className="actions">
                      <button
                        type="button"
                        className="secondary small"
                        disabled={busyId === b.id}
                        onClick={() => void toggle(b)}
                      >
                        {b.isActive ? "Disable" : "Enable"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
