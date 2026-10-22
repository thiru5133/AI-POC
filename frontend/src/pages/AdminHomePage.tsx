import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/PageHeader";
import { ApiError } from "../services/apiClient";
import { usageService } from "../services/usageService";
import type { Usage } from "../types";

const PERIOD_DAYS = 30;

export function AdminHomePage() {
  const { user } = useAuth();
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    usageService
      .get(PERIOD_DAYS)
      .then((u) => active && setUsage(u))
      .catch((err) => active && setError(err instanceof ApiError ? err.message : "Could not load your usage"));
    return () => {
      active = false;
    };
  }, []);

  const tiles = usage && [
    { label: "Conversations", value: usage.conversations },
    { label: "Customer messages", value: usage.messages },
    { label: "Voice minutes", value: usage.voiceMinutes },
    { label: "Bookings (estimated)", value: usage.bookings },
    { label: "Confirmations sent", value: usage.confirmations },
    { label: "Actions run", value: usage.toolCalls },
  ];

  return (
    <>
      <PageHeader title="Dashboard" subtitle={`Welcome back, ${user?.name ?? ""}`} />
      <div className="card">
        <h2>Usage, last {PERIOD_DAYS} days</h2>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!tiles && !error && <p className="muted">Loading…</p>}
        {tiles && (
          <dl className="usage-grid" aria-label="Usage">
            {tiles.map((t) => (
              <div key={t.label} className="usage-tile">
                <dd>{t.value.toLocaleString()}</dd>
                <dt>{t.label}</dt>
              </div>
            ))}
          </dl>
        )}
      </div>
      <div className="card">
        <h2>Get started</h2>
        <p className="muted">Connect your systems under MCP integration, review what customers asked under Conversations, or try the assistant yourself.</p>
        <Link to="/chat" className="button primary">
          Try your assistant
        </Link>
      </div>
    </>
  );
}
