import { useEffect, useState, type FormEvent } from "react";
import { PageHeader } from "../../components/PageHeader";
import { adminService } from "../../services/adminService";
import { ApiError } from "../../services/apiClient";
import type { DomainNumber } from "../../types";

function DomainRow({ domain }: { domain: DomainNumber }) {
  const [number, setNumber] = useState(domain.number ?? "");
  const [transfer, setTransfer] = useState(domain.transferNumber ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const updated = await adminService.setDomainNumber(domain.id, number, transfer);
      setNumber(updated.number ?? "");
      setTransfer(updated.transferNumber ?? "");
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the number");
    } finally {
      setSaving(false);
    }
  }

  return (
    <tr>
      <td>{domain.name}</td>
      <td>
        <form className="inline-form" onSubmit={save}>
          <input
            aria-label={`${domain.name} number`}
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            placeholder="+14155550100"
            inputMode="tel"
          />
          <input
            aria-label={`${domain.name} transfer number`}
            value={transfer}
            onChange={(e) => setTransfer(e.target.value)}
            placeholder="Transfer to a person (optional)"
            inputMode="tel"
          />
          <button type="submit" className="secondary small" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
          {saved && <span role="status">Saved.</span>}
          {error && (
            <span className="error" role="alert">
              {error}
            </span>
          )}
        </form>
      </td>
    </tr>
  );
}

/** Superadmin: the shared phone line of each domain. Its compare-all assistant has no admin of its own. */
export function DomainNumbersPage() {
  const [domains, setDomains] = useState<DomainNumber[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    adminService
      .listDomainNumbers()
      .then(setDomains)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the domains"));
  }, []);

  return (
    <>
      <PageHeader
        title="Domain numbers"
        subtitle="One shared number per domain, answered by the assistant that compares all of that domain's partners"
      />
      <p className="muted">
        Use the number you set up in Vapi, with its country code. A business can also have its own number on its Phone page. One
        number can belong to only one business or domain.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="card table-card">
        {domains === null && !error && <p className="muted">Loading…</p>}
        {domains?.length === 0 && <p className="muted empty">No domains yet.</p>}
        {domains && domains.length > 0 && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>Number and transfer number</th>
                </tr>
              </thead>
              <tbody>
                {domains.map((d) => (
                  <DomainRow key={d.id} domain={d} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
