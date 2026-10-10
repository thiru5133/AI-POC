import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "../../components/PageHeader";
import { ApiError } from "../../services/apiClient";
import { adminService } from "../../services/adminService";
import type { OnboardingRequest } from "../../types";
import { formatDateTime } from "../../utils/date";

export function RequestsPage() {
  const [requests, setRequests] = useState<OnboardingRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRequests(await adminService.listRequests("pending"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load requests");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function review(request: OnboardingRequest, action: "approve" | "reject") {
    let reason: string | undefined;
    if (action === "reject") {
      const answer = window.prompt(`Reason for rejecting ${request.email} (optional)`);
      if (answer === null) return; // cancelled
      reason = answer.trim();
    }
    setBusyId(request.id);
    setError(null);
    try {
      await (action === "approve" ? adminService.approve(request.id) : adminService.reject(request.id, reason));
      setRequests((current) => current?.filter((r) => r.id !== request.id) ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed");
      await load();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Onboarding requests"
        subtitle="Admins waiting for access"
        actions={requests ? <span className="badge">{requests.length} pending</span> : undefined}
      />
      <div className="card table-card">
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {requests === null && !error && <p className="muted">Loading…</p>}
        {requests?.length === 0 && <p className="muted empty">No pending requests.</p>}
        {requests && requests.length > 0 && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Requested</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {requests.map((r) => (
                  <tr key={r.id}>
                    <td>{r.name}</td>
                    <td>{r.email}</td>
                    <td>{formatDateTime(r.createdAt)}</td>
                    <td className="actions">
                      <button
                        type="button"
                        className="primary small"
                        disabled={busyId === r.id}
                        onClick={() => void review(r, "approve")}
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        className="danger small"
                        disabled={busyId === r.id}
                        onClick={() => void review(r, "reject")}
                      >
                        Reject
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
