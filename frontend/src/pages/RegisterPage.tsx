import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../services/apiClient";
import { authService } from "../services/authService";

/** Sign-up: create an account, then confirm the emailed code before the first session starts. */
export function RegisterPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await authService.register(name, email, password);
      navigate("/verify", { replace: true, state: { email } });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create your account");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card form" onSubmit={onSubmit}>
      <h1>Sign up</h1>
      <p className="muted">Create an account to ask questions and make bookings with our businesses. We'll email you a code to confirm your address.</p>
      <label>
        Name
        <input required maxLength={200} autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        Email
        <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label>
        Password (at least 8 characters)
        <input
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          maxLength={128}
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
        {busy ? "Signing up…" : "Sign up"}
      </button>
      <p className="muted">
        Already have an account? <Link to="/login">Log in</Link>
      </p>
    </form>
  );
}
