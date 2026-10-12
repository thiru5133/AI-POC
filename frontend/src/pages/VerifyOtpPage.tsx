import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { homePathFor, useAuth } from "../auth/AuthContext";
import { ApiError } from "../services/apiClient";
import { authService } from "../services/authService";

/** First login / sign-up: enter the code emailed to the account to confirm the address and start the session. */
export function VerifyOtpPage() {
  const { verifyOtp } = useAuth();
  const navigate = useNavigate();
  const email = (useLocation().state as { email?: string } | null)?.email;

  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!email) return <Navigate to="/login" replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const user = await verifyOtp(email!, code.trim());
      navigate(homePathFor(user), { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not verify the code");
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError(null);
    setNotice(null);
    try {
      await authService.resendOtp(email!);
      setNotice("We sent you a new code.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send a new code");
    }
  }

  return (
    <form className="card form" onSubmit={onSubmit}>
      <h1>Verify your email</h1>
      <p className="muted">
        We sent a 6-digit code to <strong>{email}</strong>. Enter it to continue.
      </p>
      <label>
        Verification code
        <input
          required
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          maxLength={6}
          title="The 6-digit code from your email"
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="success" role="status">
          {notice}
        </p>
      )}
      <button type="submit" className="primary" disabled={busy || code.trim().length !== 6}>
        {busy ? "Verifying…" : "Verify and continue"}
      </button>
      <p className="muted">
        Didn't get it?{" "}
        <button type="button" className="link-button" onClick={() => void resend()}>
          Send a new code
        </button>{" "}
        · <Link to="/login">Back to log in</Link>
      </p>
    </form>
  );
}
