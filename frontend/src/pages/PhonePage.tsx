import { useEffect, useState, type FormEvent } from "react";
import { PageHeader } from "../components/PageHeader";
import { ApiError } from "../services/apiClient";
import { phoneService } from "../services/phoneService";
import type { PhoneSettings } from "../types";

/** The number customers call, and the number a call is handed to when they ask for a person. */
export function PhonePage() {
  const [settings, setSettings] = useState<PhoneSettings | null>(null);
  const [number, setNumber] = useState("");
  const [transfer, setTransfer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    phoneService
      .get()
      .then((s) => {
        if (!active) return;
        setSettings(s);
        setNumber(s.number ?? "");
        setTransfer(s.transferNumber ?? "");
      })
      .catch((err) => active && setError(err instanceof ApiError ? err.message : "Could not load your phone settings"));
    return () => {
      active = false;
    };
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const s = await phoneService.save(number, transfer);
      setSettings(s);
      setNumber(s.number ?? "");
      setTransfer(s.transferNumber ?? "");
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your phone settings");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader title="Phone" subtitle="Let customers call your AI receptionist on a real phone number" />
      {settings && !settings.ready && (
        <p className="error" role="status">
          This server is not set up for phone calls yet: it needs PUBLIC_BASE_URL
          {settings.provider === "vapi" ? "" : " and the Twilio credentials"}. Ask your platform administrator.
        </p>
      )}
      {settings?.domainNumber && (
        <div className="card">
          <h2>Your {settings.domainName ?? "domain"} line</h2>
          <p className="muted">
            Callers to <strong>{settings.domainNumber}</strong> reach the assistant that compares every{" "}
            {settings.domainName ?? "partner"} business, not only yours. It is set by the platform administrator. Your own number
            below is optional: it reaches only your business.
          </p>
        </div>
      )}
      <form className="card form" onSubmit={onSubmit}>
        <h2>Your number</h2>
        <label>
          Business phone number (optional)
          <input value={number} onChange={(e) => setNumber(e.target.value)} placeholder="+914412345678" inputMode="tel" />
        </label>
        <p className="muted">
          The number customers dial, with its country code. It must be the number set up for calls (in Vapi or Twilio), and
          customers will see exactly what you save. Leave empty to turn phone calls off.
        </p>
        <label>
          Transfer to a person
          <input value={transfer} onChange={(e) => setTransfer(e.target.value)} placeholder="+919876543210" inputMode="tel" />
        </label>
        <p className="muted">
          When a caller asks for a person, or the assistant flags an emergency, the call is handed to this number. Transfers only
          happen during your operating hours.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {saved && <p role="status">Saved.</p>}
        <button type="submit" className="primary" disabled={saving || !settings}>
          {saving ? "Saving…" : "Save"}
        </button>
      </form>
      {settings?.publicUrl && (
        <div className="card">
          <h2>Share your number</h2>
          <p className="muted">
            Customers can see your number in the app, and on this page that needs no login. Link to it from your website:
          </p>
          <code className="webhook-url">{settings.publicUrl}</code>
        </div>
      )}
      {settings?.webhookUrl && (
        <div className="card">
          {settings.provider === "vapi" ? (
            <>
              <h2>Connect it in Vapi</h2>
              <p className="muted">
                In the Vapi dashboard, open your number and set its <strong>Server URL</strong> to this URL, with the server
                credential your platform administrator gave you. Leave the number without an assistant.
              </p>
            </>
          ) : (
            <>
              <h2>Connect it in Twilio</h2>
              <p className="muted">
                In the Twilio console, open your number and set <strong>A call comes in</strong> to a Webhook (HTTP POST) with this
                URL:
              </p>
            </>
          )}
          <code className="webhook-url">{settings.webhookUrl}</code>
        </div>
      )}
    </>
  );
}
