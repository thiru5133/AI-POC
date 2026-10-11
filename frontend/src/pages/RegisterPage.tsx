import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../services/apiClient";
import { authService } from "../services/authService";

export function RegisterPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await authService.register(name, email, organizationName);
      navigate("/pending", { replace: true, state: { email, justRegistered: true } });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not submit your request");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card form" onSubmit={onSubmit}>
      <h1>Request admin access</h1>
      <p className="muted">
        A superadmin must approve your request. Once approved, your password is emailed to you.
      </p>
      <label>
        Name (you can also log in with it, so it must be unique)
        <input
          required
          maxLength={200}
          pattern="[^@]+"
          title="Name cannot contain @"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label>
        Organization name (shown to callers)
        <input required maxLength={200} value={organizationName} onChange={(e) => setOrganizationName(e.target.value)} />
      </label>
      <label>
        Email (your password is sent here)
        <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="primary" disabled={busy}>
        {busy ? "Submitting…" : "Submit request"}
      </button>
      <p className="muted">
        Already approved? <Link to="/login">Log in</Link>
      </p>
    </form>
  );
}
