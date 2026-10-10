import { Link, useLocation } from "react-router-dom";

export function PendingApprovalPage() {
  const state = useLocation().state as { email?: string; justRegistered?: boolean } | null;

  return (
    <div className="card">
      <h1>{state?.justRegistered ? "Request submitted" : "Awaiting approval"}</h1>
      <p>
        Your admin access request{state?.email ? ` for ${state.email}` : ""} is waiting for a superadmin to review it.
        You will be able to log in once it is approved.
      </p>
      <p className="muted">
        <Link to="/login">Back to log in</Link>
      </p>
    </div>
  );
}
