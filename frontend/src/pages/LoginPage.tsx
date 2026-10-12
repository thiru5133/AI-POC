import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { homePathFor, useAuth } from "../auth/AuthContext";
import { ApiError } from "../services/apiClient";

export function LoginPage() {
  const { user, loading, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from;

  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && user) return <Navigate to={from ?? homePathFor(user)} replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await login(identifier, password);
      if ("otpRequired" in result) {
        // First login: a code was emailed; entering it finishes the login.
        navigate("/verify", { replace: true, state: { email: result.email } });
        return;
      }
      navigate(from ?? homePathFor(result.user), { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card form" onSubmit={onSubmit}>
      <h1>Log in</h1>
      <label>
        Email
        <input
          type="email"
          autoComplete="username"
          required
          value={identifier}
          onChange={(e) => setIdentifier(e.target.value)}
        />
      </label>
      <label>
        Password
        <input
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="primary" disabled={busy}>
        {busy ? "Signing in…" : "Log in"}
      </button>
      <p className="muted">
        New here? <Link to="/register">Sign up</Link>
      </p>
    </form>
  );
}
